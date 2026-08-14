# -*- coding: utf-8 -*-
"""processa_tudo.py — orquestrador local ("faz tudo que falta").

Roda no .bat local (o robo do GitHub NAO importa este modulo). Em vez de
escolher mes a mes, varre as pastas Raw e Processado, descobre o que ainda
nao foi processado e faz o pipeline completo de cada mes pendente:

    Movimentacao -> Ticket DOM/INT -> Agrupar -> Mesclar (95 colunas)

Dois modos:
  - SEM --ano (opcao 1 do menu): so olha >= ANO_MINIMO (o ano corrente e
    o presente). Ao final, gera o arquivo de CONSUMO do ano corrente em
    Historico/Anual/{ano}.csv, com o Siros anexado (visao passado+futuro).
  - COM --ano AAAA (opcao 2 do menu): processa aquele ano especifico,
    SEM o piso ANO_MINIMO -- e assim que o historico (2025 pra tras, que
    so tem Raw) e processado. Nao gera arquivo de consumo/Siros; para
    congelar o ano use a opcao "Fechar ano".

Idempotente: o que ja tem _final pronto e pulado (a menos de --forcar).
Toda a logica de caminho fica em Python, que lida com acentos no path sem
os problemas do batch.

Dolar (INT): se algum mes INT for processado, o cache do IPEA e atualizado
automaticamente uma vez no inicio (a API traz a serie historica inteira num
call so). Se o IPEA cair, segue com o cache atual. Nao ha mais necessidade
de rodar a opcao "Atualizar dolar" a mao antes de processar.

Uso (chamado pelo menu.bat):
    python -m robo.processa_tudo --corp "<...>\\Anac" --bases "<...>\\Bases"
    python -m robo.processa_tudo --corp "..." --bases "..." --ano 2025
    python -m robo.processa_tudo --corp "..." --bases "..." --forcar
"""

from __future__ import annotations

import argparse
import os
import re
from datetime import date
from pathlib import Path

from . import (comum, processa_mes, processa_ticket, agrupa_ticket,
               mescla_final, fecha_ano, dolar)


def _meses_raw_movimentacao(mov_raw: Path, ano_min: int) -> set[tuple[int, int]]:
    """Descobre (ano, mes) que tem PAR basica+combinada na pasta Raw."""
    bas, comb = {}, {}
    if not mov_raw.exists():
        return set()
    for arq in mov_raw.iterdir():
        if not arq.is_file() or not arq.suffix.lower() == ".txt":
            continue
        m = re.match(r"(basica|combinada)(\d{4})-?(\d{2})", arq.name.lower())
        if not m:
            continue
        ano, mes = int(m.group(2)), int(m.group(3))
        if ano < ano_min:
            continue
        (bas if m.group(1) == "basica" else comb)[(ano, mes)] = arq
    # so os meses com os DOIS lados
    return set(bas) & set(comb)


def _meses_raw_ticket(tkt_raw: Path, ano_min: int) -> dict[tuple[int, int], dict]:
    """Descobre tarifas DOM/INT na pasta Raw, por (ano, mes)."""
    achados: dict[tuple[int, int], dict] = {}
    if not tkt_raw.exists():
        return achados
    for arq in tkt_raw.iterdir():
        if not arq.is_file() or arq.suffix.lower() != ".csv":
            continue
        nome = arq.name.upper()
        if nome.startswith("INTERNACIONAL"):
            m = re.search(r"(\d{4})-(\d{2})", nome)
            tipo = "int"
        else:
            # DOM: 6 digitos no INICIO. Nao exige '.CSV' logo apos, para
            # tolerar sufixos que a ANAC as vezes adiciona, tipo
            # '202605 (1).CSV' ou '202605(1).CSV'.
            m = re.match(r"(\d{4})(\d{2})", nome)
            tipo = "dom"
        if not m:
            continue
        ano, mes = int(m.group(1)), int(m.group(2))
        if ano < ano_min:
            continue
        achados.setdefault((ano, mes), {})[tipo] = arq
    return achados


def _tem_final(mov_proc: Path, ano: int, mes: int) -> bool:
    return (mov_proc / f"anac_{ano}-{mes:02d}_final.csv").exists()


