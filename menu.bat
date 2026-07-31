@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Processador ANAC

REM ============================================================
REM  CAMINHOS -- ajuste aqui se algo mudar de lugar
REM ============================================================

REM Repositorio (onde estao os modulos Python: pasta 'robo')
set "REPO=C:\Users\pedro\GitHub\Anac"

REM OneDrive Corporativo (destino final, "a verdade")
set "CORP=C:\Backup\FRAPORT BRASIL S.A AEROPORTO DE PORTO ALEGRE\BI Operações - BI"
set "CORP_ANAC=%CORP%\Anac"
set "BASES=%CORP%\Bases"

REM OneDrive Pessoal (espelho do Google Drive via rclone)
set "PESSOAL=C:\Backup\OneDrive\Sync\Fraport"
set "PESSOAL_ANAC=%PESSOAL%\Anac"
set "PESSOAL_BASES=%PESSOAL%\Bases"

REM Subpastas derivadas
set "MOV_RAW=%CORP_ANAC%\Movimentacao\Raw"
set "MOV_PROC=%CORP_ANAC%\Movimentacao\Processado"
set "TKT_RAW=%CORP_ANAC%\Ticket\Raw"
set "TKT_PROC=%CORP_ANAC%\Ticket\Processado"
set "SIROS_RAW=%CORP_ANAC%\Siros\Raw"
set "SIROS_PROC=%CORP_ANAC%\Siros\Processado"
set "HIST_ANUAL=%CORP_ANAC%\Historico\Anual"
set "HIST_AGRUP=%CORP_ANAC%\Historico\Agrupado"

cd /d "%REPO%"

:MENU
cls
echo ============================================================
echo    PROCESSADOR ANAC
echo ============================================================
echo.
echo   --- Fluxo mensal ---
echo   1. Processar Movimentacao (mes)
echo   2. Processar Ticket DOM (mes)
echo   3. Processar Ticket INT (mes)
echo   4. Agrupar Ticket DOM+INT (mes)
echo   5. Mesclar Ticket na Movimentacao + flip (mes)
echo   6. Processar Siros (voos futuros)
echo.
echo   --- Combos ---
echo   7. Reprocessar MES completo (mov + ticket + mescla)
echo   8. Reprocessar ANO completo (12 meses + fechar)
echo.
echo   --- Fechamento e historico ---
echo   9. Fechar ano (12 finais -^> AAAA.csv)
echo  10. Gerar stack multi-ano (Agrupado)
echo.
echo   --- Manutencao ---
echo  11. Mover Pessoal -^> Corp + sincronizar Bases
echo  12. Atualizar cotacao do dolar (IPEA)
echo.
echo   0. Sair
echo.
set /p OP=Escolha uma opcao:

if "%OP%"=="1" goto MOV
if "%OP%"=="2" goto TKT_DOM
if "%OP%"=="3" goto TKT_INT
if "%OP%"=="4" goto AGRUPA
if "%OP%"=="5" goto MESCLA
if "%OP%"=="6" goto SIROS
if "%OP%"=="7" goto COMBO_MES
if "%OP%"=="8" goto COMBO_ANO
if "%OP%"=="9" goto FECHA
if "%OP%"=="10" goto STACK
if "%OP%"=="11" goto MOVER
if "%OP%"=="12" goto DOLAR
if "%OP%"=="0" goto FIM
goto MENU

REM ------------------------------------------------------------
:MOV
set /p P=Periodo (AAAA-MM):
python -m robo.processa_mes %P% --brutos "%MOV_RAW%" --aircrafts "%BASES%\Aircraft.xlsx" --saida "%MOV_PROC%"
pause
goto MENU

REM ------------------------------------------------------------
:TKT_DOM
set /p P=Periodo (AAAA-MM):
set "AAAA=%P:~0,4%"
set "MM=%P:~5,2%"
set "ARQ=%TKT_RAW%\%AAAA%%MM%.CSV"
if not exist "%ARQ%" (
  echo [!] Arquivo DOM nao encontrado: %ARQ%
  pause
  goto MENU
)
python -m robo.processa_ticket "%ARQ%" --saida "%TKT_PROC%" --tipo dom
pause
goto MENU

REM ------------------------------------------------------------
:TKT_INT
set /p P=Periodo (AAAA-MM):
set "ARQ=%TKT_RAW%\INTERNACIONAL_%P%.CSV"
if not exist "%ARQ%" (
  echo [!] Arquivo INT nao encontrado: %ARQ%
  pause
  goto MENU
)
python -m robo.processa_ticket "%ARQ%" --saida "%TKT_PROC%" --bases "%BASES%" --tipo int
pause
goto MENU

