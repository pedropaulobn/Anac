# -*- coding: utf-8 -*-
"""carrega_bigquery.py — le o siros.csv (DEP+ARR ja processado) e carrega
duas tabelas no BigQuery (projeto barsa-509512, dataset aviacao_mercado):

  siros_internacional     grao diario, so voos internacionais, 23 aeroportos
                           de interesse (Fraport + concorrentes/vizinhos).
  siros_domestico_resumo  agregado por mes/aeroporto/OD/empresa, so voos
                           domesticos de POA/FOR/JJD (frequencia + assentos).

Ambas as tabelas sao SUBSTITUIDAS a cada rodada (WRITE_TRUNCATE), pelo
mesmo motivo que o siros.csv em si e substitutivo: a base reflete a malha
"vista de hoje" para o futuro, nao um historico. Comparacao dia-a-dia fica
por conta do agente que consome isso (Claude), nao de acumulo aqui dentro.

Nunca derruba o run principal: qualquer excecao e logada e engolida por
quem chama (ver robo/main.py, _processar_siros).
"""

from __future__ import annotations

import io
import json
import os
from datetime import date

import pandas as pd

PROJETO = "barsa-509512"
DATASET = "aviacao_mercado"
TABELA_INTL = "siros_internacional"
TABELA_DOM = "siros_domestico_resumo"

# ICAO dos 23 aeroportos de interesse (Fraport + Tier 1 + demais monitorados)
AEROPORTOS_INTERESSE = {
    "SBPA": "POA",  # Porto Alegre (Fraport)
    "SBFZ": "FOR",  # Fortaleza (Fraport)
    "SBJE": "JJD",  # Jericoacoara (Fraport)
    "SBSG": "NAT",  # Natal
    "SBRF": "REC",  # Recife
    "SBSV": "SSA",  # Salvador
    "SBJU": "JDO",  # Juazeiro do Norte
    "SBBE": "BEL",  # Belem
    "SBBR": "BSB",  # Brasilia
    "SBCF": "CNF",  # Confins
    "SBGL": "GIG",  # Galeao
    "SBRJ": "SDU",  # Santos Dumont
    "SBKP": "VCP",  # Viracopos
    "SBGR": "GRU",  # Guarulhos
    "SBSP": "CGH",  # Congonhas
    "SBEG": "MAO",  # Manaus
    "SBCT": "CWB",  # Curitiba
    "SBFL": "FLN",  # Florianopolis
    "SBPK": "PET",  # Pelotas
    "SBCX": "CXJ",  # Caxias do Sul
    "SBMO": "MCZ",  # Maceio (Alagoas)
    "SBJP": "JPA",  # Joao Pessoa
    "SBSL": "SLZ",  # Sao Luis
}

# So o resumo domestico entra pros 3 aeroportos da Fraport
AEROPORTOS_DOMESTICO = {"SBPA", "SBFZ", "SBJE"}

_DIAS_SEMANA_PT = {
    0: "segunda", 1: "terca", 2: "quarta", 3: "quinta",
    4: "sexta", 5: "sabado", 6: "domingo",
}


def _client():
    """Cria o client do BigQuery a partir da credencial em
    GCP_SA_KEY_BIGQUERY (conteudo JSON da service account, no ambiente).
    Import tardio de google-cloud-bigquery para nao quebrar quem nao usa
    esta etapa (requirements.txt so precisa listar a lib pra quem chamar)."""
    from google.cloud import bigquery
    from google.oauth2 import service_account

    chave_json = os.environ.get("GCP_SA_KEY_BIGQUERY")
    if not chave_json:
        raise RuntimeError(
            "GCP_SA_KEY_BIGQUERY nao encontrada no ambiente "
            "(configure o secret no GitHub Actions)."
        )
    info = json.loads(chave_json)
    credenciais = service_account.Credentials.from_service_account_info(info)
    return bigquery.Client(project=PROJETO, credentials=credenciais)


