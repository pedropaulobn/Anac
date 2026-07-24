"""Gera ESTADO.md — o retrato legivel da ultima coleta.

O manifest.json guarda tudo e e feito para o robo ler. Este arquivo e
feito para voce ler: qual o ultimo periodo de cada fonte, quando a ANAC
publicou, quando o robo pegou.

E reescrito a cada execucao. Fonte sem novidade mantem a linha anterior,
porque a tabela nasce do historico acumulado e nao do que ocorreu hoje.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import comum

ESTADO = comum.RAIZ / "ESTADO.md"
VALIDOS = {"novo", "atualizado", "republicado", "inalterado"}

ROTULO = {
    "basica": "Movimentação — básica",
    "combinada": "Movimentação — combinada",
    "tarifas/dom": "Tarifas — domésticas",
    "tarifas/int": "Tarifas — internacionais",
}


def _br(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso


def _mb(n) -> str:
    return f"{n / 1_048_576:.1f} MB" if isinstance(n, int) else "—"


def _periodo_mensal(ref: str) -> str:
    return f"{ref[:4]}-{ref[4:]}" if len(ref) == 6 and ref.isdigit() else ref


def _cobertura(pagina: dict, arquivos: dict, segmento: str) -> str:
    """'202606 (312 de 318)' — o que o site tem contra o que ja foi pego."""
    inv = (pagina.get("inventario") or {}).get(segmento) or {}
    total = inv.get("total")
    pegos = sum(1 for k, v in arquivos.items()
                if k.startswith(f"{segmento}/") and v.get("situacao") in VALIDOS)
    if not total:
        return "—"
    return f"{inv.get('ultimo') or '?'} ({pegos} de {total})"


def _linha_microdados(arquivos: dict, segmento: str) -> str:
    itens = [
        (k.split("/", 1)[1], v) for k, v in arquivos.items()
        if k.startswith(f"{segmento}/") and v.get("situacao") in VALIDOS
    ]
    if not itens:
        return f"| {ROTULO[segmento]} | — | — | — | — | nunca coletado |"
    ref, e = max(itens, key=lambda kv: kv[0])
    return (f"| {ROTULO[segmento]} | **{_periodo_mensal(ref)}** | ver nota ¹ "
            f"| {_br(e.get('verificado_em'))} | {_mb(e.get('bytes_zip'))} "
            f"| {e.get('situacao', '—')} |")


def _linha_tarifas(arquivos: dict, marca: str) -> str:
    chave = f"tarifas/{marca}"
    meses: dict[str, str] = {}
    ultima_entrada = None
    for k, v in arquivos.items():
        if k.startswith(chave + "/") and v.get("meses"):
            ano = k.rsplit("/", 1)[-1]
            for mes, quando in v["meses"].items():
                meses[f"{ano}{mes}"] = quando
            if v.get("situacao") in VALIDOS:
                ultima_entrada = v
    if not meses:
        return f"| {ROTULO[chave]} | — | — | — | — | nunca coletado |"
    ref = max(meses)
    e = ultima_entrada or {}
    return (f"| {ROTULO[chave]} | **{_periodo_mensal(ref)}** | {meses[ref]} "
            f"| {_br(e.get('verificado_em'))} | {_mb(e.get('bytes_zip'))} "
            f"| {e.get('situacao', '—')} |")


def escrever(m: dict) -> None:
    arquivos = m.get("arquivos", {})
    pagina = m.get("pagina_microdados", {})

    linhas = [
        "# Estado da coleta",
        "",
        f"Última execução do robô: **{_br(m.get('gerado_em'))} UTC**",
        "",
        "| Fonte | Último período | Publicado no site | Coletado em | Tamanho | Situação |",
        "|---|---|---|---|---|---|",
        _linha_microdados(arquivos, "basica"),
        _linha_microdados(arquivos, "combinada"),
        _linha_tarifas(arquivos, "dom"),
        _linha_tarifas(arquivos, "int"),
    ]

    s = arquivos.get("siros/voos")
    if s:
        linhas.append(
            f"| SIROS — voos futuros | (diário) | {s.get('publicado_em') or '—'} "
            f"| {_br(s.get('verificado_em'))} | {_mb(s.get('bytes_zip'))} "
            f"| {s.get('situacao', '—')} |"
        )

    linhas += [
        "",
        "## Cobertura dos microdados",
        "",
        "| Segmento | Último no site (coletados de disponíveis) |",
        "|---|---|",
        f"| básica | {_cobertura(pagina, arquivos, 'basica')} |",
        f"| combinada | {_cobertura(pagina, arquivos, 'combinada')} |",
        "",
        "Se o número coletado for menor que o total do site, rode `--backfill`.",
        "",
        f"¹ O servidor dos microdados não informa data por arquivo — só a página "
        f"inteira, que consta como **atualizada em {pagina.get('atualizado') or '—'}** "
        f"(publicada em {pagina.get('publicado') or '—'}). "
        "A detecção de republicação usa o tamanho em bytes de cada arquivo.",
    ]

    problemas = [(k, v) for k, v in sorted(arquivos.items())
                 if v.get("situacao") in {"erro", "indisponivel"}]
    if problemas:
        linhas += ["", "## Atenção", ""]
        for k, v in problemas:
            det = v.get("detalhe", "")
            linhas.append(f"- `{k}` — {v['situacao']}" + (f": {det[:120]}" if det else ""))

    republicados = [k for k, v in sorted(arquivos.items())
                    if v.get("situacao") == "republicado"]
    if republicados:
        linhas += [
            "", "## Republicados na última execução", "",
            "A ANAC alterou estes períodos depois de já os termos coletado.",
            "Se o dado já foi consumido, vale reprocessar:", "",
        ]
        linhas += [f"- `{k}`" for k in republicados]

    linhas += [
        "", "---", "",
        f"Períodos rastreados: **{len(arquivos)}**",
        "",
        "Arquivos ficam nas *Releases* do repositório. Detalhe técnico completo",
        "(hash, tamanho, datas por mês) está em `manifest.json`.",
        "",
    ]

    ESTADO.write_text("\n".join(linhas), encoding="utf-8")
    print(f"\nESTADO.md atualizado ({len(arquivos)} periodos rastreados)")
