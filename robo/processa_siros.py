# -*- coding: utf-8 -*-
"""processa_siros.py — voos futuros (voos.csv) -> movimentacao futura.

Substitui o motor antigo que usava o futuro.csv (incompleto). O voos.csv
ja vem expandido (1 linha por voo por dia), entao nao ha explosao de
datas: e leitura direta + classificacao + lookups + flip DEP/ARR.

Objetivo: sair com o MAXIMO de colunas em comum com a Movimentacao ANAC,
para empilhar as duas no BI. O que nao existe no futuro fica null.

Fonte: voos.csv (sep=';', utf-8-sig, 1a linha e disclaimer -> skip).
Saida: siros_YYYY-MM-DD.csv (substitutivo; com flip DEP+ARR).

Conversao de horario: voos.csv traz horarios em UTC. Convertidos para
local via 'UTC Offset' do Airports (origem). Plano B por UF quando o
aeroporto nao e encontrado. Isso e o que faz a Data local bater com a
Movimentacao na deduplicacao mensal.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import pandas as pd

# Colunas do voos.csv (apos skip da 1a linha)
COL_EMP_ICAO = "Sigla ICAO Empresa Aérea"
COL_EMP_NOME = "Nome da Empresa Aérea"
COL_ETAPA = "Número Etapa"
COL_VOO = "Número Voo"
COL_ACFT = "Sigla ICAO Modelo Aeronave"
COL_SEATS = "Quantidade de Assentos Previstos"
COL_ORIG = "Sigla ICAO Aeroporto Origem"
COL_PART = "Data Partida Prevista UTC"
COL_DEST = "Sigla ICAO Aeroporto Destino"
COL_CHEG = "Data Chegada Prevista UTC"
COL_TIPO = "Tipo de Voo"

FATOR_OCUPACAO = 0.8

# Plano B: offset por UF (Brasil). A base Airports hoje marca tudo -03,
# mas mantemos o mapa correto para quando ela for corrigida ou o
# aeroporto nao for encontrado. Horario de verao foi extinto em 2019.
OFFSET_UF = {
    "AC": -5, "AM": -4, "RO": -4, "RR": -4, "MT": -4, "MS": -4,
    "AP": -3, "PA": -3, "TO": -3, "MA": -3, "PI": -3, "CE": -3,
    "RN": -3, "PB": -3, "PE": -3, "AL": -3, "SE": -3, "BA": -3,
    "MG": -3, "ES": -3, "RJ": -3, "SP": -3, "PR": -3, "SC": -3,
    "RS": -3, "GO": -3, "DF": -3,
}
OFFSET_PADRAO = -3  # se nada mais servir

# Colunas finais (as mesmas 75 da Movimentacao DEP; null onde nao existe)
COLUNAS_MOV = [
    "Airline Icao", "Airline", "Voo", "Fln Icao", "Fln",
    "Id Voo", "Id Linha", "Natureza", "Tipo", "Base", "Etapa", "Escala",
    "Hora", "Data", "OD Hora", "OD Data",
    "Aero Icao", "Aero", "Aeroporto", "Cidade", "UF", "Região", "País", "Continente",
    "OD Icao", "OD", "OD Aeroporto", "OD Cidade", "OD UF", "OD Região", "OD País", "OD Continente",
    "Aircraft", "Acft Modelo", "Matrícula", "Acft Group", "Mtow", "Acft Fra Group",
    "Combustível (L)", "Seats", "Payload Capacidade (Kg)", "Distância (Km)",
    "PAX Pagos", "PAX Grátis", "Bagagem Livre (Kg)", "Bagagem Excesso (Kg)",
    "Carga Paga (Kg)", "Carga Grátis (Kg)", "Correios (Kg)",
    "Decolagens", "Horas Voadas", "Peso Útil (Kg)", "Vméd (Km/h)", "Ask", "Rpk",
    "Pax Total", "LF", "Cargo Total", "Group", "Chave", "KeyTkt",
    "CD Dest: PAX Pagos", "CD Dest: PAX Grátis", "CD Dest: Bags Livre (kg)",
    "CD Dest: Bags Excesso (kg)", "CD Dest: Carga Paga (kg)",
    "CD Dest: Carga Grátis (kg)", "CD Dest: Correios (kg)",
    "CI Dest: PAX Pagos", "CI Dest: PAX Grátis", "CI Dest: Bags Livre (kg)",
    "CI Dest: Bags Excesso (kg)", "CI Dest: Carga Paga (kg)",
    "CI Dest: Carga Grátis (kg)", "CI Dest: Correios (kg)",
]

# Colunas que trocam origem<->destino no flip ARR (geo)
_SWAP_GEO = [
    ("Aero Icao", "OD Icao"), ("Aero", "OD"),
    ("Aeroporto", "OD Aeroporto"), ("Cidade", "OD Cidade"),
    ("UF", "OD UF"), ("Região", "OD Região"),
    ("País", "OD País"), ("Continente", "OD Continente"),
]


# ─────────────────────────────────────────────────────────── lookups

def _norm_offset(txt) -> int:
    """'-03:00' ou '−03:00' (menos unicode) -> -3 (horas inteiras)."""
    if not isinstance(txt, str) or not txt.strip():
        return OFFSET_PADRAO
    s = txt.replace("\u2212", "-").strip()  # menos unicode -> ascii
    m = re.match(r"([+-]?)(\d{1,2})", s)
    if not m:
        return OFFSET_PADRAO
    sinal = -1 if m.group(1) == "-" else 1
    return sinal * int(m.group(2))


def carregar_airports(pasta_bases):
    """Airports: OD ICAO->ICAO (chave), + geo e offset. Dedup por ICAO.

    A planilha tem ICAO/IATA (originais) E OD ICAO/OD IATA. O M usa os
    'OD', entao dropamos os originais antes de renomear -- senao ficam
    colunas ICAO/IATA duplicadas.
    """
    caminho = Path(pasta_bases) / "Airports.xlsx"
    df = pd.read_excel(caminho, dtype=str)
    df.columns = df.columns.str.strip()
    df = df.drop(columns=[c for c in ("ICAO", "IATA") if c in df.columns])
    df = df.rename(columns={"OD ICAO": "ICAO", "OD IATA": "IATA"})
    manter = ["ICAO", "IATA", "Airport", "City", "UF", "Region",
              "Country", "Continent", "UTC Offset"]
    df = df[[c for c in manter if c in df.columns]].drop_duplicates("ICAO")
    df["_offset"] = df["UTC Offset"].apply(_norm_offset) if "UTC Offset" in df else OFFSET_PADRAO
    return df


def carregar_airlines(pasta_bases):
    caminho = Path(pasta_bases) / "Airlines.xlsx"
    df = pd.read_excel(caminho, dtype=str)
    df.columns = df.columns.str.strip()
    return df[["ICAO", "IATA/ICAO"]].drop_duplicates("ICAO")


def carregar_aircrafts(pasta_bases):
    caminho = Path(pasta_bases) / "Aircraft.xlsx"
    df = pd.read_excel(caminho, dtype=str)
    df.columns = df.columns.str.strip()
    df = df.rename(columns={"Name": "Aircraft", "Group": "Acft Group",
                            "MTOWF": "Mtow", "GROUPF": "Acft Fra Group"})
    cols = ["Aircraft", "Acft Group", "Mtow", "Acft Fra Group"]
    return df[[c for c in cols if c in df.columns]].drop_duplicates("Aircraft")


# ──────────────────────────────────────────────── classificacao Tipo Voo

def _classificar_tipo(t: str) -> tuple[str, str, str]:
    """'REGULAR DE PASSAGEIROS DOMÉSTICA' -> (Id Voo, Id Linha, Natureza)."""
    if not isinstance(t, str):
        return (None, None, None)
    up = t.upper().strip()
    natureza = "Internacional" if "INTERNACIONAL" in up else "Doméstica"
    corpo = up.replace("INTERNACIONAL", "").replace("DOMÉSTICA", "").strip()
    if "PASSAGEIRO" in corpo:
        linha = "Passageiros"
    elif "CARGA" in corpo or "CORREIO" in corpo:
        linha = "Carga"
    else:
        linha = "Others"
    id_voo = corpo.title().replace(" De ", " De ")  # Text.Proper aproximado
    return (id_voo, linha, natureza)


def _hora(dt: pd.Series) -> pd.Series:
    return dt.dt.strftime("%H:%M:%S")


# ─────────────────────────────────────────────────────── processamento

def processar(caminho_voos, pasta_saida, pasta_bases, data_exec=None):
    """Le voos.csv, processa e grava siros_YYYY-MM-DD.csv (com flip)."""
    from datetime import date
    data_exec = data_exec or date.today().isoformat()

    print(f"\n  Processando SIROS (voos futuros)")
    df = pd.read_csv(caminho_voos, sep=";", encoding="utf-8-sig",
                     dtype=str, skiprows=1)
    df.columns = df.columns.str.strip()
    print(f"    {len(df):,} linhas no voos.csv")

    # Datetimes UTC
    part = pd.to_datetime(df[COL_PART], format="%d/%m/%Y %H:%M:%S", errors="coerce")
    cheg = pd.to_datetime(df[COL_CHEG], format="%d/%m/%Y %H:%M:%S", errors="coerce")

    out = pd.DataFrame(index=df.index)
    out["Airline Icao"] = df[COL_EMP_ICAO]
    out["Voo"] = df[COL_VOO]
    out["Aircraft"] = df[COL_ACFT]
    out["Seats"] = pd.to_numeric(df[COL_SEATS], errors="coerce").astype("Int64")
    out["Etapa"] = pd.to_numeric(df[COL_ETAPA], errors="coerce").astype("Int64")
    out["Aero Icao"] = df[COL_ORIG]
    out["OD Icao"] = df[COL_DEST]

    # Classificacao do tipo
    cls = df[COL_TIPO].apply(_classificar_tipo)
    out["Id Voo"] = cls.apply(lambda x: x[0])
    out["Id Linha"] = cls.apply(lambda x: x[1])
    out["Natureza"] = cls.apply(lambda x: x[2])
    out["Group"] = out["Id Linha"].map(
        {"Passageiros": "Pax", "Carga": "Cargo"}).fillna("Others")

    # Lookups
    ap = carregar_airports(pasta_bases)
    al = carregar_airlines(pasta_bases)
    ac = carregar_aircrafts(pasta_bases)

    # Offset da ORIGEM para converter UTC->local
    off_map = ap.set_index("ICAO")["_offset"].to_dict()
    off = out["Aero Icao"].map(off_map).fillna(
        out["Aero Icao"].map(lambda ic: OFFSET_PADRAO))  # se nao achar, -3
    off_td = pd.to_timedelta(off.astype(float), unit="h")

    part_local = part + off_td
    cheg_local = cheg + off_td
    out["Data"] = part_local.dt.date.astype("string")
    out["Hora"] = _hora(part_local)
    out["OD Data"] = cheg_local.dt.date.astype("string")
    out["OD Hora"] = _hora(cheg_local)

    # Airlines
    out = out.merge(al.rename(columns={"ICAO": "Airline Icao",
                                       "IATA/ICAO": "Airline"}),
                    on="Airline Icao", how="left")
    out["Fln Icao"] = out["Airline Icao"].fillna("") + out["Voo"].fillna("")
    out["Fln"] = out["Airline"].fillna("") + out["Voo"].fillna("")

    # Airports origem: seleciona e renomeia a partir de colunas cruas,
    # evitando colisao de nomes no merge.
    ap_sel = ap.rename(columns={"Region": "Região", "Country": "País",
                                "Continent": "Continente"})
    cols_ap = ["ICAO", "IATA", "Airport", "City", "UF", "Região", "País", "Continente"]
    cols_ap = [c for c in cols_ap if c in ap_sel.columns]
    ap_sel = ap_sel[cols_ap]

    ap_o = ap_sel.rename(columns={
        "ICAO": "Aero Icao", "IATA": "Aero", "Airport": "Aeroporto",
        "City": "Cidade"})  # UF, Região, País, Continente ficam iguais
    out = out.merge(ap_o, on="Aero Icao", how="left")

    # Airports destino
    ap_d = ap_sel.rename(columns={
        "ICAO": "OD Icao", "IATA": "OD", "Airport": "OD Aeroporto",
        "City": "OD Cidade", "UF": "OD UF", "Região": "OD Região",
        "País": "OD País", "Continente": "OD Continente"})
    out = out.merge(ap_d, on="OD Icao", how="left")

    # Aircrafts
    out = out.merge(ac, on="Aircraft", how="left")

    # Calculadas
    out["Pax Total"] = (out["Seats"].astype("Float64") * FATOR_OCUPACAO).round().astype("Int64")
    out["Decolagens"] = 1
    out["Tipo"] = "DEP"
    out["Base"] = "Siros"

    # Preenche colunas ausentes com NA e ordena
    for c in COLUNAS_MOV:
        if c not in out.columns:
            out[c] = pd.NA
    dep = out[COLUNAS_MOV].copy()

    # Flip ARR
    arr = dep.copy()
    arr["Tipo"] = "ARR"
    # swap geo origem<->destino
    ren = {}
    for a, b in _SWAP_GEO:
        ren[a] = b
        ren[b] = a
    arr = arr.rename(columns=ren)
    # swap hora/data origem<->destino
    arr = arr.rename(columns={"Hora": "OD Hora", "OD Hora": "Hora",
                              "Data": "OD Data", "OD Data": "Data"})
    arr = arr[COLUNAS_MOV]  # reordena

    final = pd.concat([dep, arr], ignore_index=True)

    os.makedirs(pasta_saida, exist_ok=True)
    nome = f"siros_{data_exec}.csv"
    saida = os.path.join(pasta_saida, nome)
    final.to_csv(saida, index=False, sep=";", encoding="utf-8-sig")
    print(f"    gravado: {nome}  ({len(dep):,} DEP + {len(arr):,} ARR = "
          f"{len(final):,} linhas x {len(final.columns)} cols)")
    return saida


def _cli() -> int:
    p = argparse.ArgumentParser(description="Processa voos.csv (SIROS futuro)")
    p.add_argument("voos", help="caminho do voos.csv")
    p.add_argument("--saida", required=True)
    p.add_argument("--bases", required=True, help="pasta com Airports/Airlines/Aircraft")
    args = p.parse_args()
    r = processar(args.voos, args.saida, args.bases)
    return 0 if r else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
