"""Sondagem 3 — quais links de download a pagina de microdados realmente tem?

A sondagem anterior mostrou 404 em todos os meses menos o mais recente,
inclusive em meses que sabidamente existem. Conclusao: a URL montada por
padrao (`/basica/AAAA/basicaAAAAMM.zip`) so acerta no mes corrente.

Em vez de adivinhar a convencao, este script le os links que a propria
pagina publica. Nao baixa nenhum arquivo — so o HTML.

Uso:  python sondagem3.py
"""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urljoin

import requests

BASE = (
    "https://www.gov.br/anac/pt-br/assuntos/regulados/empresas-aereas/"
    "Instrucoes-para-a-elaboracao-e-apresentacao-das-demonstracoes-contabeis/"
    "envio-de-informacoes"
)
PAGINA = f"{BASE}/microdados"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

L = "=" * 72
s = requests.Session()
s.headers.update({
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
})

print(f"{L}\nLendo {PAGINA}\n{L}")
r = s.get(PAGINA, timeout=90)
html = r.text
print(f"HTTP {r.status_code} — {len(html)} caracteres\n")

hrefs = re.findall(r'href\s*=\s*["\']([^"\']+)["\']', html, re.I)
print(f"Total de links na pagina: {len(hrefs)}")

zips = [urljoin(PAGINA + "/", h) for h in hrefs if h.lower().split("?")[0].endswith(".zip")]
print(f"Links terminando em .zip: {len(zips)}\n")


def classificar(u: str) -> str:
    b = u.lower()
    if "basica" in b:
        return "basica"
    if "combinada" in b:
        return "combinada"
    return "outro"


grupos: dict[str, list[str]] = {}
for u in zips:
    grupos.setdefault(classificar(u), []).append(u)

for nome in ("basica", "combinada", "outro"):
    lista = sorted(set(grupos.get(nome, [])))
    print(f"{L}\n{nome.upper()} — {len(lista)} link(s)\n{L}")
    if not lista:
        print("  (nenhum)\n")
        continue

    # Padroes de nome de arquivo, para revelar mudanca de convencao.
    padroes = Counter()
    for u in lista:
        arq = u.rsplit("/", 1)[-1]
        p = re.sub(r"\d", "N", arq)
        padroes[p] += 1
    print("  padroes de nome encontrados:")
    for p, n in padroes.most_common():
        print(f"    {p:32} {n} arquivo(s)")

    print("\n  primeiros 5:")
    for u in lista[:5]:
        print(f"    {u}")
    print("  ultimos 5:")
    for u in lista[-5:]:
        print(f"    {u}")
    print()

# Links que parecem paginas de ano/pasta, caso o inventario esteja paginado.
possiveis = sorted({
    urljoin(PAGINA + "/", h) for h in hrefs
    if re.search(r"/(basica|combinada)(/|$)", h, re.I)
    and not h.lower().endswith(".zip")
})
print(f"{L}\nPossiveis paginas de pasta/ano — {len(possiveis)}\n{L}")
for u in possiveis[:25]:
    print(f"  {u}")
if len(possiveis) > 25:
    print(f"  ... e mais {len(possiveis) - 25}")

if not zips:
    print(f"\n{L}\nNENHUM .zip no HTML — a lista deve ser montada por JavaScript.")
    print("Trecho ao redor da palavra 'basica' para eu analisar:")
    for m in list(re.finditer(r"basica", html, re.I))[:3]:
        ini, fim = max(0, m.start() - 200), min(len(html), m.end() + 200)
        print(f"\n---\n{html[ini:fim]}")

print(f"\n{L}\nCopie tudo acima e mande no chat.\n{L}")
