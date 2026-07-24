# ANAC — coleta automatizada de dados abertos

Robô que acompanha diariamente as bases públicas da ANAC e publica o
`.zip` **original** como asset de GitHub Release. Sem tratamento, sem
extração — o arquivo fica como a ANAC entregou.

## Fontes e sinais

Cada fonte expõe um sinal diferente de "isso mudou". O robô usa o melhor
disponível em cada uma, medido por sondagem do servidor real:

| Fonte | Sinal de mudança | Release |
|---|---|---|
| SIROS | data + tamanho na listagem de diretório | `siros-latest` |
| Microdados | "Atualizado em" da página + tamanho por arquivo | `microdados-{ano}` |
| Tarifas | coluna *Data Hora Arquivo*, por mês | `tarifas-{ano}` |

## Como decide baixar

**SIROS** — lê a listagem; se data e tamanho baterem com o registro, não baixa.

**Microdados** — a página serve de porteiro. Se o "Atualizado em" não mudou,
não varre nada. O avanço (procurar o mês seguinte) roda todo dia de qualquer
forma: são duas sondagens de um byte.

**Tarifas** — lê a tabela do ano e compara as datas mês a mês. Só clica em
"Baixar Marcados" se algum mês é novo ou teve a data alterada. Varredura
completa de todos os anos no dia 28.

Nada disso baixa arquivo para descobrir se mudou.

## Detalhes técnicos que valem saber

O Apache na frente do `gov.br` recusa **HEAD** com 403, mas aceita **GET
com Range**. Por isso `comum.propriedades()` pede o byte 0 e lê o
`Content-Range` — traz o tamanho exato por um byte de tráfego.

Esse servidor **não emite `Last-Modified`** para os arquivos. Logo, o único
indicador de republicação por arquivo nos microdados é o tamanho em bytes.

Os zips do DataSAS são gerados sob demanda e carregam o horário da geração,
então o SHA-256 muda a cada download mesmo sem dado novo. A comparação usa
`comum.impressao()`: nome, tamanho e CRC de cada membro, ordenados.

## Por que Release e não pasta

Os CSVs descompactados chegam a 166 MB, e o Git **rejeita** arquivos acima
de 100 MB. Releases aceitam 2 GB por asset e não contam no tamanho do
repositório. Comprimido, `basica202606` cai de 71 MB para 8 MB.

## Uso

```bash
pip install -r requirements.txt
python -m playwright install chromium

python -m robo.main --fonte datasas --explorar   # estrutura da página
python -m robo.main --local                      # baixa em _tmp/, não publica
python -m robo.main                              # coleta e publica
python -m robo.main --completo                   # força varredura do histórico
```

Publicar exige `GH_TOKEN`. No Actions vem pronto.

## Arquivos de acompanhamento

`ESTADO.md` — tabela legível: último período de cada fonte, quando a ANAC
publicou, quando o robô pegou. Reescrito a cada execução.

`manifest.json` — detalhe por período: tamanho, hash, impressão de conteúdo,
datas por mês das tarifas, situação. É o que o robô consulta para saber onde
parou.

O commit desses dois a cada execução também mantém o agendamento vivo — o
GitHub desativa cron após ~60 dias sem atividade no repositório.
