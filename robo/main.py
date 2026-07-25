"""Ponto de entrada do robo de coleta ANAC.

Fluxo: cada fonte baixa o .zip da ANAC; o robo extrai o(s) .csv/.txt de
dentro e envia para a pasta correta do Google Drive via rclone. O .zip e
descartado -- so o arquivo extraido interessa. Nao ha publicacao em
Release: o Drive e o destino final.

O manifest.json (estado que o robo le para saber o que ja pegou) e o
ESTADO.md (retrato legivel) ficam no proprio repositorio.

Se qualquer fonte ou envio falhar, o robo registra, segue com as demais,
e termina com codigo 1 -- o que dispara a notificacao automatica de
falha do GitHub Actions.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from . import comum, datasas, estado, microdados, siros


def _extrair_e_enviar(caminho_zip: Path, chave: str, sem_drive: bool) -> list[str]:
    """Extrai os .csv/.txt do zip e envia cada um ao Drive.

    Devolve a lista de motivos de falha (vazia se tudo correu bem).
    O zip permanece em _tmp/ ate o fim da execucao; nao e publicado.
    """
    falhas: list[str] = []

    try:
        conteudo = caminho_zip.read_bytes()
        extraidos = comum.extrair(conteudo, comum.tmp() / "extraidos")
    except Exception as e:  # noqa: BLE001
        print(f"  [ERRO] extracao de {caminho_zip.name}: {e}", file=sys.stderr)
        return [f"extrair:{caminho_zip.name}"]

    if sem_drive:
        print(f"  [--sem-drive] {len(extraidos)} arquivo(s) extraido(s), nao enviados")
        return []

    for arquivo in extraidos:
        if not comum.enviar_gdrive(arquivo, chave):
            falhas.append(f"drive:{arquivo.name}")

    return falhas


def main() -> int:
    p = argparse.ArgumentParser(description="Coleta de bases abertas da ANAC")
    p.add_argument("--fonte", choices=["siros", "microdados", "datasas", "todas"],
                   default="todas")
    p.add_argument("--sem-drive", action="store_true",
                   help="extrai mas nao envia ao Drive (so testa a coleta)")
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
    pendentes: list[tuple[str, str, Path]] = []
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

    # Extrai e envia cada zip coletado ao Drive.
    if pendentes:
        print(f"\n== extraindo e enviando {len(pendentes)} arquivo(s) ao Drive ==")
        for _, chave, caminho in pendentes:
            print(f"\n[{chave}]")
            falhas.extend(_extrair_e_enviar(caminho, chave, args.sem_drive))
    else:
        print("\nNada novo para enviar.")

    comum.salvar_manifest(manifest)
    estado.escrever(manifest)

    if falhas:
        print(f"\nConcluido com falhas: {', '.join(falhas)}", file=sys.stderr)
        return 1
    print("\nConcluido sem falhas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
