# -*- coding: utf-8 -*-
"""carrega_bigquery.py -- gera os 2 CSVs de resumo do BigQuery a partir do
siros.csv (DEP+ARR ja processado) e os envia ao Drive.

A CARGA no BigQuery deixou de ser feita aqui (fluxo 29/09/2026):
o robo so gera os arquivos e sobe pro Drive; o BigQuery le do Drive
(tabela externa ou carga feita pela Barsa). Assim uma falha de carga
nunca derruba o run e o arquivo ja esta no Drive para retentar.

  siros_internacional.csv     grao diario, so voos internacionais, 23
                              aeroportos de interesse (Fraport + concorrentes/vizinhos).
  siros_domestico_resumo.csv  agregado por mes/aeroporto/OD/empresa, so voos
                              domesticos de POA/FOR/JJD (frequencia + assentos).

Ambos sao SUBSTITUIDOS a cada rodada (a base e a malha "vista de hoje").
Destino no Drive: gdrive:Sync/Fraport/Anac/Siros/BigQuery/

Nunca derruba o run principal: qualquer excecao e logada e engolida por
quem chama (ver robo/main.py, _processar_siros).
"""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pandas as pd

from . import comum

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


DESTINO_DRIVE = f"{comum.DRIVE_RAIZ}/Anac/Siros/BigQuery/"


def _enviar_drive(caminho: Path) -> None:
    """rclone copy (sobrescreve o mesmo nome). Levanta erro se falhar."""
    cmd = [comum.rclone_bin(), "copy", str(caminho), DESTINO_DRIVE, "--verbose"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"rclone falhou ({r.returncode}): {r.stderr.strip()[-500:]}")
    print(f"  [bigquery-drive] {caminho.name} ({caminho.stat().st_size/1_048_576:.1f} MB) "
          f"-> {DESTINO_DRIVE}")


def carregar(caminho_siros_csv: str, data_extracao: str | None = None) -> dict:
    """Le o siros.csv, gera os 2 CSVs de resumo e envia ao Drive.

    Mantem o nome/retorno antigo ({"internacional": n, "domestico": n})
    para nao mexer em robo/main.py.
    """
    data_extracao = data_extracao or date.today().isoformat()

    df = pd.read_csv(caminho_siros_csv, sep=";", encoding="utf-8-sig", dtype=str)
    df.columns = df.columns.str.strip()

    intl = _preparar_internacional(df, data_extracao)
    dom = _preparar_domestico_resumo(df, data_extracao)

    saida = Path(comum.tmp()) / "bigquery"
    saida.mkdir(parents=True, exist_ok=True)

    for nome, tabela_df in ((TABELA_INTL, intl), (TABELA_DOM, dom)):
        arq = saida / f"{nome}.csv"
        # utf-8 puro (sem BOM), virgula, cabecalho na 1a linha
        tabela_df.to_csv(arq, index=False, encoding="utf-8")
        _enviar_drive(arq)

    return {"internacional": len(intl), "domestico": len(dom)}
