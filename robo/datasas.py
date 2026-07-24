"""DataSAS — tarifas de transporte aereo (domesticas e internacionais).

Unica fonte sem link direto: WebForms ASP.NET onde o zip so existe apos
Tema -> Ano -> Buscar -> Marcar -> Baixar.

Em compensacao, e a fonte mais rica: a tabela que aparece depois de
"Buscar Arquivos" traz a coluna "Data Hora Arquivo", com a data de
publicacao REAL de cada mes. Isso permite decidir se vale baixar sem
baixar nada -- e as datas ficam registradas por mes, mesmo o download
vindo com o ano inteiro num pacote so.

Ids confirmados por exploracao do site real.
O combo Ano e repovoado conforme o Tema: DOM tem 2002-2026, INT tem
2011-2025. Por isso o robo nunca pede ano fixo -- le o que existe.
"""

from __future__ import annotations

import re
import time
import unicodedata
from datetime import date
from pathlib import Path

from . import comum

URL = "https://sas.anac.gov.br/sas/downloads/view/frmDownload.aspx"

IDS = {
    "tema": "#MainContent_listTema",
    "ano": "#MainContent_listAno",
    "buscar": "#MainContent_btnListaArquivos",
    "marcar": "#MainContent_btnMarcar",
    "baixar": "#MainContent_btnBaixar",
}
FALLBACK = {
    "tema": "select[id*='Tema']",
    "ano": "select[id*='Ano']",
    "buscar": "input[value='Buscar Arquivos']",
    "marcar": "input[value='Marcar Todos']",
    "baixar": "input[value='Baixar Marcados']",
}

TIMEOUT_DOWNLOAD = 15 * 60 * 1000
TIMEOUT_PADRAO = 90 * 1000
TIMEOUT_POSTBACK = 20

RE_DATAHORA = re.compile(r"\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}(:\d{2})?")


def _simples(txt: str) -> str:
    n = unicodedata.normalize("NFKD", txt or "")
    return "".join(c for c in n if not unicodedata.combining(c)).lower().strip()


def classificar_tema(rotulo: str) -> str | None:
    s = _simples(rotulo)
    if "tarifa" not in s:
        return None
    if "internacion" in s:
        return "int"
    if "domestic" in s or "nacion" in s:
        return "dom"
    return None


# ------------------------------------------------------------- controles

def _el(page, chave: str):
    for sel in (IDS[chave], FALLBACK[chave]):
        loc = page.locator(sel)
        if loc.count():
            return loc.first
    raise RuntimeError(f"controle '{chave}' nao encontrado. Rode com --explorar.")


def _assentar(page) -> None:
    page.wait_for_load_state("domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:  # noqa: BLE001
        pass


def _opcoes_ano(page) -> list[str]:
    brutas = _el(page, "ano").locator("option").all_text_contents()
    return [t.strip() for t in brutas if re.fullmatch(r"\d{4}", t.strip())]


def selecionar_tema(page, rotulo: str) -> list[str]:
    """Seleciona o tema e devolve os anos disponiveis DEPOIS do postback."""
    from playwright.sync_api import TimeoutError as PWTimeout

    antes = tuple(_opcoes_ano(page))
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=15_000):
            _el(page, "tema").select_option(label=rotulo)
    except PWTimeout:
        pass  # postback parcial, sem navegacao
    _assentar(page)

    limite = time.time() + TIMEOUT_POSTBACK
    while time.time() < limite:
        agora = tuple(_opcoes_ano(page))
        if agora and agora != antes:
            return list(agora)
        time.sleep(0.5)
    return _opcoes_ano(page)


# ----------------------------------------------------------------- tabela

