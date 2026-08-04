# -*- coding: utf-8 -*-
"""agrupa_ticket.py — junta ticket DOM + INT de um mes num CSV so.

Roda no .bat local. Le ticket_dom_YYYY-MM.csv e/ou ticket_int_YYYY-MM.csv
e empilha (append) num ticket_YYYY-MM.csv. As Keys sao disjuntas (DOM =
rotas SBXX-SBXX; INT = pelo menos um aeroporto estrangeiro), entao nao ha
sobreposicao.

Se so um existe, gera o ticket so com ele. Quando o outro chegar, roda de
novo e sobrescreve com os dois. Idempotente.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd

COLUNAS = [
    "Key", "ANO", "MES", "EMPRESA", "ORIGEM", "DESTINO", "Pax",
    "Tkt Avg", "Tkt Min", "Tkt Max",
    "TktEco Avg", "TktBsn Avg", "TktFst Avg",
]


def agrupar(pasta: str | Path, ano: int, mes: int,
            pasta_saida: str | Path | None = None) -> str | None:
    """Agrupa DOM+INT do mes. Devolve o caminho do ticket_YYYY-MM.csv."""
    pasta = Path(pasta)
    pasta_saida = Path(pasta_saida) if pasta_saida else pasta
    periodo = f"{ano}-{mes:02d}"

    dom = pasta / f"ticket_dom_{periodo}.csv"
    int_ = pasta / f"ticket_int_{periodo}.csv"

    partes = []
    if dom.exists():
        partes.append(pd.read_csv(dom, sep=";", dtype=str, encoding="utf-8-sig"))
        print(f"  DOM: {dom.name} ({len(partes[-1])} rotas)")
    if int_.exists():
        partes.append(pd.read_csv(int_, sep=";", dtype=str, encoding="utf-8-sig"))
        print(f"  INT: {int_.name} ({len(partes[-1])} rotas)")

    if not partes:
        print(f"  [aviso] nenhum ticket (dom/int) para {periodo}")
        return None

    junto = pd.concat(partes, ignore_index=True)
    # Garante todas as colunas e a ordem
    for c in COLUNAS:
        if c not in junto.columns:
            junto[c] = pd.NA
    junto = junto[COLUNAS]

    pasta_saida.mkdir(parents=True, exist_ok=True)
    saida = pasta_saida / f"ticket_{periodo}.csv"
    junto.to_csv(saida, index=False, sep=";", encoding="utf-8-sig")
    print(f"  gravado: {saida.name} ({len(junto)} rotas)")
    return str(saida)


def _cli() -> int:
    p = argparse.ArgumentParser(description="Agrupa ticket DOM+INT de um mes")
    p.add_argument("periodo", help="AAAA-MM (ex: 2026-01)")
    p.add_argument("--pasta", required=True, help="pasta dos ticket_dom/int")
    p.add_argument("--saida", help="pasta de saida (default = --pasta)")
    args = p.parse_args()
    ano, mes = int(args.periodo[:4]), int(args.periodo[5:7])
    r = agrupar(args.pasta, ano, mes, args.saida)
    return 0 if r else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
