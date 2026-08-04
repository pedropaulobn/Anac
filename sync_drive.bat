@echo off
setlocal enabledelayedexpansion
title Sync ANAC (Drive para OneDrive corp)

REM ============================================================
REM  SINCRONIZACAO Drive publico -> OneDrive corporativo
REM
REM  Le o links.csv (inventario publico gerado pelo robo no
REM  GitHub) e baixa cada arquivo via curl para a pasta corp,
REM  espelhando a estrutura. NAO faz login no Google: usa so os
REM  links publicos de download.
REM
REM  ASCII puro; pasta com acento resolvida por curinga.
REM  Agende no Agendador de Tarefas do Windows para rodar diario.
REM ============================================================

REM URL publica FIXA do links.csv. Formato de download direto:
REM https://drive.usercontent.google.com/download?id=SEU_ID&export=download&confirm=t
REM >>> AJUSTE: cole so o ID do links.csv aqui <<<
set "LINKS_ID=152zUEMQwbwkAMrkTE7EmxZvEnAFRrS_6"

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
  echo Pressione uma tecla para sair.
  pause >nul
  exit /b 1
)
set "DESTINO=%CORP%\Anac"
echo Destino: %DESTINO%

REM Pasta temporaria de trabalho (nome de log fixo, sem depender de %DATE%).
set "WORK=%TEMP%\sync_anac"
if not exist "%WORK%" mkdir "%WORK%"
set "LISTA=%WORK%\links.csv"
set "LOG=%WORK%\sync.log"

echo ============================================================> "%LOG%"
echo Sync iniciado>> "%LOG%"
echo Destino: %DESTINO%>> "%LOG%"

REM 1. Baixa o links.csv (URL montada inline; & fica literal)
echo Baixando links.csv...
if exist "%LISTA%" del "%LISTA%"
curl.exe -L -s -o "%LISTA%" "https://drive.usercontent.google.com/download?id=%LINKS_ID%&export=download&confirm=t"
if not exist "%LISTA%" (
  echo [ERRO] nao baixou o links.csv. Verifique o LINKS_ID e a rede.
  echo [ERRO] nao baixou o links.csv>> "%LOG%"
  pause >nul
  exit /b 1
)
echo links.csv baixado.

REM 2. Para cada linha (pula cabecalho): baixa via ID (token 3).
set "TOTAL=0"
set "OK=0"
set "FALHA=0"
for /f "usebackq skip=1 tokens=1,3 delims=;" %%A in ("%LISTA%") do (
  set /a TOTAL+=1
  set "CAMINHO=%%A"
  set "GID=%%B"
  set "REL=!CAMINHO:/=\!"
  set "ALVO=%DESTINO%\!REL!"
  for %%F in ("!ALVO!") do set "PASTA=%%~dpF"
  if not exist "!PASTA!" mkdir "!PASTA!" 2>nul
  echo   baixando: !REL!
  curl.exe -L -s -o "!ALVO!" "https://drive.usercontent.google.com/download?id=!GID!&export=download&confirm=t"
  if exist "!ALVO!" (
    set /a OK+=1
    echo   OK    !REL!>> "%LOG%"
  ) else (
    set /a FALHA+=1
    echo   FALHA !REL!>> "%LOG%"
  )
)

echo.
echo Concluido: !OK! de !TOTAL! baixado^(s^), !FALHA! falha^(s^)
echo Concluido: !OK! de !TOTAL! baixado, !FALHA! falha>> "%LOG%"
echo Log: %LOG%
echo.
echo Pressione uma tecla para fechar.
pause >nul

endlocal
exit /b 0