REM ------------------------------------------------------------
:AGRUPA
set /p P=Periodo (AAAA-MM):
python -m robo.agrupa_ticket %P% --pasta "%TKT_PROC%"
pause
goto MENU

REM ------------------------------------------------------------
:MESCLA
set /p P=Periodo (AAAA-MM):
set "TKTFILE=%TKT_PROC%\ticket_%P%.csv"
set "TKTARG="
if exist "%TKTFILE%" set "TKTARG=--ticket "%TKTFILE%""
python -m robo.mescla_final %P% --mov "%MOV_PROC%\anac_%P%.csv" %TKTARG% --saida "%MOV_PROC%"
pause
goto MENU

REM ------------------------------------------------------------
:SIROS
python -m robo.processa_siros "%SIROS_RAW%\voos.csv" --saida "%SIROS_PROC%" --bases "%BASES%"
pause
goto MENU

REM ------------------------------------------------------------
:COMBO_MES
set /p P=Periodo (AAAA-MM):
call :RUN_MES %P%
pause
goto MENU

REM sub-rotina: processa um mes completo. %1 = AAAA-MM
:RUN_MES
set "PER=%~1"
set "AAAA=%PER:~0,4%"
set "MM=%PER:~5,2%"
echo.
echo === [%PER%] Movimentacao ===
python -m robo.processa_mes %PER% --brutos "%MOV_RAW%" --aircrafts "%BASES%\Aircraft.xlsx" --saida "%MOV_PROC%"
echo.
echo === [%PER%] Ticket DOM ===
if exist "%TKT_RAW%\%AAAA%%MM%.CSV" (
  python -m robo.processa_ticket "%TKT_RAW%\%AAAA%%MM%.CSV" --saida "%TKT_PROC%" --tipo dom
) else ( echo   (sem DOM) )
echo.
echo === [%PER%] Ticket INT ===
if exist "%TKT_RAW%\INTERNACIONAL_%PER%.CSV" (
  python -m robo.processa_ticket "%TKT_RAW%\INTERNACIONAL_%PER%.CSV" --saida "%TKT_PROC%" --bases "%BASES%" --tipo int
) else ( echo   (sem INT) )
echo.
echo === [%PER%] Agrupar Ticket ===
python -m robo.agrupa_ticket %PER% --pasta "%TKT_PROC%"
echo.
echo === [%PER%] Mesclar final ===
set "TKTFILE=%TKT_PROC%\ticket_%PER%.csv"
set "TKTARG="
if exist "%TKTFILE%" set "TKTARG=--ticket "%TKTFILE%""
python -m robo.mescla_final %PER% --mov "%MOV_PROC%\anac_%PER%.csv" %TKTARG% --saida "%MOV_PROC%"
exit /b

REM ------------------------------------------------------------
:COMBO_ANO
set /p AAAA=Ano (AAAA):
for %%M in (01 02 03 04 05 06 07 08 09 10 11 12) do (
  echo.
  echo ############# %AAAA%-%%M #############
  call :RUN_MES %AAAA%-%%M
)
echo.
echo === Fechando ano %AAAA% ===
python -m robo.fecha_ano --ano %AAAA% --finais "%MOV_PROC%" --saida "%HIST_ANUAL%"
pause
goto MENU

REM ------------------------------------------------------------
:FECHA
set /p AAAA=Ano a fechar (AAAA):
python -m robo.fecha_ano --ano %AAAA% --finais "%MOV_PROC%" --saida "%HIST_ANUAL%"
pause
goto MENU

REM ------------------------------------------------------------
:STACK
set /p INI=Ano inicial:
set /p FIM=Ano final:
python -m robo.fecha_ano --stack %INI% %FIM% --anual "%HIST_ANUAL%" --saida "%HIST_AGRUP%"
pause
goto MENU

REM ------------------------------------------------------------
:MOVER
python -m robo.move_arquivos --pessoal "%PESSOAL_ANAC%" --corp "%CORP_ANAC%" --bases-corp "%BASES%" --bases-pessoal "%PESSOAL_BASES%"
pause
goto MENU

REM ------------------------------------------------------------
:DOLAR
python -m robo.dolar --atualizar --bases "%BASES%"
pause
goto MENU

REM ------------------------------------------------------------
:FIM
endlocal
exit /b 0
