"""Funcoes compartilhadas pelos robos de coleta da ANAC."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
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

TENTATIVAS = 3
ESPERA_BASE = 4  # segundos; cresce exponencialmente
TIMEOUT_CONEXAO = 30  # segundos para estabelecer conexao (nao o download todo)
TIMEOUT_LEITURA = 300  # segundos para baixar o corpo, uma vez conectado
LIMITE_ASSET_MB = 2048  # teto do GitHub por asset de release

# Piso de ano para coleta automatica. O robo do GitHub so cuida do
# presente; o historico (2000..2025) ja esta congelado no OneDrive
# corporativo e e reprocessado localmente pelo .bat. Isso evita que uma
# varredura completa (ou um manifest vazio) faca o robo tentar rebaixar
# 25 anos de tarifa via Playwright -- causa do exit 1 no log de julho.
# Para mudar o horizonte do robo, muda-se so aqui.
ANO_MINIMO = 2026

# Onde procurar o rclone. No PC do Pedro esta em C:\Backup\Rclone;
# no GitHub Actions (Linux) esta no PATH como "rclone".
RCLONE_WINDOWS = r"C:\Backup\Rclone\rclone.exe"


def rclone_bin() -> str:
    """Descobre o executavel do rclone conforme o ambiente.

    Prioridade: caminho fixo do Windows (se existir) -> rclone no PATH.
    Isso permite o mesmo codigo rodar no PC e no GitHub Actions.
    """
    if os.path.exists(RCLONE_WINDOWS):
        return RCLONE_WINDOWS
    achado = shutil.which("rclone")
    if achado:
        return achado
    # Ultimo recurso: tenta "rclone" e deixa o subprocess falhar com mensagem clara.
    return "rclone"


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

    Imprime o que esta tentando ANTES de tentar, para que um travamento
    apareca no log com o alvo identificado, nao como silencio.

    Usa timeout (conexao, leitura) separados: 30s para ESTABELECER a
    conexao, 300s para baixar o corpo. Assim um servidor inalcancavel
    falha em 30s, nao fica pendurado. Erro de conexao (host inalcancavel)
    desiste apos poucas tentativas; nao adianta insistir 4x num servidor
    que nao responde.
    """
    s = s or sessao()
    ultimo_erro: Exception | None = None
    curto = url if len(url) < 90 else "..." + url[-80:]

    for tentativa in range(1, TENTATIVAS + 1):
        try:
            print(f"  GET {curto} (tentativa {tentativa}/{TENTATIVAS})")
            r = s.get(url, timeout=(TIMEOUT_CONEXAO, TIMEOUT_LEITURA),
                      allow_redirects=True)
            if r.status_code == 404:
                print(f"  [404] nao publicado")
                return None
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("resposta vazia")
            return r.content
        except requests.exceptions.ConnectionError as e:
            # Host inalcancavel: falha de rede, nao adianta insistir muito.
            print(f"  [conexao falhou] {str(e)[:120]}")
            ultimo_erro = e
            if tentativa < 2:  # so uma re-tentativa para erro de conexao
                time.sleep(ESPERA_BASE)
            else:
                break
        except Exception as e:  # noqa: BLE001
            print(f"  [erro] {str(e)[:120]}")
            ultimo_erro = e
            if tentativa < TENTATIVAS:
                espera = ESPERA_BASE * (2 ** (tentativa - 1))
                print(f"  aguardando {espera}s")
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


