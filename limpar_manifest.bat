@echo off
setlocal enabledelayedexpansion
title Limpar Manifest ANAC

REM ============================================================
REM  Remove chaves do manifest.json para forcar recoleta no
REM  proximo run do robo (GitHub). Depois de limpar, faca
REM  COMMIT + PUSH do manifest.json pelo GitHub Desktop.
REM
REM  ASCII puro. Roda de dentro do repositorio.
REM ============================================================

REM Caminho do repositorio (ajuste se mudou de lugar).
set "REPO=C:\Backup\GitHub\Anac"
if not exist "%REPO%\robo\limpar_manifest.py" (
  REM tenta o caminho alternativo (repo movido para OneDrive)
  set "REPO=C:\Backup\OneDrive\Sync\GitHub\Anac"
)
if not exist "%REPO%\robo\limpar_manifest.py" (
  echo [ERRO] nao achei o repositorio. Ajuste REPO no topo do .bat.
  pause
  exit /b 1
)
cd /d "%REPO%"

:MENU
cls
echo ============================================================
echo    LIMPAR MANIFEST (forcar recoleta no proximo run)
echo ============================================================
echo   Repo: %REPO%
echo ============================================================
echo.
echo   1. Mes atual (movimentacao do mes + siros + tarifa DOM do ano)
echo   2. So Siros (voos futuros)
echo   3. Tudo de 2026 (todos os meses + siros + tarifas)
echo   4. Chave especifica (digitar)
echo   5. Listar o que tem no manifest
echo.
echo   0. Sair
echo.
set /p OP=Escolha uma opcao:

if "%OP%"=="1" ( python -m robo.limpar_manifest --preset mes-atual & goto FIM_OP )
if "%OP%"=="2" ( python -m robo.limpar_manifest --preset siros & goto FIM_OP )
if "%OP%"=="3" ( python -m robo.limpar_manifest --preset tudo-2026 & goto FIM_OP )
if "%OP%"=="4" goto CHAVE
if "%OP%"=="5" ( python -m robo.limpar_manifest --listar & pause & goto MENU )
if "%OP%"=="0" goto FIM
goto MENU

:CHAVE
echo.
echo Exemplos de chave: basica/202606  combinada/202606  siros/voos
echo                    tarifas/dom/2026  tarifas/int/2026
set /p K=Digite a chave:
python -m robo.limpar_manifest --chave "%K%"
goto FIM_OP

:FIM_OP
echo.
echo ============================================================
echo   IMPORTANTE: agora faca COMMIT + PUSH do manifest.json
echo   pelo GitHub Desktop, senao a mudanca nao vai para o robo.
echo ============================================================
pause
goto MENU

:FIM
endlocal
exit /b 0
