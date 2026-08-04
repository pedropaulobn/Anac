# -*- coding: utf-8 -*-
"""dolar.py — cache da taxa de cambio USD/BRL (para converter tarifa INT).

Estrategia: um CSV de cache (`dolar.csv`) e a fonte de verdade que o
processamento da Ticket INT le. A atualizacao vem da API OData do IPEA
(muito mais estavel que raspar o HTML). Se a API falha, o modulo usa o
que ja tem no cache; se falta o mes exato de que a Ticket precisa, avisa
e permite input manual -- sem travar o resto do pipeline.

Isolamento proposital: se a fonte IPEA mudar, so este arquivo muda.

Formato do cache (dolar.csv, sep=';', utf-8):
    KeyDolar;taxa
    2026 - 01;5.8432
    2026 - 02;5.9011

KeyDolar = "ANO - MM" (mes com zero a esquerda) -- bate com o KeyDolar
que o processa_ticket monta para a INT.

Uso standalone (local, para popular/atualizar o cache):
    python -m robo.dolar --atualizar --bases "C:\\...\\Bases"
    python -m robo.dolar --descobrir          # lista series de cambio
    python -m robo.dolar --manual 2026-01 5.84 --bases "C:\\...\\Bases"
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

import requests

# SERCODIGO da serie de cambio no IPEA (OData). O 'serid=32098' do site
# antigo e o id da pagina web, NAO o SERCODIGO da API. O padrao abaixo e
# a taxa comercial de compra, media mensal. Se estiver errado para o seu
# caso, rode --descobrir e ajuste aqui (um lugar so).
SERCODIGO = "BM12_ERC12"

API_VALORES = "http://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='{cod}')"
API_METADADOS = "http://www.ipeadata.gov.br/api/odata4/Metadados"

NOME_CACHE = "dolar.csv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
TIMEOUT = 60


# ─────────────────────────────────────────────────────── cache (leitura)

def caminho_cache(pasta_bases: str | Path) -> Path:
    return Path(pasta_bases) / NOME_CACHE


def carregar(pasta_bases: str | Path) -> dict[str, float]:
    """Le o dolar.csv e devolve {KeyDolar: taxa}. Vazio se nao existe."""
    caminho = caminho_cache(pasta_bases)
    if not caminho.exists():
        print(f"  [dolar] cache nao encontrado: {caminho}")
        return {}
    tabela: dict[str, float] = {}
    with open(caminho, encoding="utf-8", newline="") as f:
        leitor = csv.DictReader(f, delimiter=";")
        for linha in leitor:
            chave = (linha.get("KeyDolar") or "").strip()
            bruto = (linha.get("taxa") or "").strip().replace(",", ".")
            if not chave or not bruto:
                continue
            try:
                tabela[chave] = float(bruto)
            except ValueError:
                continue
    print(f"  [dolar] {len(tabela)} mes(es) no cache")
    return tabela


def gravar(pasta_bases: str | Path, tabela: dict[str, float]) -> Path:
    """Grava o dolar.csv ordenado por KeyDolar."""
    caminho = caminho_cache(pasta_bases)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f, delimiter=";")
        escritor.writerow(["KeyDolar", "taxa"])
        for chave in sorted(tabela):
            escritor.writerow([chave, f"{tabela[chave]:.6f}".rstrip("0").rstrip(".")])
    print(f"  [dolar] cache gravado: {caminho} ({len(tabela)} mes(es))")
    return caminho


# ──────────────────────────────────────────────────────── IPEA (OData)

def _key(ano: int, mes: int) -> str:
    return f"{ano} - {mes:02d}"


def buscar_ipea(sercodigo: str = SERCODIGO) -> dict[str, float]:
    """Baixa a serie inteira do IPEA via OData. Devolve {KeyDolar: taxa}.

    Levanta excecao se a API falhar -- quem chama decide o fallback.
    """
    url = API_VALORES.format(cod=sercodigo)
    r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    dados = r.json().get("value", [])

    tabela: dict[str, float] = {}
    for reg in dados:
        data = reg.get("VALDATA")  # ex: "2026-01-01T00:00:00-03:00"
        valor = reg.get("VALVALOR")
        if not data or valor is None:
            continue
        try:
            ano = int(data[0:4])
            mes = int(data[5:7])
        except (ValueError, IndexError):
            continue
        tabela[_key(ano, mes)] = float(valor)
    return tabela


def descobrir_series() -> list[tuple[str, str, str]]:
    """Lista series cujo nome menciona cambio/compra. Ajuda a achar o
    SERCODIGO certo. Devolve [(SERCODIGO, SERNOME, PERNOME), ...]."""
    params = {
        "$filter": "contains(SERNOME,'mbio') and contains(SERNOME,'compra')",
        "$select": "SERCODIGO,SERNOME,PERNOME",
    }
    r = requests.get(API_METADADOS, params=params,
                     headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    return [(s.get("SERCODIGO", ""), s.get("SERNOME", ""), s.get("PERNOME", ""))
            for s in r.json().get("value", [])]


# ──────────────────────────────────────────────────────────── atualizar

def atualizar(pasta_bases: str | Path, sercodigo: str = SERCODIGO) -> dict[str, float]:
    """Atualiza o cache com o que o IPEA tiver. Mantem o que ja existe se
    a API falhar. Devolve a tabela resultante (mesclada)."""
    cache = carregar(pasta_bases)
    try:
        novos = buscar_ipea(sercodigo)
        print(f"  [dolar] IPEA respondeu com {len(novos)} mes(es)")
        cache.update(novos)  # IPEA prevalece onde houver
        gravar(pasta_bases, cache)
    except Exception as e:  # noqa: BLE001
        print(f"  [dolar] falha ao consultar IPEA: {str(e)[:150]}")
        print(f"  [dolar] seguindo com o cache atual ({len(cache)} mes(es))")
    return cache


def taxa_de(pasta_bases: str | Path, ano: int, mes: int) -> float | None:
    """Conveniencia: taxa de um mes especifico, do cache. None se ausente."""
    return carregar(pasta_bases).get(_key(ano, mes))


# ───────────────────────────────────────────────────────────────── CLI

def _cli() -> int:
    p = argparse.ArgumentParser(description="Cache da taxa de cambio USD/BRL (IPEA)")
    p.add_argument("--bases", help="pasta onde fica o dolar.csv")
    p.add_argument("--atualizar", action="store_true",
                   help="busca do IPEA e atualiza o cache")
    p.add_argument("--descobrir", action="store_true",
                   help="lista series de cambio do IPEA (para achar o SERCODIGO)")
    p.add_argument("--sercodigo", default=SERCODIGO, help="SERCODIGO a usar")
    p.add_argument("--manual", nargs=2, metavar=("AAAA-MM", "TAXA"),
                   help="grava manualmente a taxa de um mes")
    args = p.parse_args()

    if args.descobrir:
        try:
            series = descobrir_series()
        except Exception as e:  # noqa: BLE001
            print(f"Falha ao consultar IPEA: {e}")
            return 1
        print(f"{len(series)} serie(s) de cambio (compra):")
        for cod, nome, per in series:
            print(f"  {cod:20} [{per}]  {nome}")
        return 0

    if not args.bases:
        print("--bases e obrigatorio (exceto com --descobrir)")
        return 1

    if args.manual:
        periodo, taxa = args.manual
        ano, mes = int(periodo[:4]), int(periodo[5:7])
        cache = carregar(args.bases)
        cache[_key(ano, mes)] = float(taxa.replace(",", "."))
        gravar(args.bases, cache)
        print(f"  [dolar] {_key(ano, mes)} = {taxa} gravado manualmente")
        return 0

    if args.atualizar:
        atualizar(args.bases, args.sercodigo)
        return 0

    # Sem acao: so mostra o estado do cache.
    cache = carregar(args.bases)
    if cache:
        ultimos = sorted(cache)[-3:]
        print("  ultimos:", ", ".join(f"{k}={cache[k]}" for k in ultimos))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
