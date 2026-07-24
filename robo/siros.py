"""SIROS — registro de voos futuros. Publicacao diaria.

Servidor proprio (IIS), fora do proxy do gov.br, e por isso o mais
generoso das tres fontes: a listagem de diretorio ja traz data, hora e
tamanho, e o HEAD funciona normalmente no arquivo.

Consequencia pratica: da para saber se o voos.zip mudou antes de gastar
os 12 MB do download.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import comum

DIRETORIO = "https://siros.anac.gov.br/siros/registros/voos/"
URL = f"{DIRETORIO}voos.zip"
TAG = "siros-latest"
CHAVE = "siros/voos"

# Listagem do IIS: "7/24/2026  5:19 AM     12206740 voos.zip"
RE_ITEM = re.compile(
    r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}\s*[AP]M)\s+(\d+)\s+([^\s<]+\.zip)",
    re.IGNORECASE,
)


def listar(s=None) -> dict[str, dict]:
    """Le a listagem de diretorio. Devolve {nome: {data, bytes}}."""
    s = s or comum.sessao()
    conteudo = comum.baixar(DIRETORIO, s)
    if conteudo is None:
        return {}
    texto = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ",
                                       conteudo.decode("utf-8", "replace")))
    return {
        nome: {"publicado_em": f"{data} {hora}", "bytes": int(tam)}
        for data, hora, tam, nome in RE_ITEM.findall(texto)
    }


def coletar(m: dict) -> list[tuple[str, str, Path]]:
    s = comum.sessao()
    entrada = m["arquivos"].get(CHAVE, {})

    itens = listar(s)
    anuncio = itens.get("voos.zip")

    if anuncio:
        print(f"[SIROS] site anuncia: {anuncio['publicado_em']} "
              f"({anuncio['bytes']/1_048_576:.1f} MB)")
        if (anuncio["publicado_em"] == entrada.get("publicado_em")
                and anuncio["bytes"] == entrada.get("bytes_zip")):
            print("  identico ao registrado; nao baixa")
            comum.registrar(m, CHAVE, situacao="inalterado")
            return []
    else:
        # Sem listagem legivel, cai para o HEAD do proprio arquivo.
        props = comum.propriedades(URL, s)
        if props:
            print(f"[SIROS] {props['bytes']} bytes, {props['modificado_em']}")
            if props["bytes"] == entrada.get("bytes_zip"):
                print("  tamanho identico ao registrado; nao baixa")
                comum.registrar(m, CHAVE, situacao="inalterado")
                return []
        anuncio = {"publicado_em": (props or {}).get("modificado_em"),
                   "bytes": (props or {}).get("bytes")}

    conteudo = comum.baixar(URL, s)
    if conteudo is None:
        comum.registrar(m, CHAVE, situacao="indisponivel")
        return []

    comum.validar_zip(conteudo)
    imp = comum.impressao(conteudo)
    situacao = "atualizado" if entrada.get("impressao") else "novo"

    if imp == entrada.get("impressao"):
        print("  conteudo identico apesar do anuncio; nao republica")
        comum.registrar(m, CHAVE, impressao=imp, situacao="inalterado",
                        publicado_em=anuncio.get("publicado_em"))
        return []

    print(f"  {situacao} ({len(conteudo)/1_048_576:.1f} MB)")
    comum.registrar(m, CHAVE, url=URL, impressao=imp,
                    sha256=comum.sha256(conteudo), bytes_zip=len(conteudo),
                    publicado_em=anuncio.get("publicado_em"), situacao=situacao)
    return [(TAG, CHAVE, comum.salvar(conteudo, "voos.zip"))]
