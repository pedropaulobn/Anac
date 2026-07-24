"""Publicacao de arquivos como assets de GitHub Releases.

Usa o `gh` CLI, que ja vem instalado nos runners do GitHub Actions e
autentica sozinho via GH_TOKEN. Evita escrever cliente da API REST.

Em execucao local sem GH_TOKEN, o modo `--local` do main.py pula esta
etapa e apenas deixa os arquivos em _tmp/, para inspecao manual.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class SemToken(RuntimeError):
    pass


def _gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=check,
        env={**os.environ},
    )


def disponivel() -> bool:
    if not os.environ.get("GH_TOKEN") and not os.environ.get("GITHUB_TOKEN"):
        return False
    try:
        _gh("--version")
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def garantir_release(tag: str, titulo: str, notas: str = "") -> None:
    existe = _gh("release", "view", tag, check=False).returncode == 0
    if existe:
        return
    print(f"  criando release '{tag}'")
    _gh(
        "release",
        "create",
        tag,
        "--title",
        titulo,
        "--notes",
        notas or f"Coleta automatizada — {titulo}",
    )


def enviar(tag: str, titulo: str, arquivos: list[Path]) -> None:
    """Sobe (ou substitui) assets na release indicada."""
    if not arquivos:
        return
    if not disponivel():
        raise SemToken(
            "gh CLI indisponivel ou GH_TOKEN ausente; use --local para testar"
        )

    garantir_release(tag, titulo)
    for a in arquivos:
        mb = a.stat().st_size / 1_048_576
        if mb > 2048:
            raise RuntimeError(
                f"{a.name} tem {mb:.0f} MB e excede o limite de 2 GB por asset"
            )
        print(f"  enviando {a.name} ({mb:.1f} MB) -> release '{tag}'")
        _gh("release", "upload", tag, str(a), "--clobber")