def _preparar_internacional(df: pd.DataFrame, data_extracao: str) -> pd.DataFrame:
    """Filtra DEP + Internacional + aeroportos de interesse; grao diario."""
    base = df[
        (df["Tipo"] == "DEP")
        & (df["Natureza"] == "Internacional")
        & (df["Aero Icao"].isin(AEROPORTOS_INTERESSE))
    ].copy()

    if base.empty:
        return pd.DataFrame(columns=[
            "data_local", "dia_semana", "mes_ref", "aeroporto_icao",
            "aeroporto_iata", "od_icao", "od_iata", "od_pais",
            "empresa_icao", "empresa_nome", "voo", "aeronave", "assentos",
            "tipo", "hora_local", "data_extracao",
        ])

    data_local = pd.to_datetime(base["Data"], errors="coerce")
    out = pd.DataFrame({
        "data_local": data_local.dt.date.astype("string"),
        "dia_semana": data_local.dt.dayofweek.map(_DIAS_SEMANA_PT),
        "mes_ref": data_local.dt.to_period("M").dt.to_timestamp().dt.date.astype("string"),
        "aeroporto_icao": base["Aero Icao"],
        "aeroporto_iata": base.get("Aero"),
        "od_icao": base.get("OD Icao"),
        "od_iata": base.get("OD"),
        "od_pais": base.get("OD State/Country"),
        "empresa_icao": base.get("Airline Icao"),
        "empresa_nome": base.get("Airline"),
        "voo": base.get("Voo"),
        "aeronave": base.get("Aircraft"),
        "assentos": pd.to_numeric(base.get("Seats"), errors="coerce").astype("Int64"),
        "tipo": base.get("Group"),  # Pax/Cargo/Others
        "hora_local": base.get("Hora"),
        "data_extracao": data_extracao,
    })
    return out.dropna(subset=["data_local"])


def _preparar_domestico_resumo(df: pd.DataFrame, data_extracao: str) -> pd.DataFrame:
    """Filtra DEP + Domestica + POA/FOR/JJD; agrega por mes/aeroporto/OD/empresa."""
    base = df[
        (df["Tipo"] == "DEP")
        & (df["Natureza"] == "Doméstica")
        & (df["Aero Icao"].isin(AEROPORTOS_DOMESTICO))
    ].copy()

    if base.empty:
        return pd.DataFrame(columns=[
            "mes_ref", "aeroporto_icao", "od_icao", "od_iata",
            "empresa_icao", "empresa_nome", "partidas_mes",
            "assentos_totais_mes", "data_extracao",
        ])

    data_local = pd.to_datetime(base["Data"], errors="coerce")
    base["_mes_ref"] = data_local.dt.to_period("M").dt.to_timestamp().dt.date.astype("string")
    base["_seats"] = pd.to_numeric(base.get("Seats"), errors="coerce").fillna(0)

    agrupado = (
        base.groupby(
            ["_mes_ref", "Aero Icao", "OD Icao", "OD", "Airline Icao", "Airline"],
            dropna=False,
        )
        .agg(partidas_mes=("Voo", "count"), assentos_totais_mes=("_seats", "sum"))
        .reset_index()
    )
    agrupado = agrupado.rename(columns={
        "_mes_ref": "mes_ref",
        "Aero Icao": "aeroporto_icao",
        "OD Icao": "od_icao",
        "OD": "od_iata",
        "Airline Icao": "empresa_icao",
        "Airline": "empresa_nome",
    })
    agrupado["assentos_totais_mes"] = agrupado["assentos_totais_mes"].astype("Int64")
    agrupado["data_extracao"] = data_extracao
    return agrupado


def carregar(caminho_siros_csv: str, data_extracao: str | None = None) -> dict:
    """Le o siros.csv, monta as duas tabelas e substitui (WRITE_TRUNCATE)
    no BigQuery. Devolve {"internacional": n_linhas, "domestico": n_linhas}."""
    from google.cloud import bigquery

    data_extracao = data_extracao or date.today().isoformat()

    df = pd.read_csv(caminho_siros_csv, sep=";", encoding="utf-8-sig", dtype=str)
    df.columns = df.columns.str.strip()

    intl = _preparar_internacional(df, data_extracao)
    dom = _preparar_domestico_resumo(df, data_extracao)

    cliente = _client()

    for nome_tabela, tabela_df in (
        (TABELA_INTL, intl),
        (TABELA_DOM, dom),
    ):
        destino = f"{PROJETO}.{DATASET}.{nome_tabela}"
        job_config = bigquery.LoadJobConfig(
            write_disposition="WRITE_TRUNCATE",
            source_format=bigquery.SourceFormat.CSV,
            skip_leading_rows=1,
            autodetect=False,
        )
        # Carrega via CSV em memoria (mantem o schema ja criado na tabela,
        # evitando reinferir tipos a cada rodada).
        buffer = io.StringIO()
        tabela_df.to_csv(buffer, index=False)
        buffer.seek(0)
        job = cliente.load_table_from_file(buffer, destino, job_config=job_config)
        job.result()
        print(f"  [bigquery] {nome_tabela}: {len(tabela_df):,} linhas carregadas")

    return {"internacional": len(intl), "domestico": len(dom)}
