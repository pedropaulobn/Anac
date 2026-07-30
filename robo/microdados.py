"""Microdados ANAC — basica e combinada (ambas alimentam Movimentacao).

A pagina de microdados NAO e so um aviso de atualizacao: ela publica o
inventario completo, um link por mes, de 2000-01 ate o mes mais recente
(318 meses por segmento em 07/2026). O robo le essa lista e nunca monta
URL por deducao.

Isso nao e preciosismo. A ANAC usa DUAS convencoes de nome ao mesmo
tempo: 317 arquivos como `basica2026-05.zip` (com hifen) e exatamente um,
o mais recente, como `basica202606.zip`. Qualquer padrao deduzido acerta
um e erra os outros 317. Lendo os links, a convencao deixa de importar --
e se a ANAC renomear o arquivo depois, o mes continua o mesmo e nada e
republicado, porque a comparacao e por conteudo.

Ritmo de trabalho:

PORTEIRO   "Atualizado em" da pagina. Se nao mudou, nao varre nada.
AVANCO     Meses do inventario ainda nao coletados, do mais antigo para
           o mais novo. Sem sondagem de existencia: o inventario ja diz.
VARREDURA  Confere o tamanho dos meses ja coletados (GET com Range, um
           byte cada). So roda quando o porteiro acusa mudanca.

Este servidor nao emite Last-Modified para os arquivos, entao o unico
indicador de republicacao por arquivo e o tamanho em bytes.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin

from . import comum

BASE = (
    "https://www.gov.br/anac/pt-br/assuntos/regulados/empresas-aereas/"
    "Instrucoes-para-a-elaboracao-e-apresentacao-das-demonstracoes-contabeis/"
    "envio-de-informacoes"
)
PAGINA = f"{BASE}/microdados"

SEGMENTOS = ("basica", "combinada")
BOOTSTRAP_MESES = 12   # quantos meses pegar na primeira execucao
COLETADO = {"novo", "atualizado", "republicado", "inalterado"}

RE_PAGINA = re.compile(
    r"(Publicado|Atualizado)\s+em\s*[:\-]?\s*"
    r"(\d{1,2}/\d{1,2}/\d{4})"
    r"(?:\s*(?:as|às)?\s*(\d{1,2}[h:]\d{2}))?",
    re.IGNORECASE,
)
RE_HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
# Aceita as duas convencoes: basica2026-05.zip e basica202606.zip
RE_ARQUIVO = re.compile(r"(basica|combinada)(\d{4})-?(\d{2})\.zip$", re.IGNORECASE)


# ------------------------------------------------------------- inventario

def ler_pagina(s=None) -> tuple[dict, dict[str, dict[str, str]]]:
    """Devolve (datas_da_pagina, {segmento: {ref: url}}).

    Uma unica requisicao serve ao porteiro e ao inventario.
    """
    s = s or comum.sessao()
    conteudo = comum.baixar(PAGINA, s)
    if conteudo is None:
        return {}, {}

    html = conteudo.decode("utf-8", "replace")
    texto = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    datas = {rot.lower(): f"{d} {h}".strip() for rot, d, h in RE_PAGINA.findall(texto)}

    inventario: dict[str, dict[str, str]] = {seg: {} for seg in SEGMENTOS}
    for href in RE_HREF.findall(html):
        url = urljoin(PAGINA + "/", href.split("?")[0])
        m = RE_ARQUIVO.search(url)
        if not m:
            continue
        segmento, ano, mes = m.group(1).lower(), m.group(2), m.group(3)
        if segmento in inventario:
            inventario[segmento][f"{ano}{mes}"] = url

    return datas, inventario


def refs_coletadas(m: dict, segmento: str) -> list[str]:
    return sorted(
        k.split("/", 1)[1]
        for k, v in m.get("arquivos", {}).items()
        if k.startswith(f"{segmento}/") and v.get("situacao") in COLETADO
    )


# ---------------------------------------------------------------- coleta

def _guardar(m: dict, segmento: str, ref: str, url: str, s, motivo: str):
    chave = f"{segmento}/{ref}"

    conteudo = comum.baixar(url, s)
    if conteudo is None:
        print(f"  [{ref}] link do inventario nao respondeu")
        comum.registrar(m, chave, url=url, situacao="indisponivel")
        return None

    comum.validar_zip(conteudo)
    imp = comum.impressao(conteudo)
    anterior = m["arquivos"].get(chave, {}).get("impressao")

    if imp == anterior:
        comum.registrar(m, chave, url=url, impressao=imp,
                        bytes_zip=len(conteudo), situacao="inalterado")
        return None

    situacao = "republicado" if anterior else "novo"
    if anterior:
        print(f"  [{ref}] ATENCAO: a ANAC alterou este mes desde a coleta anterior")
    print(f"  [{ref}] {situacao} ({len(conteudo)/1_048_576:.1f} MB) [{motivo}]")

    comum.registrar(m, chave, url=url, impressao=imp, sha256=comum.sha256(conteudo),
                    bytes_zip=len(conteudo), situacao=situacao)
    nome = f"{segmento}{ref}.zip"
    return (f"microdados-{ref[:4]}", chave, comum.salvar(conteudo, nome))


def _avancar(m, segmento, disponiveis: dict[str, str], s, backfill: bool):
    conhecidas = set(refs_coletadas(m, segmento))
    faltando = sorted(set(disponiveis) - conhecidas)

    if not faltando:
        print(f"  em dia: {len(conhecidas)} de {len(disponiveis)} meses do inventario")
        return []

    if backfill:
        alvos = faltando
        print(f"  backfill: {len(alvos)} mes(es) faltando, de {alvos[0]} a {alvos[-1]}")
    elif not conhecidas:
        alvos = faltando[-BOOTSTRAP_MESES:]
        print(f"  primeira execucao; pegando os {len(alvos)} meses mais recentes "
              f"({alvos[0]} a {alvos[-1]}) — use --backfill para os {len(faltando)} todos")
    else:
        alvos = [r for r in faltando if r > max(conhecidas)]
        antigos = len(faltando) - len(alvos)
        print(f"  ultimo coletado: {max(conhecidas)} | novos no site: "
              f"{alvos or 'nenhum'}" + (f" | {antigos} buraco(s) atras" if antigos else ""))

    saida = []
    for ref in alvos:
        r = _guardar(m, segmento, ref, disponiveis[ref], s, "coleta")
        if r:
            saida.append(r)
    return saida


def _varrer(m, segmento, disponiveis: dict[str, str], s):
    conhecidas = refs_coletadas(m, segmento)
    if not conhecidas:
        return []

    print(f"  varrendo {len(conhecidas)} mes(es) por tamanho")
    suspeitos = []
    for ref in conhecidas:
        url = disponiveis.get(ref)
        if not url:
            print(f"  [{ref}] sumiu do inventario da pagina")
            continue
        entrada = m["arquivos"][f"{segmento}/{ref}"]
        props = comum.propriedades(url, s)
        if not props or props["bytes"] is None:
            continue
        antes = entrada.get("bytes_zip")
        if antes and props["bytes"] != antes:
            print(f"  [{ref}] tamanho mudou: {antes} -> {props['bytes']} bytes")
            suspeitos.append(ref)

    if not suspeitos:
        print("  nenhuma divergencia de tamanho no historico")
        return []

    saida = []
    for ref in suspeitos:
        r = _guardar(m, segmento, ref, disponiveis[ref], s, "varredura")
        if r:
            saida.append(r)
    return saida


def coletar(m: dict, forcar_varredura: bool = False,
            backfill: bool = False) -> list[tuple[str, str, Path]]:
    s = comum.sessao()
    publicar: list[tuple[str, str, Path]] = []

    datas, inventario = ler_pagina(s)
    atual = datas.get("atualizado")
    anterior = m.get("pagina_microdados", {}).get("atualizado")
    mudou = bool(atual) and atual != anterior

    print(f"\n[MICRODADOS] pagina atualizada em: {atual or 'nao lido'} "
          f"(registro anterior: {anterior or 'nenhum'})")
    for seg in SEGMENTOS:
        d = inventario.get(seg, {})
        print(f"  inventario {seg}: {len(d)} mes(es)"
              + (f", de {min(d)} a {max(d)}" if d else " — NADA ENCONTRADO"))

    m["pagina_microdados"] = {
        "publicado": datas.get("publicado"),
        "atualizado": atual,
        "verificado_em": comum.agora(),
        "inventario": {
            seg: {"total": len(d), "ultimo": max(d) if d else None}
            for seg, d in inventario.items()
        },
    }

    if not any(inventario.values()):
        print("  ERRO: nenhum link de download na pagina; nada a fazer")
        return []

    varrer = mudou or forcar_varredura
    print("  " + ("a pagina mudou -> varredura habilitada" if mudou
                  else "varredura forcada" if forcar_varredura
                  else "pagina inalterada -> sem varredura"))

    for segmento in SEGMENTOS:
        print(f"\n[{segmento.upper()}]")
        disponiveis = inventario.get(segmento, {})
        if not disponiveis:
            continue
        # Piso central: no fluxo automatico o robo so cuida de >= ANO_MINIMO.
        # O historico fica para o --backfill (rodado de proposito) ou para o
        # .bat local. Assim uma primeira execucao nao tenta 318 meses.
        if not backfill:
            antes = len(disponiveis)
            disponiveis = {ref: url for ref, url in disponiveis.items()
                           if int(ref[:4]) >= comum.ANO_MINIMO}
            corte = antes - len(disponiveis)
            if corte:
                print(f"  (piso {comum.ANO_MINIMO}: {corte} mes(es) antigo(s) "
                      f"ignorado(s) no automatico; use --backfill para o historico)")
            if not disponiveis:
                print(f"  nada >= {comum.ANO_MINIMO} no inventario")
                continue
        publicar += _avancar(m, segmento, disponiveis, s, backfill)
        if varrer:
            publicar += _varrer(m, segmento, disponiveis, s)

    return publicar