def _tem_mov(mov_proc: Path, ano: int, mes: int) -> bool:
    return (mov_proc / f"anac_{ano}-{mes:02d}.csv").exists()


def processar_tudo(corp_anac: str, bases: str, ano_alvo: int | None = None,
                   forcar: bool = False) -> int:
    """Varre as pastas e processa tudo que falta. Devolve nº de falhas."""
    corp = Path(corp_anac)
    mov_raw = corp / "Movimentacao" / "Raw"
    mov_proc = corp / "Movimentacao" / "Processado"
    tkt_raw = corp / "Ticket" / "Raw"
    tkt_proc = corp / "Ticket" / "Processado"
    aircraft = str(Path(bases) / "Aircraft.xlsx")

    mov_proc.mkdir(parents=True, exist_ok=True)
    tkt_proc.mkdir(parents=True, exist_ok=True)

    # Piso da varredura:
    #   - COM --ano: o proprio ano e o piso (ignora ANO_MINIMO). E o que
    #     libera processar o historico (2025 pra tras), que so tem Raw.
    #   - SEM --ano: >= ANO_MINIMO (o robo do GitHub cuida do presente; o
    #     historico fica para a opcao "processar ano especifico").
    # ANO_MINIMO (em comum.py) NAO e alterado -- ele governa a COLETA do
    # GitHub. Aqui so decidimos ate onde o .bat local varre.
    piso = ano_alvo if ano_alvo else comum.ANO_MINIMO

    def _no_alvo(ano):
        return ano == ano_alvo if ano_alvo else ano >= comum.ANO_MINIMO

    # Diagnostico: mostrar exatamente onde esta olhando e o que achou.
    print(f"  Raw Movimentacao: {mov_raw}")
    print(f"    existe? {mov_raw.exists()}", end="")
    if mov_raw.exists():
        txts = list(mov_raw.glob("*.txt")) + list(mov_raw.glob("*.TXT"))
        print(f" | {len(txts)} arquivo(s) .txt")
    else:
        print()
    print(f"  Raw Ticket: {tkt_raw}")
    print(f"    existe? {tkt_raw.exists()}", end="")
    if tkt_raw.exists():
        csvs = list(tkt_raw.glob("*.csv")) + list(tkt_raw.glob("*.CSV"))
        print(f" | {len(csvs)} arquivo(s) .csv")
    else:
        print()

    pares_mov = {(a, m) for (a, m) in _meses_raw_movimentacao(mov_raw, piso)
                 if _no_alvo(a)}
    tickets = {(a, m): v for (a, m), v in _meses_raw_ticket(tkt_raw, piso).items()
               if _no_alvo(a)}

    todos_meses = sorted(pares_mov | set(tickets))
    if not todos_meses:
        alvo_txt = f"no ano {ano_alvo}" if ano_alvo else f">= {comum.ANO_MINIMO}"
        print(f"Nada a processar (nenhum bruto {alvo_txt}).")
        # Mesmo sem meses novos, o consumo do ano corrente e regerado
        # (o Siros muda todo dia). Faz sentido so no modo sem --ano.
        if ano_alvo is None:
            _gerar_consumo(corp, mov_proc)
        return 0

    print(f"Meses com bruto disponivel: {len(todos_meses)}")

    # Dolar automatico: se ha algum mes com INT a processar, atualiza o
    # cache do IPEA UMA vez (a serie historica inteira vem num call so).
    # Se o IPEA cair, atualizar() mantem o cache atual e segue.
    tem_int = any("int" in tickets.get(km, {}) for km in tickets)
    if tem_int:
        print("\n  Atualizando cache do dolar (IPEA) antes do Ticket INT...")
        try:
            dolar.atualizar(bases)
        except Exception as e:  # noqa: BLE001
            print(f"  [dolar] falha ao atualizar (segue com cache): {str(e)[:120]}")

    falhas = 0
    processados, pulados = 0, 0

    for (ano, mes) in todos_meses:
        periodo = f"{ano}-{mes:02d}"
        if not forcar and _tem_final(mov_proc, ano, mes):
            pulados += 1
            continue

        print(f"\n{'='*60}\n  {periodo}\n{'='*60}")

        # 1. Movimentacao (se houver par e ainda nao processada)
        if (ano, mes) in pares_mov and (forcar or not _tem_mov(mov_proc, ano, mes)):
            try:
                r = processa_mes.processar_mes(ano, mes, str(mov_raw),
                                               aircraft, str(mov_proc))
                if not r:
                    falhas += 1
            except Exception as e:  # noqa: BLE001
                print(f"  [ERRO] movimentacao {periodo}: {e}")
                falhas += 1
        elif (ano, mes) not in pares_mov:
            print(f"  [aviso] sem par basica+combinada para {periodo}")

        # 2. Ticket DOM/INT (se houver bruto)
        if (ano, mes) in tickets:
            lados = tickets[(ano, mes)]
            if "dom" in lados:
                try:
                    processa_ticket.processar(lados["dom"], str(tkt_proc), bases, "dom")
                except Exception as e:  # noqa: BLE001
                    print(f"  [ERRO] ticket dom {periodo}: {e}")
                    falhas += 1
            if "int" in lados:
                try:
                    processa_ticket.processar(lados["int"], str(tkt_proc), bases, "int")
                except Exception as e:  # noqa: BLE001
                    print(f"  [ERRO] ticket int {periodo}: {e}")
                    falhas += 1
            # 3. Agrupar DOM+INT
            try:
                agrupa_ticket.agrupar(str(tkt_proc), ano, mes)
            except Exception as e:  # noqa: BLE001
                print(f"  [ERRO] agrupar {periodo}: {e}")
                falhas += 1

        # 4. Mesclar (precisa da movimentacao pronta)
        mov_csv = mov_proc / f"anac_{periodo}.csv"
        if mov_csv.exists():
            tkt_csv = tkt_proc / f"ticket_{periodo}.csv"
            try:
                mescla_final.mesclar(str(mov_csv),
                                     str(tkt_csv) if tkt_csv.exists() else None,
                                     str(mov_proc), ano, mes)
                processados += 1
            except Exception as e:  # noqa: BLE001
                print(f"  [ERRO] mesclar {periodo}: {e}")
                falhas += 1
        else:
            print(f"  [aviso] sem movimentacao processada; nao mescla {periodo}")

    print(f"\n{'='*60}")
    print(f"  Concluido: {processados} processado(s), {pulados} ja pronto(s), "
          f"{falhas} falha(s)")
    print(f"{'='*60}")

    # Arquivo de consumo do ano corrente (finais + Siros). So no modo sem
    # --ano; ao processar um ano historico especifico, use "Fechar ano".
    if ano_alvo is None:
        _gerar_consumo(corp, mov_proc)

    return falhas


