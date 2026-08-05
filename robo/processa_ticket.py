# -*- coding: utf-8 -*-
"""processa_ticket.py — processa tarifas DOM e INT (uma por vez).

Replica a logica do Power Query (Dom + TktAnc/INT), mas por ARQUIVO:
como o robo ja e certeiro (sabe que este CSV e o DOM de jan/26), nao
precisa varrer a pasta inteira e agrupar tudo -- processa so o mes.

Saidas separadas, para o .bat agrupar depois:
    ticket_dom_YYYY-MM.csv   (BRL direto, sem classe)
    ticket_int_YYYY-MM.csv   (USD->BRL via dolar, com classes F/J/Y)

Colunas de saida (iguais nas duas; INT preenche as de classe, DOM deixa null):
    Key, ANO, MES, EMPRESA, ORIGEM, DESTINO, Pax,
    Tkt Avg, Tkt Min, Tkt Max, TktEco Avg, TktBsn Avg, TktFst Avg

Notas de fidelidade ao M:
- TARIFA e convertida a inteiro (Int64.Type no M). DOM vem com virgula
  decimal ('446,28'); INT com ponto ('620.0'). Ambos viram int.
- INT: sg_icao_retorno == '9999' => so ida (tarifa cheia); senao /2.
- INT classes: cd_classe_ida F=First, J=Business, Y=Economy.
- Tkt Avg (macro) = TktEco Avg no INT; Revenue/Pax no DOM.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import pandas as pd

from . import dolar as _dolar

COLUNAS_SAIDA = [
    "Key", "ANO", "MES", "EMPRESA", "ORIGEM", "DESTINO", "Pax",
    "Tkt Avg", "Tkt Min", "Tkt Max",
    "TktEco Avg", "TktBsn Avg", "TktFst Avg",
]


# ─────────────────────────────────────────────────────────── utilidades

def _periodo_do_nome(nome: str) -> tuple[int, int] | tuple[None, None]:
    """Deduz (ano, mes) do nome do arquivo.

    DOM: '202601.CSV' (AAAAMM puro).
    INT: 'INTERNACIONAL_2025-12.CSV'.
    """
    base = os.path.basename(nome).upper()
    m = re.search(r"(\d{4})-(\d{2})", base)          # INT: 2025-12
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d{4})(\d{2})", base)            # DOM: 202601
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def eh_tarifa(nome: str) -> bool:
    """Diz se o arquivo e uma tarifa (DOM ou INT), tolerante a sufixos.

    A ANAC as vezes entrega o arquivo com um sufixo de duplicata, tipo
    '202605 (1).CSV', '202605(1).CSV' ou '202605 (01).CSV'. Em vez de
    exigir o nome exato (fullmatch), reconhecemos pela ESTRUTURA:
      - INT: comeca com INTERNACIONAL
      - DOM: comeca com 6 digitos (AAAAMM), com qualquer coisa depois
    Assim qualquer variacao de sufixo e coberta agora e no futuro.
    """
    base = os.path.basename(nome).upper()
    if not base.endswith(".CSV"):
        return False
    if base.startswith("INTERNACIONAL"):
        return True
    # DOM: 6 digitos no inicio (ignora o que vier depois: espaco, (1) etc.)
    return re.match(r"\d{6}", base) is not None


def classificar_tarifa(nome: str) -> str | None:
    """Devolve 'int', 'dom' ou None (se nao for tarifa)."""
    if not eh_tarifa(nome):
        return None
    base = os.path.basename(nome).upper()
    return "int" if base.startswith("INTERNACIONAL") else "dom"


def _tarifa_int(serie: pd.Series, decimal: str) -> pd.Series:
    """Converte a coluna de tarifa (texto) para inteiro, como o Int64 do M.

    decimal=',' para DOM (BRL), '.' para INT (USD).
    """
    limpa = serie.astype(str).str.strip()
    if decimal == ",":
        limpa = limpa.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    num = pd.to_numeric(limpa, errors="coerce")
    return num.round().astype("Int64")


def _key(ano, mes, empresa, origem, destino) -> str:
    return f"{ano} - {mes} - {empresa} - {origem} - {destino}"


# ──────────────────────────────────────────────────────────────── DOM

def processar_dom(caminho: str | Path) -> pd.DataFrame:
    """Tarifa domestica: BRL direto, sem classe, sem cambio."""
    df = pd.read_csv(caminho, sep=";", encoding="cp1252", dtype=str)
    df.columns = df.columns.str.strip()

    ren = {
        "nr_ano_referencia": "ANO", "nr_mes_referencia": "MES2",
        "sg_empresa_icao": "EMPRESA", "sg_icao_origem": "ORIGEM",
        "sg_icao_destino": "DESTINO",
    }
    df = df.rename(columns=ren)
    df["TARIFA"] = _tarifa_int(df["nr_tarifa"], decimal=",")
    df["ASSENTOS"] = pd.to_numeric(df["nr_assentos"], errors="coerce").astype("Int64")
    df["REVENUE"] = df["TARIFA"] * df["ASSENTOS"]

    g = df.groupby(["ANO", "MES2", "EMPRESA", "ORIGEM", "DESTINO"], as_index=False).agg(
        Pax=("ASSENTOS", "sum"),
        Revenue=("REVENUE", "sum"),
        **{"Tkt Min": ("TARIFA", "min"), "Tkt Max": ("TARIFA", "max")},
    )
    g["MES"] = g["MES2"].apply(lambda v: f"{int(v):02d}")
    g["Key"] = g.apply(lambda r: _key(r["ANO"], r["MES"], r["EMPRESA"],
                                      r["ORIGEM"], r["DESTINO"]), axis=1)
    g["Tkt Avg"] = (g["Revenue"] / g["Pax"]).round(2)
    # DOM nao tem classe
    g["TktEco Avg"] = pd.NA
    g["TktBsn Avg"] = pd.NA
    g["TktFst Avg"] = pd.NA
    return g[COLUNAS_SAIDA]


# ──────────────────────────────────────────────────────────────── INT

def processar_int(caminho: str | Path, tabela_dolar: dict[str, float]) -> pd.DataFrame:
    """Tarifa internacional: USD->BRL via dolar, RETORNO=9999 e classes."""
    df = pd.read_csv(caminho, sep=";", encoding="cp1252", dtype=str)
    df.columns = df.columns.str.strip()

    ren = {
        "nr_ano_referencia": "ANO", "nr_mes_referencia": "MES2",
        "sg_empresa_icao": "EMPRESA", "sg_icao_origem": "ORIGEM",
        "sg_icao_destino": "DESTINO", "sg_icao_retorno": "RETORNO",
        "cd_classe_ida": "CLASSE",
    }
    df = df.rename(columns=ren)
    df["TARIFA"] = _tarifa_int(df["nr_tarifa"], decimal=".")
    df["ASSENTOS"] = pd.to_numeric(df["nr_assentos"], errors="coerce").astype("Int64")
    df["MES"] = df["MES2"].apply(lambda v: f"{int(v):02d}")

    # Cambio do mes (KeyDolar = "ANO - MM")
    df["KeyDolar"] = df["ANO"].astype(str) + " - " + df["MES"]
    df["Dolar"] = df["KeyDolar"].map(tabela_dolar)

    faltando = df["Dolar"].isna().sum()
    if faltando:
        chaves = sorted(df.loc[df["Dolar"].isna(), "KeyDolar"].unique())
        raise ValueError(f"cambio ausente para {chaves} ({faltando} linhas)")

    # Trf em BRL: 9999 = so ida (cheia); senao ida e volta -> /2
    tarifa_brl = df["TARIFA"].astype(float) * df["Dolar"]
    df["Trf"] = tarifa_brl.where(df["RETORNO"] == "9999", tarifa_brl / 2)

    # Assentos por classe
    df["PaxFst"] = df["ASSENTOS"].where(df["CLASSE"] == "F")
    df["PaxBsn"] = df["ASSENTOS"].where(df["CLASSE"] == "J")
    df["PaxEco"] = df["ASSENTOS"].where(df["CLASSE"] == "Y")
    df["RevFst"] = (df["Trf"] * df["PaxFst"]).where(df["CLASSE"] == "F")
    df["RevBsn"] = (df["Trf"] * df["PaxBsn"]).where(df["CLASSE"] == "J")
    df["RevEco"] = (df["Trf"] * df["PaxEco"]).where(df["CLASSE"] == "Y")

    g = df.groupby(["ANO", "MES", "EMPRESA", "ORIGEM", "DESTINO"], as_index=False).agg(
        Pax=("ASSENTOS", "sum"),
        PaxFst=("PaxFst", "sum"), RevFst=("RevFst", "sum"),
        PaxBsn=("PaxBsn", "sum"), RevBsn=("RevBsn", "sum"),
        PaxEco=("PaxEco", "sum"), RevEco=("RevEco", "sum"),
        **{"Tkt Min": ("Trf", "min"), "Tkt Max": ("Trf", "max")},
    )
    g["Key"] = g.apply(lambda r: _key(r["ANO"], r["MES"], r["EMPRESA"],
                                      r["ORIGEM"], r["DESTINO"]), axis=1)

    def _avg(rev, pax):
        return (g[rev] / g[pax]).round(2).where(g[pax] > 0)

    g["TktFst Avg"] = _avg("RevFst", "PaxFst")
    g["TktBsn Avg"] = _avg("RevBsn", "PaxBsn")
    g["TktEco Avg"] = _avg("RevEco", "PaxEco")
    g["Tkt Min"] = g["Tkt Min"].round(2)
    g["Tkt Max"] = g["Tkt Max"].round(2)
    g["Tkt Avg"] = g["TktEco Avg"]   # macro = economica (decisao do M)
    return g[COLUNAS_SAIDA]


# ───────────────────────────────────────────────────────── orquestrador

def _classificar(caminho: str | Path) -> str:
    """DOM ou INT pelo nome do arquivo (INT tem 'INTERNACIONAL')."""
    return "int" if "INTERNACIONAL" in os.path.basename(caminho).upper() else "dom"


def processar(caminho: str | Path, pasta_saida: str | Path,
              pasta_bases: str | Path | None = None,
              tipo: str | None = None) -> str | None:
    """Processa um arquivo de tarifa e grava ticket_{dom,int}_YYYY-MM.csv.

    tipo: 'dom'/'int' ou None (deduz do nome). Para INT, le o cache de
    dolar de pasta_bases. Devolve o caminho do CSV, ou None em erro.
    """
    caminho = str(caminho)
    tipo = tipo or _classificar(caminho)
    ano, mes = _periodo_do_nome(caminho)
    if ano is None:
        print(f"  [ticket] nao consegui deduzir periodo de {caminho}")
        return None
    periodo = f"{ano}-{mes:02d}"

    print(f"\n  Processando Ticket {tipo.upper()}: {periodo}")
    print(f"    arquivo: {os.path.basename(caminho)}")

    if tipo == "dom":
        g = processar_dom(caminho)
    else:
        if not pasta_bases:
            print("    [ERRO] INT precisa de pasta_bases (cache do dolar)")
            return None
        tabela = _dolar.carregar(pasta_bases)
        if not tabela:
            print("    [ERRO] cache de dolar vazio; rode 'dolar --atualizar'")
            return None
        try:
            g = processar_int(caminho, tabela)
        except ValueError as e:
            print(f"    [ERRO] {e}")
            return None

    os.makedirs(pasta_saida, exist_ok=True)
    nome = f"ticket_{tipo}_{periodo}.csv"
    saida = os.path.join(pasta_saida, nome)
    g.to_csv(saida, index=False, sep=";", encoding="utf-8-sig")
    print(f"    gravado: {nome}  ({len(g)} rotas)")
    return saida


def _cli() -> int:
    p = argparse.ArgumentParser(description="Processa tarifa DOM/INT")
    p.add_argument("arquivo", help="CSV de tarifa (DOM ou INT)")
    p.add_argument("--saida", required=True, help="pasta de saida")
    p.add_argument("--bases", help="pasta do dolar.csv (obrigatorio p/ INT)")
    p.add_argument("--tipo", choices=["dom", "int"], help="forca o tipo")
    args = p.parse_args()
    r = processar(args.arquivo, args.saida, args.bases, args.tipo)
    return 0 if r else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
