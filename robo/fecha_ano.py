# -*- coding: utf-8 -*-
"""fecha_ano.py — empilha os meses finais de um ano num CSV congelado.

Roda no .bat local. Junta anac_YYYY-01_final.csv .. anac_YYYY-12_final.csv
num unico YYYY.csv, gravado na pasta Historico/Anual. Esse arquivo e o
"legado congelado": o BI Online passa a consumi-lo em vez de reprocessar
os meses.

Opcional: --stack junta varios anos ja fechados num so CSV (ex:
2020-2024.csv em Historico/Agrupado), para reduzir uploads no Dataflow.

Reprocessamento: e so rodar de novo. Idempotente. Se a ANAC republicar
um mes antigo, regenera-se aquele _final e refecha-se o ano.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
from pathlib import Path

import pandas as pd


def fechar_ano(pasta_finais: str | Path, ano: int,
               pasta_saida: str | Path) -> str | None:
    """Empilha os _final do ano. Devolve o caminho do YYYY.csv."""
    pasta_finais = Path(pasta_finais)
    padrao = str(pasta_finais / f"anac_{ano}-*_final.csv")
    arquivos = sorted(glob.glob(padrao))

    if not arquivos:
        print(f"  [aviso] nenhum _final para {ano} em {pasta_finais}")
        return None

    meses = [re.search(r"-(\d{2})_final", os.path.basename(a)).group(1)
             for a in arquivos]
    print(f"  {ano}: {len(arquivos)} mes(es) -> {', '.join(meses)}")
    if len(arquivos) < 12:
        print(f"  [ATENCAO] ano incompleto ({len(arquivos)}/12). "
              f"Fechando mesmo assim (regenere depois se faltar mes).")

    partes = []
    for a in arquivos:
        df = pd.read_csv(a, sep=";", dtype=str, encoding="utf-8-sig")
        partes.append(df)
    grande = pd.concat(partes, ignore_index=True)

    pasta_saida = Path(pasta_saida)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    saida = pasta_saida / f"{ano}.csv"
    grande.to_csv(saida, index=False, sep=";", encoding="utf-8-sig")
    tam = saida.stat().st_size / 1_048_576
    print(f"  gravado: {saida.name} ({len(grande):,} linhas, {tam:.1f} MB)")
    return str(saida)


def stack_anos(pasta_anual: str | Path, anos: list[int],
               pasta_saida: str | Path) -> str | None:
    """Junta varios YYYY.csv ja fechados num so (ex: 2020-2024.csv)."""
    pasta_anual = Path(pasta_anual)
    partes, presentes = [], []
    for ano in anos:
        caminho = pasta_anual / f"{ano}.csv"
        if not caminho.exists():
            print(f"  [aviso] {ano}.csv nao encontrado; pulado")
            continue
        partes.append(pd.read_csv(caminho, sep=";", dtype=str, encoding="utf-8-sig"))
        presentes.append(ano)
    if not partes:
        print("  [aviso] nenhum ano encontrado para o stack")
        return None

    grande = pd.concat(partes, ignore_index=True)
    pasta_saida = Path(pasta_saida)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    nome = f"{min(presentes)}-{max(presentes)}.csv"
    saida = pasta_saida / nome
    grande.to_csv(saida, index=False, sep=";", encoding="utf-8-sig")
    tam = saida.stat().st_size / 1_048_576
    print(f"  gravado: {nome} ({len(grande):,} linhas, {tam:.1f} MB, "
          f"{len(presentes)} anos)")
    return str(saida)


def _cli() -> int:
    p = argparse.ArgumentParser(description="Fecha ano / stack multi-ano")
    p.add_argument("--ano", type=int, help="ano a fechar")
    p.add_argument("--finais", help="pasta dos anac_YYYY-MM_final.csv")
    p.add_argument("--saida", required=True, help="pasta de saida (Historico/Anual)")
    p.add_argument("--stack", nargs=2, type=int, metavar=("INICIO", "FIM"),
                   help="junta YYYY.csv de INICIO..FIM num so")
    p.add_argument("--anual", help="pasta dos YYYY.csv (para --stack)")
    args = p.parse_args()

    if args.stack:
        anos = list(range(args.stack[0], args.stack[1] + 1))
        r = stack_anos(args.anual or args.saida, anos, args.saida)
        return 0 if r else 1

    if args.ano and args.finais:
        r = fechar_ano(args.finais, args.ano, args.saida)
        return 0 if r else 1

    print("Use --ano + --finais OU --stack INICIO FIM")
    return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
