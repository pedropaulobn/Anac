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
import re
import sys
from datetime import date
from pathlib import Path

from . import comum, datasas, estado, microdados, siros

# Modulos de processamento (opcionais no fluxo: se faltar base, o raw
# ainda sobe e o processamento e apenas pulado).
from . import processa_mes, processa_ticket, processa_siros, dolar, gerar_links


def _extrair_e_enviar(caminho_zip: Path, chave: str,
                      sem_drive: bool) -> tuple[list[str], list[Path]]:
    """Extrai os .csv/.txt do zip e envia cada um (RAW) ao Drive.

    Devolve (falhas, extraidos): a lista de motivos de falha (vazia se
    tudo correu bem) e a lista de Path dos arquivos extraidos -- esta
    ultima alimenta a etapa de processamento.
    O zip permanece em _tmp/ ate o fim da execucao; nao e publicado.
    """
    falhas: list[str] = []

    try:
        conteudo = caminho_zip.read_bytes()
        extraidos = comum.extrair(conteudo, comum.tmp() / "extraidos")
    except Exception as e:  # noqa: BLE001
        print(f"  [ERRO] extracao de {caminho_zip.name}: {e}", file=sys.stderr)
        return [f"extrair:{caminho_zip.name}"], []

    if sem_drive:
        print(f"  [--sem-drive] {len(extraidos)} arquivo(s) extraido(s), nao enviados")
        return [], extraidos

    for arquivo in extraidos:
        if not comum.enviar_gdrive(arquivo, chave):
            falhas.append(f"drive:{arquivo.name}")

    return falhas, extraidos


def _parear_movimentacao(extraidos: list[Path]) -> dict[tuple[int, int], dict]:
    """Agrupa arquivos extraidos de basica/combinada por (ano, mes).

    Devolve {(ano, mes): {'basica': Path, 'combinada': Path}}. So entram
    os que sao basica/combinada; outros arquivos sao ignorados aqui.
    """
    pares: dict[tuple[int, int], dict] = {}
    for caminho in extraidos:
        nome = caminho.name.lower()
        if nome.startswith("basica"):
            tipo = "basica"
        elif nome.startswith("combinada"):
            tipo = "combinada"
        else:
            continue
        m = re.search(r"(\d{4})-?(\d{2})", nome)
        if not m:
            continue
        chave = (int(m.group(1)), int(m.group(2)))
        pares.setdefault(chave, {})[tipo] = caminho
    return pares


def _processar_movimentacao(extraidos: list[Path], pasta_bases: Path | None,
                            sem_drive: bool) -> list[str]:
    """Processa os pares basica+combinada e envia o CSV ao Drive (Processado/).

    Opcao A: so processa um mes quando o PAR completo (basica E combinada)
    esta presente. Se so um lado veio, adia -- loga e segue. Na ANAC os
    dois saem juntos, entao isso e raro; o proximo run resolve.

    Falha de base ou de processamento NAO derruba o run: o raw ja subiu.
    """
    falhas: list[str] = []
    pares = _parear_movimentacao(extraidos)
    if not pares:
        return falhas

    aircraft = None
    if pasta_bases:
        cand = pasta_bases / processa_mes.AIRCRAFT_NOME
        aircraft = str(cand) if cand.exists() else None

    saida = comum.tmp() / "processado"
    saida.mkdir(parents=True, exist_ok=True)

    print(f"\n== processando Movimentação: {len(pares)} mes(es) ==")
    for (ano, mes), lados in sorted(pares.items()):
        periodo = f"{ano}-{mes:02d}"
        if "basica" not in lados or "combinada" not in lados:
            faltou = "combinada" if "basica" in lados else "basica"
            print(f"  [{periodo}] par incompleto (falta {faltou}); adiado")
            continue
        try:
            csv = processa_mes.processar_par(
                lados["basica"], lados["combinada"], aircraft, str(saida),
                ano=ano, mes=mes,
            )
        except Exception as e:  # noqa: BLE001
            print(f"  [{periodo}] ERRO no processamento: {e}", file=sys.stderr)
            falhas.append(f"processa_mov:{periodo}")
            continue
        if not csv:
            falhas.append(f"processa_mov:{periodo}")
            continue
        if sem_drive:
            print(f"  [--sem-drive] processado nao enviado: {Path(csv).name}")
            continue
        # A chave de origem define a pasta Processado/ (Movimentacao).
        if not comum.enviar_gdrive_processado(Path(csv), f"basica/{ano}{mes:02d}"):
            falhas.append(f"drive_proc:{periodo}")

    return falhas