def ler_tabela(page) -> list[dict]:
    """Le a listagem gerada por 'Buscar Arquivos'.

    Devolve [{'arquivo','publicado_em','ano','mes','tamanho'}, ...].
    O mapeamento e por cabecalho, nao por posicao, para sobreviver a
    insercao de colunas.
    """
    tabelas = page.locator("table")
    alvo, cabec = None, []
    for i in range(tabelas.count()):
        t = tabelas.nth(i)
        titulos = [_simples(c) for c in t.locator("th").all_text_contents()]
        if any("data hora" in c for c in titulos):
            alvo, cabec = t, titulos
            break
    if alvo is None:
        return []

    def col(*chaves: str) -> int | None:
        for j, titulo in enumerate(cabec):
            if any(k in titulo for k in chaves):
                return j
        return None

    i_nome, i_data = col("nome do arquivo"), col("data hora")
    i_ano, i_mes = col("ano referencia"), col("mes referencia")
    i_tam = col("tamanho")

    registros = []
    linhas = alvo.locator("tr")
    for i in range(linhas.count()):
        celulas = linhas.nth(i).locator("td")
        n = celulas.count()
        if n < 3:
            continue
        v = [celulas.nth(j).inner_text().strip() for j in range(n)]

        def pega(idx):
            return v[idx] if idx is not None and idx < n else ""

        data = pega(i_data)
        if not RE_DATAHORA.search(data):
            continue  # linha de cabecalho ou rodape
        registros.append({
            "arquivo": pega(i_nome),
            "publicado_em": data,
            "ano": pega(i_ano),
            "mes": pega(i_mes).zfill(2),
            "tamanho": pega(i_tam),
        })
    return registros


def _abrir_ano(page, rotulo: str, ano: str) -> list[dict] | None:
    """Seleciona tema+ano, clica Buscar e devolve a tabela lida."""
    disponiveis = selecionar_tema(page, rotulo)
    if ano not in disponiveis:
        return None
    _el(page, "ano").select_option(label=ano)
    _assentar(page)
    _el(page, "buscar").click()
    _assentar(page)
    return ler_tabela(page)


# ------------------------------------------------------------ diagnostico

def _diagnostico(page, nome: str) -> None:
    pasta = comum.tmp() / "diagnostico"
    pasta.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(pasta / f"{nome}.png"), full_page=True)
        (pasta / f"{nome}.html").write_text(page.content(), encoding="utf-8")
        print(f"  diagnostico salvo em _tmp/diagnostico/{nome}.*")
    except Exception as e:  # noqa: BLE001
        print(f"  (falhou ao salvar diagnostico: {e})")


def _temas_tarifa(page) -> list[tuple[str, str]]:
    rotulos = [t.strip() for t in _el(page, "tema").locator("option").all_text_contents()]
    achados = [(r, classificar_tema(r)) for r in rotulos if classificar_tema(r)]
    if not achados:
        raise RuntimeError("nenhum tema de tarifa reconhecido: " + "; ".join(rotulos[:15]))
    return achados


# ------------------------------------------------------------- exploracao

def explorar() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        nav = pw.chromium.launch(headless=True)
        page = nav.new_page(user_agent=comum.UA)
        page.set_default_timeout(TIMEOUT_PADRAO)
        page.goto(URL, wait_until="domcontentloaded")
        _assentar(page)

        print(f"\ntitulo: {page.title()}\n--- temas ---")
        for r in _el(page, "tema").locator("option").all_text_contents():
            marca = classificar_tema(r)
            print(f"  {r.strip()}" + (f"   <== {marca}" if marca else ""))

        for rotulo, marca in _temas_tarifa(page):
            anos = selecionar_tema(page, rotulo)
            print(f"\n--- [{marca}] {rotulo} ---")
            print(f"  anos: {anos[0]}..{anos[-1]} ({len(anos)} anos)")
            if anos:
                tabela = _abrir_ano(page, rotulo, anos[-1]) or []
                print(f"  tabela de {anos[-1]}: {len(tabela)} linha(s)")
                for reg in tabela[:4]:
                    print(f"    {reg['ano']}-{reg['mes']}  {reg['publicado_em']}  "
                          f"{reg['tamanho']}  {reg['arquivo']}")
            page.goto(URL, wait_until="domcontentloaded")
            _assentar(page)

        _diagnostico(page, "exploracao")
        nav.close()


# ----------------------------------------------------------------- coleta

def _meses_registrados(m: dict, marca: str) -> dict[str, str]:
    """{'202606': '22/07/2026 19:30', ...} de todos os anos ja vistos."""
    saida = {}
    for chave, v in m.get("arquivos", {}).items():
        if chave.startswith(f"tarifas/{marca}/"):
            ano = chave.rsplit("/", 1)[-1]
            for mes, quando in (v.get("meses") or {}).items():
                saida[f"{ano}{mes}"] = quando
    return saida


def anos_alvo(m: dict, marca: str, disponiveis: list[str]) -> list[str]:
    """Quais anos conferir hoje.

    Sem historico, ancora no ano mais recente que o proprio combo oferece
    -- nao no ano do calendario. E o que corrige o caso INT: em 2026 o
    combo internacional so vai ate 2025, e chutar "2026" fazia o robo
    pular a fonte inteira sem nunca olhar.
    """
    if not disponiveis:
        return []
    registrados = _meses_registrados(m, marca)
    if not registrados:
        return [max(disponiveis)]

    ultimo = max(registrados)
    ano, mes = int(ultimo[:4]), int(ultimo[4:])
    alvo = str(ano + 1) if mes == 12 else str(ano)
    return [alvo] if alvo in disponiveis else []


