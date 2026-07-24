"""Teste de alcance: as URLs da ANAC respondem a partir daqui?

Rode ANTES de confiar no agendamento. Sites gov.br as vezes recusam
requisicoes vindas de datacenters fora do Brasil, e os runners do
GitHub ficam nos EUA/Europa. Se falhar aqui mas funcionar na sua
maquina, o robo precisa rodar em outro lugar.
"""

import sys

sys.path.insert(0, ".")
from robo import comum, datasas, microdados, siros  # noqa: E402

ALVOS = [("SIROS", siros.URL), ("DataSAS", datasas.URL)]
for ano, mes in microdados.meses_alvo():
    ref = f"{ano}{mes:02d}"
    for seg in microdados.SEGMENTOS:
        ALVOS.append((f"{seg} {ref}", f"{microdados.BASE}/{seg}/{ano}/{seg}{ref}.zip"))

s = comum.sessao()
falhas = 0
for nome, url in ALVOS:
    try:
        r = s.head(url, timeout=60, allow_redirects=True)
        tam = r.headers.get("Content-Length", "?")
        print(f"OK    {nome:20} HTTP {r.status_code}  {tam} bytes")
    except Exception as e:
        falhas += 1
        print(f"FALHA {nome:20} {type(e).__name__}: {e}")

print(f"\n{len(ALVOS) - falhas}/{len(ALVOS)} alcancaveis")
raise SystemExit(1 if falhas == len(ALVOS) else 0)
