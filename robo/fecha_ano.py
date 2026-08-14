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

--------------------------------------------------------------------
ANO CORRENTE ("vivo"): fechar_ano_vivo()
--------------------------------------------------------------------
O ano em curso e um caso especial. Alem de empilhar os meses ja fechados,
anexa o Siros (voos futuros) a partir do primeiro dia apos o ultimo mes
historico -- dando visao continua "passado real + futuro previsto" num
unico arquivo de consumo. Diferente do YYYY.csv congelado dos anos
passados, este e regenerado todo dia pela opcao 1 do menu.

Detalhes do merge com Siros:
- CORTE: ultimo dia do ultimo mes com _final. Siros entra so com
  Data >= primeiro dia do mes seguinte.
- DEDUP DE FRONTEIRA: por fuso/atraso, um voo pode aparecer nos dois
  lados. Remove-se do Siros toda linha cuja chave ja exista no historico:
  [Airline Icao, Voo, Aero Icao, OD Icao, Data] (mesmo dia).
- COLUNAS: o Siros (31 cols) e reindexado para as 95 do _final so aqui,
  na juncao -- o siros.csv de origem nao e alterado. As colunas que o
  voo futuro nao preenche saem vazias.
- Se o siros.csv nao existir, NAO gera/sobrescreve o arquivo de consumo
  (preserva o do dia anterior) e apenas avisa.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
from pathlib import Path

import pandas as pd

# Reusa a ordem canonica das 95 colunas do arquivo final. Importar (em vez
# de duplicar a lista) garante que qualquer mudanca de layout no
# mescla_final se propague para o Siros reindexado automaticamente.
from .mescla_final import COLUNAS_FINAL

# Chave de dedup de fronteira Siros x historico (voo no mesmo dia).
# "airline + flightnumber + origem-destino + mesmo dia".
CHAVE_DEDUP = ["Airline Icao", "Voo", "Aero Icao", "OD Icao", "Data"]

NOME_SIROS = "siros.csv"


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


# ─────────────────────────────────────────── ano corrente (vivo + Siros)

def _parse_data(serie: pd.Series) -> pd.Series:
    """Parse robusto a formato da coluna Data (texto).

    O Siros grava ISO (YYYY-MM-DD); a Movimentacao herda o formato bruto da
    ANAC (pode ser dd/mm/aaaa). Deixamos o pandas inferir e usamos dayfirst
    como desempate -- assim o corte e o dedup funcionam nos dois lados sem
    depender de saber o formato exato de antemao.
    """
    d = pd.to_datetime(serie, errors="coerce", format="ISO8601")
    if d.isna().mean() > 0.5:  # ISO nao pegou -> tenta dd/mm/aaaa
        d = pd.to_datetime(serie, errors="coerce", dayfirst=True)
    return d


def _corte_por_nome(meses: list[int], ano: int) -> "pd.Timestamp":
    """Ultimo dia do maior mes presente NOS NOMES dos arquivos _final.

    Determinístico: se o ultimo arquivo e anac_2026-06_final.csv, o corte e
    30/06/2026 -- independente de qualquer linha vazada (voo com data de
    julho dentro do pacote de junho, por atraso/fuso). O dedup de fronteira
    cuida dessas linhas vazadas separadamente. As duas defesas ficam
    independentes: o nome do arquivo diz "ate que mes fechei"; o dedup
    remove duplicatas que escaparam do corte.
    """
    ultimo_mes = max(meses)
    ref = pd.Timestamp(year=ano, month=ultimo_mes, day=1)
    return (ref.to_period("M").to_timestamp("M")
            + pd.Timedelta(hours=23, minutes=59, seconds=59))


def _carregar_siros_alinhado(siros_csv: Path) -> pd.DataFrame:
    """Le o siros.csv e reindexa para as 95 colunas do _final (nulos onde
    nao ha). NAO altera o arquivo de origem -- alinhamento so em memoria."""
    s = pd.read_csv(siros_csv, sep=";", dtype=str, encoding="utf-8-sig")
    s = s.reindex(columns=COLUNAS_FINAL)  # sobra vira NaN; ordem canonica
    return s


def _dedup_fronteira(hist: pd.DataFrame, siros: pd.DataFrame) -> pd.DataFrame:
    """Remove do Siros as linhas cuja chave ja existe no historico.

    Chave = CHAVE_DEDUP (mesmo dia). A Data e normalizada para ISO nos dois
    lados so para a comparacao (nao muda o que sera gravado)."""
    def _chave(df: pd.DataFrame) -> pd.Series:
        d_iso = _parse_data(df["Data"]).dt.strftime("%Y-%m-%d")
        partes = [df[c].fillna("").astype(str).str.strip() for c in CHAVE_DEDUP[:-1]]
        partes.append(d_iso.fillna(""))
        return partes[0].str.cat(partes[1:], sep="|")

    chaves_hist = set(_chave(hist))
    k = _chave(siros)
    manter = ~k.isin(chaves_hist)
    removidos = int((~manter).sum())
    if removidos:
        print(f"    dedup fronteira: {removidos} voo(s) do Siros ja no historico")
    return siros[manter]