def coletar(m: dict, completo: bool = False) -> list[tuple[str, str, Path]]:
    from playwright.sync_api import sync_playwright

    publicar: list[tuple[str, str, Path]] = []

    with sync_playwright() as pw:
        nav = pw.chromium.launch(headless=True)
        page = nav.new_page(user_agent=comum.UA, accept_downloads=True)
        page.set_default_timeout(TIMEOUT_PADRAO)

        try:
            page.goto(URL, wait_until="domcontentloaded")
            _assentar(page)
            temas = _temas_tarifa(page)

            for rotulo, marca in temas:
                disponiveis = selecionar_tema(page, rotulo)
                page.goto(URL, wait_until="domcontentloaded")
                _assentar(page)

                if completo:
                    alvos = disponiveis
                    print(f"\n[TARIFAS {marca.upper()}] varredura completa: "
                          f"{len(alvos)} ano(s)")
                else:
                    alvos = anos_alvo(m, marca, disponiveis)
                    registrados = _meses_registrados(m, marca)
                    ultimo = max(registrados) if registrados else "nenhum"
                    print(f"\n[TARIFAS {marca.upper()}] ultimo mes: {ultimo} | "
                          f"combo vai ate {max(disponiveis) if disponiveis else '?'} "
                          f"-> conferindo {alvos or 'nada'}")

                for ano in alvos:
                    chave = f"tarifas/{marca}/{ano}"
                    try:
                        tabela = _abrir_ano(page, rotulo, ano)
                    except Exception as e:  # noqa: BLE001
                        _diagnostico(page, f"falha_{marca}_{ano}")
                        print(f"  [{ano}] ERRO: {e}")
                        comum.registrar(m, chave, situacao="erro", detalhe=str(e)[:300])
                        page.goto(URL, wait_until="domcontentloaded")
                        _assentar(page)
                        continue

                    if not tabela:
                        print(f"  [{ano}] tabela vazia")
                        comum.registrar(m, chave, situacao="indisponivel")
                        page.goto(URL, wait_until="domcontentloaded")
                        _assentar(page)
                        continue

                    meses = {r["mes"]: r["publicado_em"] for r in tabela}
                    antes = (m["arquivos"].get(chave, {}).get("meses") or {})
                    novos = {k: v for k, v in meses.items() if k not in antes}
                    mudados = {k: v for k, v in meses.items()
                               if k in antes and antes[k] != v}

                    print(f"  [{ano}] {len(tabela)} arquivo(s); "
                          f"{len(novos)} novo(s), {len(mudados)} alterado(s)")
                    for k in sorted(novos):
                        print(f"      novo      {ano}-{k}  {novos[k]}")
                    for k in sorted(mudados):
                        print(f"      alterado  {ano}-{k}  {antes[k]} -> {mudados[k]}")

                    if not novos and not mudados:
                        comum.registrar(m, chave, meses=meses, situacao="inalterado")
                        page.goto(URL, wait_until="domcontentloaded")
                        _assentar(page)
                        continue

                    # So aqui o download acontece.
                    _el(page, "marcar").click()
                    _assentar(page)
                    with page.expect_download(timeout=TIMEOUT_DOWNLOAD) as dl:
                        _el(page, "baixar").click()
                    destino = comum.tmp() / f"tarifas_{marca}_{ano}.zip"
                    dl.value.save_as(str(destino))

                    conteudo = destino.read_bytes()
                    comum.validar_zip(conteudo)
                    situacao = "atualizado" if antes else "novo"
                    print(f"  [{ano}] {situacao} ({len(conteudo)/1_048_576:.1f} MB)")

                    comum.registrar(
                        m, chave, url=URL, meses=meses,
                        impressao=comum.impressao(conteudo),
                        sha256=comum.sha256(conteudo), bytes_zip=len(conteudo),
                        publicado_em=max(meses.values()) if meses else None,
                        situacao=situacao,
                    )
                    publicar.append((f"tarifas-{ano}", chave, destino))

                    page.goto(URL, wait_until="domcontentloaded")
                    _assentar(page)
        finally:
            nav.close()

    return publicar
