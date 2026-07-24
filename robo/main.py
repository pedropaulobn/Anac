"""Ponto de entrada do robo de coleta ANAC.

Etapa 1: baixa os .zip originais e publica como assets de GitHub Releases.
Nenhum tratamento e nenhuma extracao -- o arquivo fica como a ANAC entregou.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from . import comum, datasas, estado, microdados, publicar, siros

TITULOS = {
    "siros-latest": "SIROS - voos futuros (ultima coleta)",
}


def titulo_release(tag: str) -> str:
    if tag in TITULOS:
        return TITULOS[tag]
    if tag.startswith("microdados-"):
        return f"Microdados basica/combinada - {tag.split('-')[1]}"
    if tag.startswith("tarifas-"):
        return f"Tarifas DataSAS DOM/INT - {tag.split('-')[1]}"
    return tag


def main() -> int:
    p = argparse.ArgumentParser(description="Coleta de bases abertas da ANAC")
    p.add_argument("--fonte", choices=["siros", "microdados", "datasas", "todas"],
                   default="todas")
    p.add_argument("--local", action="store_true",
                   help="nao publica; deixa os zips em _tmp/ para inspecao")
    p.add_argument("--explorar", action="store_true",
                   help="so para datasas: imprime a estrutura da pagina e sai")
    p.add_argument("--completo", action="store_true",
                   help="forca varredura completa do historico")
    p.add_argument("--backfill", action="store_true",
                   help="baixa TODO o inventario de microdados (2000 em diante)")
    args = p.parse_args()

    if args.explorar:
        datasas.explorar()
        return 0

    manifest = comum.carregar_manifest()
    pendentes: list[tuple[str, str, object]] = []
    falhas: list[str] = []

    # Dia 28: varredura completa das tarifas, que nao tem porteiro proprio.
    # Os microdados tem porteiro (data da pagina) e dispensam calendario.
    completo = args.completo or date.today().day == 28
    if completo:
        print("== modo completo: varrendo todo o historico ==")

    tarefas = {
        "siros": lambda: siros.coletar(manifest),
        "microdados": lambda: microdados.coletar(manifest, forcar_varredura=args.completo,
                                                 backfill=args.backfill),
        "datasas": lambda: datasas.coletar(manifest, completo=completo),
    }
    alvos = tarefas if args.fonte == "todas" else {args.fonte: tarefas[args.fonte]}

    for nome, funcao in alvos.items():
        try:
            pendentes.extend(funcao())
        except Exception as e:  # noqa: BLE001
            print(f"[ERRO] fonte '{nome}': {e}", file=sys.stderr)
            falhas.append(nome)

    # Agrupa por release para nao chamar o gh uma vez por arquivo.
    if pendentes and not args.local:
        por_tag: dict[str, list] = {}
        for tag, _, caminho in pendentes:
            por_tag.setdefault(tag, []).append(caminho)
        for tag, arquivos in sorted(por_tag.items()):
            try:
                publicar.enviar(tag, titulo_release(tag), arquivos)
            except Exception as e:  # noqa: BLE001
                print(f"[ERRO] publicacao em '{tag}': {e}", file=sys.stderr)
                falhas.append(f"publicar:{tag}")
    elif pendentes:
        print(f"\n[--local] {len(pendentes)} arquivo(s) em _tmp/, sem publicar:")
        for _, chave, caminho in pendentes:
            print(f"  {chave} -> {caminho}")
    else:
        print("\nNada novo para publicar.")

    comum.salvar_manifest(manifest)
    estado.escrever(manifest)

    if falhas:
        print(f"\nConcluido com falhas: {', '.join(falhas)}", file=sys.stderr)
        return 1
    print("\nConcluido sem falhas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
