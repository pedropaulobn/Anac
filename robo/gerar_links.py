# -*- coding: utf-8 -*-
"""gerar_links.py — inventario de links de download da pasta publica.

Roda no GitHub, depois de enviar os arquivos ao Drive. Lista tudo dentro
de Sync/Fraport/Anac (rclone lsjson traz o ID do Google Drive de cada
arquivo) e gera um links.csv com:

    caminho_relativo;nome;id;url_download

O url_download usa o endpoint que NAO passa pela pagina de confirmacao de
virus (funciona para arquivos grandes, ex: Siros de 600+ MB):
    https://drive.usercontent.google.com/download?id=ID&export=download&confirm=t

Esse links.csv e enviado para a raiz de Sync/Fraport/Anac no Drive. O PC
corporativo baixa so esse CSV (link publico fixo), le a lista e baixa cada
arquivo via curl -- sem nunca logar no Google Drive.

So faz sentido se a pasta Anac do Drive for publica ("qualquer um com o
link"). O ID e estavel; o link publico de cada arquivo deriva dele.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path

from . import comum

# Pasta raiz cujo conteudo sera inventariado (recursivo).
DRIVE_ANAC = f"{comum.DRIVE_RAIZ}/Anac"
NOME_LISTA = "links.csv"

URL_DOWNLOAD = ("https://drive.usercontent.google.com/download"
                "?id={id}&export=download&confirm=t")


def listar_arquivos_drive() -> list[dict]:
    """Roda rclone lsjson recursivo e devolve [{Path, Name, ID}, ...].

    lsjson traz 'ID' (o id do Google Drive) quando o remote e gdrive.
    Ignora diretorios (IsDir) e o proprio links.csv.
    """
    exe = comum.rclone_bin()
    cmd = [exe, "lsjson", "-R", "--files-only", DRIVE_ANAC]
    print(f"  listando (lsjson -R): {DRIVE_ANAC}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"rclone lsjson falhou ({r.returncode}): "
                           f"{r.stderr.strip()[:300]}")
    itens = json.loads(r.stdout or "[]")
    saida = []
    for it in itens:
        if it.get("IsDir"):
            continue
        if it.get("Name") == NOME_LISTA:
            continue
        gid = it.get("ID")
        if not gid:
            # Sem ID nao da para montar link publico; avisa e pula.
            print(f"  [aviso] sem ID: {it.get('Path')}")
            continue
        saida.append({"path": it.get("Path", ""), "name": it.get("Name", ""),
                      "id": gid})
    return saida


def gerar_csv(itens: list[dict], destino_local: Path) -> Path:
    """Grava o links.csv local. Colunas: caminho;nome;id;url."""
    destino_local.parent.mkdir(parents=True, exist_ok=True)
    with open(destino_local, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["caminho", "nome", "id", "url"])
        for it in sorted(itens, key=lambda x: x["path"]):
            url = URL_DOWNLOAD.format(id=it["id"])
            w.writerow([it["path"], it["name"], it["id"], url])
    print(f"  links.csv gerado: {len(itens)} arquivo(s)")
    return destino_local


def enviar_lista(caminho_local: Path) -> bool:
    """Envia o links.csv para a raiz de Sync/Fraport/Anac no Drive."""
    exe = comum.rclone_bin()
    destino = f"{DRIVE_ANAC}/"
    cmd = [exe, "copy", str(caminho_local), destino, "--verbose"]
    print(f"  enviando {NOME_LISTA} -> {destino}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode == 0:
        print(f"  ok: {NOME_LISTA} enviado")
        return True
    print(f"  ERRO ao enviar lista ({r.returncode}): {r.stderr.strip()[:200]}")
    return False


def gerar(enviar: bool = True) -> Path | None:
    """Fluxo completo: lista o Drive, gera o CSV, envia. Devolve o caminho."""
    try:
        itens = listar_arquivos_drive()
    except Exception as e:  # noqa: BLE001
        print(f"  [ERRO] nao consegui listar o Drive: {e}")
        return None
    if not itens:
        print("  [aviso] nenhum arquivo encontrado no Drive; lista nao gerada")
        return None
    local = comum.tmp() / NOME_LISTA
    gerar_csv(itens, local)
    if enviar and not enviar_lista(local):
        return None
    return local


def _cli() -> int:
    p = argparse.ArgumentParser(description="Gera links.csv da pasta publica do Drive")
    p.add_argument("--sem-enviar", action="store_true",
                   help="gera localmente mas nao envia ao Drive")
    args = p.parse_args()
    r = gerar(enviar=not args.sem_enviar)
    return 0 if r else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