def _gerar_consumo(corp: Path, mov_proc: Path) -> None:
    """Regenera Historico/Anual/{ano_corrente}.csv com Siros anexado.

    Chamado ao fim da opcao 1. E o arquivo que o BI consome; atualiza todo
    dia (o Siros muda diariamente). Se o siros.csv nao estiver no corp, a
    propria fechar_ano_vivo avisa e preserva o arquivo anterior.
    """
    ano_corrente = date.today().year
    hist_anual = corp / "Historico" / "Anual"
    siros_proc = corp / "Siros" / "Processado"
    print(f"\n{'='*60}\n  Gerando consumo do ano corrente ({ano_corrente})\n{'='*60}")
    try:
        fecha_ano.fechar_ano_vivo(str(mov_proc), ano_corrente,
                                  str(hist_anual), str(siros_proc))
    except Exception as e:  # noqa: BLE001
        print(f"  [ERRO] ao gerar consumo {ano_corrente}: {e}")


def _cli() -> int:
    p = argparse.ArgumentParser(
        description="Processa tudo que falta. Sem --ano: >= ANO_MINIMO + "
                    "gera consumo do ano corrente. Com --ano: aquele ano "
                    "(historico), sem piso.")
    p.add_argument("--corp", required=True, help="raiz Anac do OneDrive corp")
    p.add_argument("--bases", required=True, help="pasta Bases")
    p.add_argument("--ano", type=int,
                   help="processa um ano especifico (historico), ignora ANO_MINIMO")
    p.add_argument("--forcar", action="store_true",
                   help="reprocessa mesmo os que ja tem _final")
    args = p.parse_args()
    return 1 if processar_tudo(args.corp, args.bases, args.ano, args.forcar) else 0


if __name__ == "__main__":
    raise SystemExit(_cli())
