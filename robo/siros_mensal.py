# -*- coding: utf-8 -*-
"""siros_mensal.py — congela um snapshot mensal do Siros (voos futuros).

Problema que isso resolve: a Movimentacao da ANAC sai com atraso (as
vezes o ultimo mes publicado fica 1-2 meses atras de hoje). O siros.csv
processado e SUBSTITUTIVO (sobrescrito todo dia) e, como o proprio site
da ANAC apaga os dias passados a cada publicacao, ele so contem voos a
partir do dia do download em diante. Isso cria um buraco entre o ultimo
mes fechado da Movimentacao e o dia de hoje -- nenhum registro cobre os
dias que ja passaram mas ainda nao viraram Movimentacao oficial.

Solucao: no primeiro dia de cada mes em que o robo roda (ou no primeiro
run apos o deploy desta funcionalidade, se o mes ja estiver em curso),
congela uma copia do siros.csv daquele dia filtrada para o mes corrente
(coluna 'Data', ja com o flip DEP/ARR aplicado por processa_siros) e
nunca mais sobrescreve -- vira um retrato fixo daquele mes. A juncao
desses arquivos mensais na visao final (unificacao) fica para depois;
aqui so garantimos que o arquivo mensal existe.

Chave no manifest: 'siros/mensal/AAAA-MM'. Uma vez registrada, o mes
nunca mais e recapturado -- roda uma vez por mes, nao todo dia.

Nao ha logica de exclusao aqui: os arquivos mensais se acumulam em
Siros/Mensal/ ate que a unificacao futura decida o que fazer com eles.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

CHAVE_PREFIXO = "siros/mensal"


def periodo_atual() -> str:
    """Periodo (AAAA-MM) do dia de hoje."""
    hoje = date.today()
    return f"{hoje.year}-{hoje.month:02d}"


def chave(periodo: str) -> str:
    return f"{CHAVE_PREFIXO}/{periodo}"


def ja_capturado(m: dict, periodo: str) -> bool:
    """True se o mes ja foi congelado (existe no manifest)."""
    return chave(periodo) in m.get("arquivos", {})


def congelar(caminho_siros_csv: str | Path, pasta_saida: str | Path,
             periodo: str | None = None) -> Path | None:
    """Filtra o siros.csv processado (com flip DEP/ARR ja aplicado) para
    o mes 'periodo' (AAAA-MM, default: mes corrente) e grava
    siros_mensal_AAAA-MM.csv em pasta_saida.

    Filtro pela coluna 'Data' (nao 'OD Data'): cada linha, seja DEP ou
    ARR, carrega no campo 'Data' a sua propria data local apos o flip
    -- e o mesmo criterio que fecha_ano.py ja usa para cortar/dedupar
    o Siros na consolidacao anual.

    Devolve o caminho gravado, ou None se nao houver nenhuma linha
    daquele mes no arquivo (nao deveria acontecer no fluxo normal, mas
    evita gravar um arquivo vazio).
    """
    periodo = periodo or periodo_atual()
    ano, mes = (int(x) for x in periodo.split("-"))

    df = pd.read_csv(caminho_siros_csv, sep=";", dtype=str, encoding="utf-8-sig")
    d = pd.to_datetime(df["Data"], errors="coerce", format="ISO8601")
    filtro = (d.dt.year == ano) & (d.dt.month == mes)
    recorte = df[filtro]

    if recorte.empty:
        print(f"  [siros-mensal] nenhuma linha de {periodo} no siros.csv; nao grava")
        return None

    pasta_saida = Path(pasta_saida)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    nome = f"siros_mensal_{periodo}.csv"
    saida = pasta_saida / nome
    recorte.to_csv(saida, index=False, sep=";", encoding="utf-8-sig")
    print(f"  [siros-mensal] {periodo}: {len(recorte):,} linha(s) -> {nome}")
    return saida
