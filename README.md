# Robô de coleta ANAC

Coleta diária e automática de dados abertos da ANAC. Baixa os arquivos
novos de cada fonte, extrai o CSV/TXT de dentro do ZIP e envia para uma
pasta no Google Drive. Roda sozinho no GitHub Actions.

## O que ele coleta

| Fonte | Conteúdo | Pasta no Drive |
|---|---|---|
| Microdados básica | Movimentação mensal | `Fraport/Anac/Movimentacao` |
| Microdados combinada | Movimentação mensal | `Fraport/Anac/Movimentacao` |
| Tarifas DOM/INT | Tarifas aéreas mensais | `Fraport/Anac/Ticket` |
| SIROS | Voos futuros (diário) | `Fraport/Anac/Siros` |

Microdados e tarifas **acumulam** (cada mês vira um arquivo). SIROS
**substitui** (sempre o mais recente).

## Como decide o que baixar

Nunca baixa o que já pegou. Cada fonte tem seu sinal de novidade:

- **Microdados** — lê o inventário completo da página (um link por mês) e
  baixa só os meses ausentes. A data "Atualizado em" da página funciona
  como porteiro: se não mudou, não reconfere tamanhos.
- **Tarifas** — lê a tabela com a data de publicação de cada mês e baixa
  só o que é novo ou mudou de data.
- **SIROS** — compara data e tamanho da listagem antes de baixar.

## Destino: Google Drive via rclone

Os arquivos vão para o Drive pelo `rclone`. A credencial fica no secret
`RCLONE_CONFIG_GDRIVE` do repositório. No PC, o rclone é procurado em
`C:\Backup\Rclone\rclone.exe`; no Actions, no PATH do sistema.

## Rodar

```
python -m robo.main                    # coleta tudo e envia ao Drive
python -m robo.main --fonte siros      # só uma fonte
python -m robo.main --sem-drive        # extrai mas não envia (teste)
python -m robo.main --completo         # reconfere todo o histórico
python -m robo.main --backfill         # baixa todo o inventário (2000+)
python -m robo.main --explorar         # inspeciona a página do DataSAS
```

## Estado

- `manifest.json` — o que o robô já pegou (ele lê para saber onde parou)
- `ESTADO.md` — retrato legível da última coleta

Se uma fonte falhar, o robô registra, segue com as demais e termina com
erro — o que dispara a notificação automática de falha do GitHub.

## Agendamento

Cron diário às 09:00 UTC (06:00 Brasília). No dia 28, varredura completa
das tarifas. O commit de `manifest.json` e `ESTADO.md` a cada execução
mantém o agendamento ativo (o GitHub desliga cron após ~60 dias sem
atividade).
