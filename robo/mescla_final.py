# -*- coding: utf-8 -*-
"""mescla_final.py — Movimentacao + Ticket + flip DEP/ARR = arquivo final.

Roda no .bat local. Pega a Movimentacao processada (75 cols, DEP) e o
ticket agrupado do mes, junta pela KeyTkt, e gera a visao DEP+ARR com as
95 colunas -- identica ao que o dataflow entregava.

Ordem das operacoes (fiel ao M original):
1. Merge ticket na Movimentacao (DEP) pela KeyTkt = Key  -> +6 colunas
2. Constroi ARR: duplica, troca origem<->destino (geo + hora/data),
   renomeia CD/CI Dest -> CD/CI Orig, Tipo = "ARR"
3. Empilha DEP + ARR -> 95 colunas
4. Grava anac_YYYY-MM_final.csv

O ticket carrega inalterado no flip: a tarifa da rota e a mesma vista como
partida ou chegada.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd

# Ordem exata das 95 colunas do arquivo final (do dataflow atual)
COLUNAS_FINAL = [
    "Airline Icao", "Airline", "Voo", "Id Voo", "Id Linha", "Natureza",
    "Hora", "Data", "Aero Icao", "Aero", "Aeroporto", "Cidade", "UF",
    "Região", "País", "Continente", "Etapa", "OD Hora", "OD Data",
    "Aircraft", "Acft Modelo", "Matrícula", "OD Icao", "OD", "OD Aeroporto",
    "OD Cidade", "OD UF", "OD Região", "OD País", "OD Continente", "Escala",
    "Combustível (L)", "Seats", "Payload Capacidade (Kg)", "Distância (Km)",
    "PAX Pagos", "PAX Grátis", "Bagagem Livre (Kg)", "Bagagem Excesso (Kg)",
    "Carga Paga (Kg)", "Carga Grátis (Kg)", "Correios (Kg)", "Decolagens",
    "Horas Voadas", "Peso Útil (Kg)", "Vméd (Km/h)", "Ask", "Rpk",
    "Pax Total", "LF", "Cargo Total", "Chave", "Tipo", "KeyTkt", "Group",
    "CD Dest: PAX Pagos", "CD Dest: PAX Grátis", "CD Dest: Bags Livre (kg)",
    "CD Dest: Bags Excesso (kg)", "CD Dest: Carga Paga (kg)",
    "CD Dest: Carga Grátis (kg)", "CD Dest: Correios (kg)",
    "CI Dest: PAX Pagos", "CI Dest: PAX Grátis", "CI Dest: Bags Livre (kg)",
    "CI Dest: Bags Excesso (kg)", "CI Dest: Carga Paga (kg)",
    "CI Dest: Carga Grátis (kg)", "CI Dest: Correios (kg)",
    "Acft Group", "Mtow", "Acft Fra Group",
    "Tkt Avg", "Tkt Min", "Tkt Max", "TktEco Avg", "TktBsn Avg", "TktFst Avg",
    "Fln Icao", "Fln", "Base",
    "CD Orig: PAX Pagos", "CD Orig: PAX Grátis", "CD Orig: Bags Livre (kg)",
    "CD Orig: Bags Excesso (kg)", "CD Orig: Carga Paga (kg)",
    "CD Orig: Carga Grátis (kg)", "CD Orig: Correios (kg)",
    "CI Orig: PAX Pagos", "CI Orig: PAX Grátis", "CI Orig: Bags Livre (kg)",
    "CI Orig: Bags Excesso (kg)", "CI Orig: Carga Paga (kg)",
    "CI Orig: Carga Grátis (kg)", "CI Orig: Correios (kg)",
    # Geo do Airports (por ICAO), no fim. Flip troca origem<->destino.
    "State/Country", "Region", "OD State/Country", "OD Region",
]

TKT_COLS = ["Tkt Avg", "Tkt Min", "Tkt Max", "TktEco Avg", "TktBsn Avg", "TktFst Avg"]

# Pares que trocam no flip ARR (origem <-> destino)
_SWAP = [
    ("Hora", "OD Hora"), ("Data", "OD Data"),
    ("Aero Icao", "OD Icao"), ("Aero", "OD"),
    ("Aeroporto", "OD Aeroporto"), ("Cidade", "OD Cidade"),
    ("UF", "OD UF"), ("Região", "OD Região"),
    ("País", "OD País"), ("Continente", "OD Continente"),
    ("State/Country", "OD State/Country"), ("Region", "OD Region"),
]

# CD/CI Dest -> Orig (14 colunas)
_DEST_ORIG = {
    f"{cx} Dest: {campo}": f"{cx} Orig: {campo}"
    for cx in ("CD", "CI")
    for campo in ("PAX Pagos", "PAX Grátis", "Bags Livre (kg)",
                  "Bags Excesso (kg)", "Carga Paga (kg)",
                  "Carga Grátis (kg)", "Correios (kg)")
}


def _merge_ticket(dep: pd.DataFrame, ticket: pd.DataFrame) -> pd.DataFrame:
    """Left join do ticket na Movimentacao pela KeyTkt = Key."""
    # Se a mov ja trouxer colunas de ticket (vazias), remove antes do
    # merge para nao gerar sufixos _x/_y.
    dep = dep.drop(columns=[c for c in TKT_COLS if c in dep.columns])
    t = ticket[["Key"] + [c for c in TKT_COLS if c in ticket.columns]].copy()
    t = t.rename(columns={"Key": "KeyTkt"}).drop_duplicates("KeyTkt")
    return dep.merge(t, on="KeyTkt", how="left")


def _construir_arr(dep: pd.DataFrame) -> pd.DataFrame:
    """Gera a visao ARR a partir da DEP ja com ticket."""
    arr = dep.copy()
    arr["Tipo"] = "ARR"
    # swap origem<->destino (geo + hora/data)
    ren = {}
    for a, b in _SWAP:
        ren[a] = b
        ren[b] = a
    arr = arr.rename(columns=ren)
    # CD/CI Dest -> Orig
    arr = arr.rename(columns=_DEST_ORIG)
    return arr


def mesclar(caminho_mov: str | Path, caminho_ticket: str | Path | None,
            pasta_saida: str | Path, ano: int, mes: int) -> str | None:
    """Mescla Mov + Ticket, faz o flip e grava anac_YYYY-MM_final.csv."""
    periodo = f"{ano}-{mes:02d}"
    print(f"\n  Mesclando final: {periodo}")

    dep = pd.read_csv(caminho_mov, sep=";", dtype=str, encoding="utf-8-sig")
    print(f"    Movimentação: {len(dep)} linhas, {len(dep.columns)} cols")

    if caminho_ticket and Path(caminho_ticket).exists():
        ticket = pd.read_csv(caminho_ticket, sep=";", dtype=str, encoding="utf-8-sig")
        dep = _merge_ticket(dep, ticket)
        casados = dep["Tkt Avg"].notna().sum()
        print(f"    Ticket: {len(ticket)} rotas, {casados} linhas casadas")
    else:
        print(f"    [aviso] sem ticket para {periodo}; colunas Tkt ficam vazias")
        for c in TKT_COLS:
            if c not in dep.columns:
                dep[c] = pd.NA

    arr = _construir_arr(dep)
    final = pd.concat([dep, arr], ignore_index=True)

    # Filtra Data nula/vazia (fiel ao M: SelectRows [Data] <> null e <> "")
    final = final[final["Data"].notna() & (final["Data"].astype(str).str.strip() != "")]

    # Garante as 95 colunas na ordem
    for c in COLUNAS_FINAL:
        if c not in final.columns:
            final[c] = pd.NA
    final = final[COLUNAS_FINAL]

    pasta_saida = Path(pasta_saida)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    saida = pasta_saida / f"anac_{periodo}_final.csv"
    final.to_csv(saida, index=False, sep=";", encoding="utf-8-sig")
    print(f"    gravado: {saida.name} ({len(final)} linhas x {len(final.columns)} cols)")
    return str(saida)


def _cli() -> int:
    p = argparse.ArgumentParser(description="Mescla Mov + Ticket + flip DEP/ARR")
    p.add_argument("periodo", help="AAAA-MM")
    p.add_argument("--mov", required=True, help="anac_YYYY-MM.csv (75 cols)")
    p.add_argument("--ticket", help="ticket_YYYY-MM.csv (opcional)")
    p.add_argument("--saida", required=True, help="pasta de saida")
    args = p.parse_args()
    ano, mes = int(args.periodo[:4]), int(args.periodo[5:7])
    r = mesclar(args.mov, args.ticket, args.saida, ano, mes)
    return 0 if r else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
