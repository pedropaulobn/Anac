"""Funcoes compartilhadas pelos robos de coleta da ANAC."""

from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
TMP = RAIZ / "_tmp"
MANIFEST = RAIZ / "manifest.json"

# Sites gov.br costumam recusar clientes sem User-Agent de navegador.
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

TENTATIVAS = 4
ESPERA_BASE = 5  # segundos; cresce exponencialmente
LIMITE_ASSET_MB = 2048  # teto do GitHub por asset de release


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tmp() -> Path:
    TMP.mkdir(parents=True, exist_ok=True)
    return TMP


def sessao() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "*/*"})
    return s


def baixar(url: str, s: requests.Session | None = None) -> bytes | None:
    """Baixa a URL. Devolve None se o arquivo nao existe (404).

    Levanta excecao se o erro for persistente e nao for 404, para que
    uma falha real apareca no log do Actions em vez de passar batido.
    """
    s = s or sessao()
    ultimo_erro: Exception | None = None

    for tentativa in range(1, TENTATIVAS + 1):
        try:
            r = s.get(url, timeout=300, allow_redirects=True)
            if r.status_code == 404:
                print(f"  [404] nao publicado: {url}")
                return None
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("resposta vazia")
            return r.content
        except Exception as e:  # noqa: BLE001
            ultimo_erro = e
            if tentativa < TENTATIVAS:
                espera = ESPERA_BASE * (2 ** (tentativa - 1))
                print(f"  [retry {tentativa}/{TENTATIVAS}] {e} -> aguardando {espera}s")
                time.sleep(espera)

    raise RuntimeError(f"falha ao baixar {url}: {ultimo_erro}")


def propriedades(url: str, s: requests.Session | None = None) -> dict | None:
    """Le tamanho e data do arquivo remoto SEM baixar o conteudo.

    Usa GET com Range 0-0 (pede um byte) em vez de HEAD, porque o
    Apache na frente do gov.br devolve 403 para HEAD -- confirmado por
    sondagem: HEAD -> 403 (Server: Apache), Range -> 206 (Server: Zope).

    stream=True e obrigatorio: se o servidor ignorar o Range e responder
    200, sem isso o corpo inteiro viria junto e a economia evaporaria.

    Devolve {'bytes': int|None, 'modificado_em': str|None} ou None se o
    arquivo nao existe.
    """
    s = s or sessao()
    try:
        with s.get(url, headers={"Range": "bytes=0-0"}, stream=True,
                   timeout=60, allow_redirects=True) as r:
            if r.status_code >= 400:
                # Distinguir importa: 404 e ausencia real, 403 e bloqueio.
                print(f"    HTTP {r.status_code}")
                return None

            total = None
            faixa = r.headers.get("Content-Range")  # "bytes 0-0/8377273"
            if faixa and "/" in faixa:
                cauda = faixa.rsplit("/", 1)[-1].strip()
                if cauda.isdigit():
                    total = int(cauda)
            elif r.status_code == 200:
                cl = r.headers.get("Content-Length")
                if cl and cl.isdigit():
                    total = int(cl)

            return {"bytes": total, "modificado_em": r.headers.get("Last-Modified")}
    except Exception as e:  # noqa: BLE001
        print(f"  (falha ao sondar {url}: {e})")
        return None


def sha256(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def validar_zip(conteudo: bytes) -> list[str]:
    """Confere que o download e mesmo um zip legivel.

    A ANAC as vezes devolve HTTP 200 com uma pagina de erro HTML no
    corpo. Sem esta checagem, o robo publicaria lixo com hash novo a
    cada execucao.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            nomes = z.namelist()
            if not nomes:
                raise RuntimeError("zip vazio")
            ruim = z.testzip()
            if ruim:
                raise RuntimeError(f"entrada corrompida: {ruim}")
            return nomes
    except zipfile.BadZipFile as e:
        amostra = conteudo[:120].decode("utf-8", "replace")
        raise RuntimeError(f"resposta nao e um zip ({e}); inicio: {amostra!r}") from e


def impressao(conteudo: bytes) -> str:
    """Hash estavel do CONTEUDO de um zip, ignorando metadados.

    Zips gerados sob demanda pelo servidor (caso do DataSAS) carregam o
    horario da geracao nos membros, entao o sha256 do arquivo muda a cada
    download mesmo sem mudanca de dado. Esta impressao usa apenas nome,
    tamanho e CRC de cada membro, ordenados -- e portanto so muda quando
    o dado realmente mudou.
    """
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        itens = sorted(
            (i.filename, i.file_size, i.CRC) for i in z.infolist() if not i.is_dir()
        )
    bruto = "\n".join(f"{n}|{t}|{c}" for n, t, c in itens)
    return hashlib.sha256(bruto.encode()).hexdigest()


def salvar(conteudo: bytes, nome: str) -> Path:
    caminho = tmp() / nome
    caminho.write_bytes(conteudo)
    return caminho


def extrair(conteudo_zip: bytes, destino: Path, nome_canonico: str | None = None) -> list[str]:
    """Extrai .csv/.txt de dentro do zip. Reservado para a etapa 2."""
    destino.mkdir(parents=True, exist_ok=True)
    escritos: list[str] = []

    with zipfile.ZipFile(io.BytesIO(conteudo_zip)) as z:
        alvos = [
            i for i in z.infolist()
            if not i.is_dir() and i.filename.lower().endswith((".csv", ".txt"))
        ]
        if not alvos:
            raise RuntimeError("zip sem .csv/.txt: " + ", ".join(z.namelist()[:20]))

        for info in alvos:
            nome = nome_canonico if (nome_canonico and len(alvos) == 1) else Path(info.filename).name
            caminho = destino / nome
            with z.open(info) as origem, open(caminho, "wb") as saida:
                saida.write(origem.read())
            escritos.append(nome)

    return escritos


def carregar_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"gerado_em": None, "arquivos": {}}


def salvar_manifest(m: dict) -> None:
    m["gerado_em"] = agora()
    MANIFEST.write_text(
        json.dumps(m, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def registrar(m: dict, chave: str, **campos) -> None:
    entrada = m["arquivos"].get(chave, {})
    if "coletado_em" not in entrada:
        entrada["coletado_em"] = agora()
    entrada.update(campos)
    entrada["verificado_em"] = agora()
    m["arquivos"][chave] = entrada