def extrair(conteudo_zip: bytes, destino: Path) -> list[Path]:
    """Extrai .csv/.txt de dentro do zip, mantendo nomes originais.

    Procura por qualquer arquivo .csv ou .txt dentro do ZIP (case-insensitive).
    Preserva o nome original exatamente como esta no arquivo.

    Devolve lista de Path dos arquivos extraidos. Se nenhum arquivo
    .csv/.txt existe, levanta RuntimeError.
    """
    destino.mkdir(parents=True, exist_ok=True)
    escritos: list[Path] = []

    with zipfile.ZipFile(io.BytesIO(conteudo_zip)) as z:
        alvos = [
            i for i in z.infolist()
            if not i.is_dir() and i.filename.lower().endswith((".csv", ".txt"))
        ]
        if not alvos:
            raise RuntimeError("zip sem .csv/.txt: " + ", ".join(z.namelist()[:20]))

        for info in alvos:
            caminho = destino / Path(info.filename).name
            with z.open(info) as origem, open(caminho, "wb") as saida:
                saida.write(origem.read())
            tam_mb = caminho.stat().st_size / 1_048_576
            print(f"  extraido: {caminho.name} ({tam_mb:.1f} MB)")
            escritos.append(caminho)

    return escritos


# Raiz da nova estrutura no Drive. Tudo pende de Sync/Fraport.
DRIVE_RAIZ = "gdrive:Sync/Fraport"
DRIVE_BASES = f"{DRIVE_RAIZ}/Bases"


def _destino_drive(chave: str) -> tuple[str, str]:
    """Decide a pasta RAW do Drive a partir da ORIGEM (a chave do manifest),
    nao do nome do arquivo.

    A chave diz de onde o arquivo veio: 'basica/202606', 'combinada/...',
    'tarifas/dom/2026', 'tarifas/int/2025', 'siros/voos'. O nome do
    arquivo extraido nao e confiavel -- tarifa DOM vem como '202601.CSV'
    (numero puro), e um mesmo numero poderia colidir entre fontes. A
    origem, o robo sempre conhece.

    Nova estrutura: cada fonte tem Raw/ (bruto) e Processado/ (pronto).
    Esta funcao devolve a pasta RAW. DOM e INT ficam juntos na mesma
    pasta Raw (nomes disjuntos: '202601.CSV' vs 'INTERNACIONAL_2025-12.CSV').

    Devolve (pasta_no_drive, modo) onde modo e 'acumula' ou 'substitui'.
    """
    if chave.startswith("basica/") or chave.startswith("combinada/"):
        return f"{DRIVE_RAIZ}/Anac/Movimentacao/Raw/", "acumula"
    if chave.startswith("tarifas/dom/") or chave.startswith("tarifas/int/"):
        return f"{DRIVE_RAIZ}/Anac/Ticket/Raw/", "acumula"
    if chave.startswith("siros/"):
        return f"{DRIVE_RAIZ}/Anac/Siros/Raw/", "substitui"
    # Origem desconhecida: falha explicita, para nao espalhar em pasta errada.
    raise ValueError(f"origem nao reconhecida para o Drive: {chave!r}")


def _destino_processado(chave: str) -> tuple[str, str]:
    """Pasta PROCESSADO do Drive para uma origem.

    Espelha _destino_drive mas aponta para .../Processado/. Usada para
    enviar o CSV ja processado (75 cols na Movimentacao, ticket agrupado,
    siros com flip).

    Devolve (pasta_no_drive, modo).
    """
    if chave.startswith("basica/") or chave.startswith("combinada/"):
        return f"{DRIVE_RAIZ}/Anac/Movimentacao/Processado/", "acumula"
    if chave.startswith("tarifas/dom/") or chave.startswith("tarifas/int/"):
        return f"{DRIVE_RAIZ}/Anac/Ticket/Processado/", "acumula"
    if chave.startswith("siros/"):
        return f"{DRIVE_RAIZ}/Anac/Siros/Processado/", "substitui"
    raise ValueError(f"origem nao reconhecida para processado: {chave!r}")


