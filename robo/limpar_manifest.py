# -*- coding: utf-8 -*-
"""limpar_manifest.py — remove chaves do manifest para forcar recoleta.

Usado pelo limpar_manifest.bat. Remover uma chave faz o robo achar que
nunca coletou aquele item, entao ele rebaixa e reprocessa no proximo run.

Uso:
    python -m robo.limpar_manifest --preset mes-atual
    python -m robo.limpar_manifest --preset siros
    python -m robo.limpar_manifest --preset tudo-2026
    python -m robo.limpar_manifest --chave basica/202606 --chave siros/voos
    python -m robo.limpar_manifest --listar

Os presets cobrem os casos comuns; --chave remove chaves especificas.
Sempre mostra o que removeu e salva o manifest de volta.
"""

from __future__ import annotations

import argparse
from datetime import date

from . import comum


def _ultimo_mes_coletado() -> str | None:
    """Descobre o ultimo AAAAMM de basica no manifest (o mes de dados mais
    recente que o robo coletou). Mais util que a data do sistema, porque
    os dados da ANAC tem defasagem (em agosto, o ultimo mes pode ser junho).
    """
    m = comum.carregar_manifest()
    refs = sorted(k.split("/", 1)[1] for k in m.get("arquivos", {})
                  if k.startswith("basica/"))
    return refs[-1] if refs else None


def _mes_atual_refs() -> list[str]:
    """Chaves do ultimo mes coletado (basica/combinada) + siros + dom do ano."""
    ref = _ultimo_mes_coletado()
    ano = ref[:4] if ref else str(date.today().year)
    chaves = ["siros/voos", f"tarifas/dom/{ano}"]
    if ref:
        chaves = [f"basica/{ref}", f"combinada/{ref}"] + chaves
    return chaves


def _presets() -> dict[str, list[str]]:
    hoje = date.today()
    return {
        # Mes corrente completo: movimentacao do mes + siros + tarifa do ano.
        "mes-atual": _mes_atual_refs(),
        # So o siros (voo futuro; reprocessa o voos.csv).
        "siros": ["siros/voos"],
        # Tudo de 2026 que o robo cuida (movimentacao + siros + dom).
        "tudo-2026": (
            [f"basica/2026{mm:02d}" for mm in range(1, 13)]
            + [f"combinada/2026{mm:02d}" for mm in range(1, 13)]
            + ["siros/voos", "tarifas/dom/2026", "tarifas/int/2026"]
        ),
    }


def limpar(chaves: list[str]) -> int:
    """Remove as chaves informadas do manifest. Devolve quantas removeu."""
    m = comum.carregar_manifest()
    arq = m.get("arquivos", {})
    removidas = 0
    for k in chaves:
        if k in arq:
            del arq[k]
            print(f"  removido: {k}")
            removidas += 1
        else:
            print(f"  (nao estava): {k}")
    if removidas:
        comum.salvar_manifest(m)
        print(f"\n{removidas} chave(s) removida(s). O proximo run vai "
              f"rebaixar/reprocessar esses itens.")
    else:
        print("\nNada removido (nenhuma chave estava presente).")
    return removidas


def _listar():
    m = comum.carregar_manifest()
    arq = m.get("arquivos", {})
    print(f"Manifest tem {len(arq)} chave(s):")
    for k in sorted(arq):
        sit = arq[k].get("situacao", "?")
        print(f"  {k:28} [{sit}]")


def _cli() -> int:
    p = argparse.ArgumentParser(description="Remove chaves do manifest ANAC")
    presets = _presets()
    p.add_argument("--preset", choices=list(presets),
                   help="conjunto pronto de chaves a remover")
    p.add_argument("--chave", action="append", default=[],
                   help="chave especifica (pode repetir)")
    p.add_argument("--listar", action="store_true",
                   help="so mostra as chaves do manifest e sai")
    args = p.parse_args()

    if args.listar:
        _listar()
        return 0

    chaves = list(args.chave)
    if args.preset:
        chaves += presets[args.preset]
    if not chaves:
        print("Nada a fazer. Use --preset, --chave ou --listar.")
        return 1

    return 0 if limpar(chaves) >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