def fechar_ano_vivo(pasta_finais: str | Path, ano: int,
                    pasta_saida: str | Path,
                    siros_proc: str | Path) -> str | None:
    """Gera o arquivo de consumo do ano corrente: finais + Siros futuro.

    - Empilha anac_{ano}-MM_final.csv (o que houver).
    - Anexa o siros.csv filtrado para Data > ultimo mes historico, com
      dedup de fronteira e reindexado para as 95 colunas.
    - Se o siros.csv nao existir, NAO grava (preserva o consumo anterior).

    Devolve o caminho do {ano}.csv, ou None se nao gerou.
    """
    pasta_finais = Path(pasta_finais)
    padrao = str(pasta_finais / f"anac_{ano}-*_final.csv")
    arquivos = sorted(glob.glob(padrao))

    if not arquivos:
        print(f"  [aviso] nenhum _final de {ano}; consumo nao gerado")
        return None

    meses = [re.search(r"-(\d{2})_final", os.path.basename(a)).group(1)
             for a in arquivos]
    print(f"  {ano} (consumo): {len(arquivos)} mes(es) historico(s) -> "
          f"{', '.join(meses)}")

    hist = pd.concat(
        [pd.read_csv(a, sep=";", dtype=str, encoding="utf-8-sig") for a in arquivos],
        ignore_index=True,
    )

    # Siros e obrigatorio para o arquivo de consumo. Sem ele, preserva o
    # arquivo do dia anterior em vez de sobrescrever com meia-informacao.
    siros_csv = Path(siros_proc) / NOME_SIROS
    if not siros_csv.exists():
        print(f"  [PARA] siros.csv nao encontrado em {siros_proc}")
        print(f"         consumo {ano}.csv NAO regenerado (preservado o anterior).")
        print(f"         rode a ponte Drive->Corp (ou a opcao Siros) e tente de novo.")
        return None

    corte = _corte_por_nome([int(m) for m in meses], ano)
    siros = _carregar_siros_alinhado(siros_csv)
    print(f"    Siros bruto: {len(siros):,} linha(s)")

    sd = _parse_data(siros["Data"])
    antes = len(siros)
    siros = siros[sd > corte]
    print(f"    corte (por nome de arquivo): {corte.date()} | "
          f"Siros apos corte: {len(siros):,} de {antes:,} linha(s)")

    siros = _dedup_fronteira(hist, siros)

    grande = pd.concat([hist, siros], ignore_index=True)
    grande = grande.reindex(columns=COLUNAS_FINAL)  # garante 95 cols/ordem

    pasta_saida = Path(pasta_saida)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    saida = pasta_saida / f"{ano}.csv"
    grande.to_csv(saida, index=False, sep=";", encoding="utf-8-sig")
    tam = saida.stat().st_size / 1_048_576
    print(f"  gravado: {saida.name} ({len(hist):,} historico + {len(siros):,} "
          f"Siros = {len(grande):,} linhas, {tam:.1f} MB)")
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
    p = argparse.ArgumentParser(description="Fecha ano / stack multi-ano / consumo vivo")
    p.add_argument("--ano", type=int, help="ano a fechar")
    p.add_argument("--finais", help="pasta dos anac_YYYY-MM_final.csv")
    p.add_argument("--saida", required=True, help="pasta de saida (Historico/Anual)")
    p.add_argument("--stack", nargs=2, type=int, metavar=("INICIO", "FIM"),
                   help="junta YYYY.csv de INICIO..FIM num so")
    p.add_argument("--anual", help="pasta dos YYYY.csv (para --stack)")
    p.add_argument("--vivo", action="store_true",
                   help="gera o consumo do ano corrente (finais + Siros)")
    p.add_argument("--siros", help="pasta Siros/Processado (para --vivo)")
    args = p.parse_args()

    if args.stack:
        anos = list(range(args.stack[0], args.stack[1] + 1))
        r = stack_anos(args.anual or args.saida, anos, args.saida)
        return 0 if r else 1

    if args.vivo and args.ano and args.finais and args.siros:
        r = fechar_ano_vivo(args.finais, args.ano, args.saida, args.siros)
        return 0 if r else 1

    if args.ano and args.finais:
        r = fechar_ano(args.finais, args.ano, args.saida)
        return 0 if r else 1

    print("Use --ano + --finais [--vivo --siros PASTA] OU --stack INICIO FIM")
    return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
