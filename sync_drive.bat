@echo off
setlocal enabledelayedexpansion
title Sync ANAC (Drive -> OneDrive corp)

REM ============================================================
REM  SINCRONIZACAO Drive publico -> OneDrive corporativo
REM
REM  Le o links.csv (inventario publico gerado pelo robo no
REM  GitHub) e baixa cada arquivo via curl para a pasta corp,
REM  espelhando a estrutura. NAO faz login no Google: usa so os
REM  links publicos de download.
REM
REM  ASCII puro; a pasta com acento e resolvida por curinga.
REM  Agende no Agendador de Tarefas do Windows para rodar diario.
REM ============================================================

REM URL publica FIXA do links.csv (raiz de Sync/Fraport/Anac).
REM >>> AJUSTE: cole aqui o link de download do links.csv <<<
set "LINKS_URL=COLE_AQUI_O_LINK_DO_links.csv"

REM Base corporativa (pasta com acento resolvida por curinga).
set "BASE_FRAPORT=C:\Backup\FRAPORT BRASIL S.A AEROPORTO DE PORTO ALEGRE"
set "CORP="
for /d %%D in ("%BASE_FRAPORT%\BI Opera*es - BI") do (
  if exist "%%~fD\Anac\" set "CORP=%%~fD"
)
if not defined CORP (
  for /d %%D in ("%BASE_FRAPORT%\BI Opera*es - BI") do set "CORP=%%~fD"
)
if not defined CORP (
  echo [ERRO] pasta corp nao encontrada em %BASE_FRAPORT%
  exit /b 1
)
set "DESTINO=%CORP%\Anac"

REM Pasta temporaria de trabalho.
set "TMP=%TEMP%\sync_anac"
if not exist "%TMP%" mkdir "%TMP%"
set "LISTA=%TMP%\links.csv"
set "LOG=%TMP%\sync_%DATE:~-4%%DATE:~3,2%%DATE:~0,2%.log"

echo ============================================================ >> "%LOG%"
echo Sync iniciado em %DATE% %TIME% >> "%LOG%"
echo Destino: %DESTINO% >> "%LOG%"

REM 1. Baixa o links.csv
echo Baixando links.csv...
curl.exe -L -s -o "%LISTA%" "%LINKS_URL%"
if not exist "%LISTA%" (
  echo [ERRO] nao baixou o links.csv >> "%LOG%"
  echo [ERRO] nao baixou o links.csv
  exit /b 1
)

REM 2. Para cada linha (pula cabecalho), baixa o arquivo.
REM    Usa o ID (token 3) e monta a URL inline no curl, para que os
REM    caracteres & da URL fiquem fixos no texto (nao numa variavel,
REM    onde o & seria interpretado como separador de comando).
set "TOTAL=0"
set "OK=0"
set "FALHA=0"
for /f "usebackq skip=1 tokens=1,3 delims=;" %%A in ("%LISTA%") do (
  set /a TOTAL+=1
  set "CAMINHO=%%A"
  set "GID=%%B"
  REM troca / por \ no caminho relativo
  set "REL=!CAMINHO:/=\!"
  set "ALVO=%DESTINO%\!REL!"
  REM cria a subpasta do arquivo
  for %%F in ("!ALVO!") do set "PASTA=%%~dpF"
  if not exist "!PASTA!" mkdir "!PASTA!" 2>nul
  REM baixa (sobrescreve sempre). URL montada inline: os & ficam literais.
  curl.exe -L -s -o "!ALVO!" "https://drive.usercontent.google.com/download?id=!GID!&export=download&confirm=t"
  if exist "!ALVO!" (
    set /a OK+=1
    echo   OK    !REL! >> "%LOG%"
  ) else (
    set /a FALHA+=1
    echo   FALHA !REL! >> "%LOG%"
  )
)

echo. >> "%LOG%"
echo Concluido: !OK! de !TOTAL! baixado(s), !FALHA! falha(s) >> "%LOG%"
echo Concluido: !OK! de !TOTAL! baixado(s), !FALHA! falha(s)
echo Log: %LOG%

endlocal
exit /b 0