def _processar_ticket(extraidos: list[Path], pasta_bases: Path | None,
                      sem_drive: bool) -> list[str]:
    """Processa cada CSV de tarifa (DOM/INT) extraido e envia ao Drive.

    DOM e autocontido. INT precisa do cache de dolar (pasta_bases). Se a
    base do dolar faltar, o INT e pulado com aviso -- o raw ja subiu.
    """
    falhas: list[str] = []
    # Filtra so os arquivos de tarifa (vieram da origem tarifas/*)
    tarifas = [p for p in extraidos
               if p.suffix.upper() == ".CSV"
               and (p.name.upper().startswith(("INTERNACIONAL",))
                    or re.fullmatch(r"\d{6}\.CSV", p.name.upper()))]
    if not tarifas:
        return falhas

    saida = comum.tmp() / "processado"
    saida.mkdir(parents=True, exist_ok=True)

    # Garante cache de dolar atualizado se houver INT
    tem_int = any(p.name.upper().startswith("INTERNACIONAL") for p in tarifas)
    if tem_int and pasta_bases:
        dolar.atualizar(pasta_bases)  # tenta IPEA; segue com cache se falhar

    print(f"\n== processando Ticket: {len(tarifas)} arquivo(s) ==")
    for p in sorted(tarifas):
        tipo = "int" if p.name.upper().startswith("INTERNACIONAL") else "dom"
        ano, mes = processa_ticket._periodo_do_nome(p.name)
        periodo = f"{ano}-{mes:02d}" if ano else p.name
        try:
            csv = processa_ticket.processar(p, str(saida), pasta_bases, tipo)
        except Exception as e:  # noqa: BLE001
            print(f"  [{periodo}] ERRO ticket {tipo}: {e}", file=sys.stderr)
            falhas.append(f"processa_tkt:{periodo}")
            continue
        if not csv:
            falhas.append(f"processa_tkt:{periodo}")
            continue
        if sem_drive:
            print(f"  [--sem-drive] processado nao enviado: {Path(csv).name}")
            continue
        chave = f"tarifas/{tipo}/{ano}"
        if not comum.enviar_gdrive_processado(Path(csv), chave):
            falhas.append(f"drive_proc_tkt:{periodo}")

    return falhas


def _processar_siros(extraidos: list[Path], pasta_bases: Path | None,
                     sem_drive: bool) -> list[str]:
    """Processa o voos.csv extraido (SIROS) e envia ao Drive (substitutivo)."""
    falhas: list[str] = []
    voos = [p for p in extraidos if p.name.lower() == "voos.csv"]
    if not voos:
        return falhas
    if not pasta_bases:
        print("  [siros] sem bases; processamento pulado (raw ja subiu)")
        return falhas

    saida = comum.tmp() / "processado"
    saida.mkdir(parents=True, exist_ok=True)
    print(f"\n== processando Siros ==")
    try:
        csv = processa_siros.processar(voos[0], str(saida), pasta_bases)
    except Exception as e:  # noqa: BLE001
        print(f"  ERRO siros: {e}", file=sys.stderr)
        return ["processa_siros"]
    if not csv:
        return ["processa_siros"]
    if sem_drive:
        print(f"  [--sem-drive] processado nao enviado: {Path(csv).name}")
        return falhas
    if not comum.enviar_gdrive_processado(Path(csv), "siros/voos"):
        falhas.append("drive_proc_siros")
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
    p.add_argument("--sem-processar", action="store_true",
                   help="coleta e envia o raw, mas nao gera os CSVs processados")
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

    # Extrai e envia cada zip coletado ao Drive (RAW), acumulando os
    # arquivos extraidos para a etapa de processamento.
    extraidos_todos: list[Path] = []
    if pendentes:
        print(f"\n== extraindo e enviando {len(pendentes)} arquivo(s) ao Drive ==")
        for _, chave, caminho in pendentes:
            print(f"\n[{chave}]")
            f, extraidos = _extrair_e_enviar(caminho, chave, args.sem_drive)
            falhas.extend(f)
            extraidos_todos.extend(extraidos)
    else:
        print("\nNada novo para enviar.")

    # Processamento: so faz sentido se algo foi extraido. Baixa as bases
    # do Drive uma vez (Aircraft/Airports/Airlines/dolar.csv) e processa
    # cada fonte. Falha de base nao derruba o run -- o raw ja subiu.
    if extraidos_todos and not args.sem_processar:
        pasta_bases = None if args.sem_drive else comum.baixar_bases_drive()
        if args.sem_drive:
            # Modo teste local sem Drive: tenta usar bases do proprio _tmp
            # se existirem, senao processa sem enriquecimento de aeronave.
            cand = comum.tmp() / "bases"
            pasta_bases = cand if cand.exists() else None
        falhas.extend(_processar_movimentacao(extraidos_todos, pasta_bases,
                                              args.sem_drive))
        falhas.extend(_processar_ticket(extraidos_todos, pasta_bases,
                                        args.sem_drive))
        falhas.extend(_processar_siros(extraidos_todos, pasta_bases,
                                       args.sem_drive))

    # Se algo foi enviado ao Drive, regenera o links.csv (inventario de
    # links de download que o PC corporativo usa para baixar sem logar no
    # Google). So no modo real (com Drive) e se houve envio.
    if pendentes and not args.sem_drive:
        print("\n== atualizando links.csv ==")
        try:
            gerar_links.gerar(enviar=True)
        except Exception as e:  # noqa: BLE001
            print(f"  [aviso] falha ao gerar links.csv: {e}", file=sys.stderr)

    comum.salvar_manifest(manifest)
    estado.escrever(manifest)

    if falhas:
        print(f"\nConcluido com falhas: {', '.join(falhas)}", file=sys.stderr)
        return 1
    print("\nConcluido sem falhas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