def enviar_gdrive(caminho_local: Path, chave: str) -> bool:
    """Envia arquivo extraido para a pasta correta no Google Drive via rclone.

    A pasta e escolhida por _destino_drive(chave), a partir da ORIGEM --
    nunca do nome do arquivo. 'chave' e a mesma do manifest: 'basica/...',
    'tarifas/dom/...', 'siros/voos', etc.

    O executavel do rclone e descoberto por rclone_bin(), que funciona
    tanto no PC do Pedro quanto no GitHub Actions.

    Devolve True se enviou com sucesso, False se falhou.
    """
    if not caminho_local.exists():
        print(f"  ERRO: {caminho_local} nao existe")
        return False

    try:
        destino, modo = _destino_drive(chave)
    except ValueError as e:
        print(f"  ERRO: {e}")
        return False

    exe = rclone_bin()

    try:
        # sync (SIROS) deleta o que nao existe local; copy (resto) so envia.
        acao = "sync" if modo == "substitui" else "copy"
        cmd = [exe, acao, str(caminho_local), destino, "--verbose"]

        print(f"  enviando [{modo}]: {caminho_local.name} -> {destino}")
        resultado = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if resultado.returncode == 0:
            tam = caminho_local.stat().st_size / 1_048_576
            print(f"  ok: {caminho_local.name} ({tam:.1f} MB) em {destino}")
            return True

        print(f"  ERRO ao enviar (codigo {resultado.returncode}):")
        print(f"  {resultado.stderr.strip()}")
        return False

    except FileNotFoundError:
        print(f"  ERRO: rclone nao encontrado em '{exe}'")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"  ERRO: {e}")
        return False


def enviar_gdrive_processado(caminho_local: Path, chave: str) -> bool:
    """Envia arquivo JA PROCESSADO para a pasta Processado/ da origem.

    Igual a enviar_gdrive, mas usa _destino_processado (pasta Processado/
    em vez de Raw/). A pasta e escolhida pela ORIGEM (chave do manifest),
    nunca pelo nome do arquivo.

    Devolve True se enviou, False se falhou.
    """
    if not caminho_local.exists():
        print(f"  ERRO: {caminho_local} nao existe")
        return False

    try:
        destino, modo = _destino_processado(chave)
    except ValueError as e:
        print(f"  ERRO: {e}")
        return False

    exe = rclone_bin()
    try:
        acao = "sync" if modo == "substitui" else "copy"
        cmd = [exe, acao, str(caminho_local), destino, "--verbose"]
        print(f"  enviando processado [{modo}]: {caminho_local.name} -> {destino}")
        resultado = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if resultado.returncode == 0:
            tam = caminho_local.stat().st_size / 1_048_576
            print(f"  ok: {caminho_local.name} ({tam:.1f} MB) em {destino}")
            return True
        print(f"  ERRO ao enviar (codigo {resultado.returncode}):")
        print(f"  {resultado.stderr.strip()}")
        return False
    except FileNotFoundError:
        print(f"  ERRO: rclone nao encontrado em '{exe}'")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"  ERRO: {e}")
        return False


def baixar_bases_drive() -> Path | None:
    """Baixa as bases auxiliares do Drive para _tmp/bases/ via rclone.

    As dimensoes (Aircraft, Airports, Airlines) e o cache de cambio
    (dolar.csv) vivem em Sync/Fraport/Bases/. O .bat garante que essa
    pasta tem sempre a versao mais recente (corp = pessoal = Drive).

    O robo do GitHub le essa pasta antes de processar, porque nao tem
    acesso ao OneDrive corporativo.

    Devolve o Path da pasta local com as bases, ou None se falhou.
    Falha NAO derruba o run: quem chama decide se pula o processamento.
    """
    destino = tmp() / "bases"
    destino.mkdir(parents=True, exist_ok=True)
    exe = rclone_bin()
    try:
        cmd = [exe, "copy", f"{DRIVE_BASES}/", str(destino), "--verbose"]
        print(f"  baixando bases: {DRIVE_BASES}/ -> {destino}")
        resultado = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if resultado.returncode == 0:
            arquivos = list(destino.glob("*"))
            print(f"  ok: {len(arquivos)} base(s) baixada(s)")
            return destino
        print(f"  ERRO ao baixar bases (codigo {resultado.returncode}):")
        print(f"  {resultado.stderr.strip()}")
        return None
    except FileNotFoundError:
        print(f"  ERRO: rclone nao encontrado em '{exe}'")
        return None
    except Exception as e:  # noqa: BLE001
        print(f"  ERRO ao baixar bases: {e}")
        return None


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
