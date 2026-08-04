# -*- coding: utf-8 -*-
"""move_arquivos.py — ponte OneDrive Pessoal -> Corporativo (local).

Roda no .bat local. O robo (GitHub) escreve no Drive; o rclone sincroniza
Drive -> OneDrive Pessoal; este modulo move os arquivos do Pessoal para o
Corporativo (destino permanente), espelhando a estrutura de pastas.

Tambem sincroniza as Bases: o Corporativo e a verdade; se o Pessoal
divergir, atualiza o Pessoal (que depois sobe pro Drive via rclone).

Lida com OneDrive cloud-only: um arquivo pode existir so na nuvem; o
primeiro acesso dispara o download. Este modulo espera o arquivo
"materializar" (tamanho estavel) antes de mover.
"""

from __future__ import annotations

import argparse
import os
import shutil
import time
from pathlib import Path

# Estrutura relativa espelhada nos dois lados
SUBPASTAS = [
    r"Anac\Movimentacao\Raw",
    r"Anac\Movimentacao\Processado",
    r"Anac\Ticket\Raw",
    r"Anac\Ticket\Processado",
    r"Anac\Siros\Raw",
    r"Anac\Siros\Processado",
]

ESPERA_DOWNLOAD = 300   # segundos maximos aguardando materializar
INTERVALO = 3           # segundos entre checagens de tamanho


def _materializado(caminho: Path, timeout: int = ESPERA_DOWNLOAD) -> bool:
    """Espera o arquivo cloud-only baixar (tamanho > 0 e estavel).

    OneDrive baixa sob demanda; enquanto baixa, o tamanho cresce. Consid.
    materializado quando o tamanho para de mudar entre duas checagens.
    """
    limite = time.time() + timeout
    ultimo = -1
    while time.time() < limite:
        try:
            tam = caminho.stat().st_size
        except OSError:
            tam = -1
        if tam > 0 and tam == ultimo:
            return True
        if tam != ultimo:
            if ultimo == -1:
                print(f"      aguardando download do OneDrive: {caminho.name}")
        ultimo = tam
        time.sleep(INTERVALO)
    return caminho.exists() and caminho.stat().st_size > 0


def mover(origem_raiz: str | Path, destino_raiz: str | Path,
          apagar_origem: bool = True) -> tuple[int, list[str]]:
    """Move arquivos do Pessoal para o Corporativo, por subpasta.

    Devolve (quantidade_movida, falhas).
    """
    origem_raiz = Path(origem_raiz)
    destino_raiz = Path(destino_raiz)
    movidos = 0
    falhas: list[str] = []

    for sub in SUBPASTAS:
        o = origem_raiz / sub
        dst = destino_raiz / sub
        if not o.exists():
            continue
        dst.mkdir(parents=True, exist_ok=True)
        for arq in o.iterdir():
            if not arq.is_file():
                continue
            if not _materializado(arq):
                print(f"      [falha] nao materializou: {arq.name}")
                falhas.append(str(arq))
                continue
            alvo = dst / arq.name
            try:
                shutil.copy2(arq, alvo)
                if apagar_origem:
                    arq.unlink()
                movidos += 1
                print(f"    movido: {sub}\\{arq.name}")
            except Exception as e:  # noqa: BLE001
                print(f"    [falha] {arq.name}: {e}")
                falhas.append(str(arq))

    return movidos, falhas


def sincronizar_bases(corp_bases: str | Path, pessoal_bases: str | Path,
                      drive_via_rclone: bool = False) -> int:
    """Garante Pessoal = Corp para as bases. Corp e a verdade.

    Copia do Corp para o Pessoal os arquivos que diferem (por tamanho ou
    data de modificacao). Devolve quantos foram atualizados.
    """
    corp = Path(corp_bases)
    pes = Path(pessoal_bases)
    if not corp.exists():
        print(f"  [bases] corp nao existe: {corp}")
        return 0
    pes.mkdir(parents=True, exist_ok=True)

    atualizados = 0
    for arq in corp.iterdir():
        if not arq.is_file():
            continue
        alvo = pes / arq.name
        precisa = (not alvo.exists()
                   or arq.stat().st_size != alvo.stat().st_size
                   or arq.stat().st_mtime > alvo.stat().st_mtime)
        if precisa:
            shutil.copy2(arq, alvo)
            atualizados += 1
            print(f"    base atualizada: {arq.name}")
    if not atualizados:
        print("  [bases] pessoal ja igual ao corp")
    return atualizados


def _cli() -> int:
    p = argparse.ArgumentParser(description="Move Pessoal -> Corp e sincroniza bases")
    p.add_argument("--pessoal", required=True, help="raiz Anac do OneDrive Pessoal")
    p.add_argument("--corp", required=True, help="raiz Anac do OneDrive Corp")
    p.add_argument("--bases-corp", help="pasta Bases do Corp")
    p.add_argument("--bases-pessoal", help="pasta Bases do Pessoal")
    p.add_argument("--manter-origem", action="store_true",
                   help="nao apaga os arquivos do Pessoal apos copiar")
    args = p.parse_args()

    print("== movendo Pessoal -> Corp ==")
    n, falhas = mover(args.pessoal, args.corp, apagar_origem=not args.manter_origem)
    print(f"  {n} arquivo(s) movido(s)")

    if args.bases_corp and args.bases_pessoal:
        print("== sincronizando bases (corp -> pessoal) ==")
        sincronizar_bases(args.bases_corp, args.bases_pessoal)

    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(_cli())
