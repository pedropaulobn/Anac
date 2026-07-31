@echo off
setlocal enabledelayedexpansion
title Processador ANAC

REM ============================================================
REM  CAMINHOS -- ajuste aqui se algo mudar de lugar
REM  (arquivo salvo em ANSI/cp1252; NAO use chcp 65001 aqui,
REM   senao o acento em "Operacoes" quebra o parse do caminho)
REM ============================================================

set "REPO=C:\Backup\GitHub\Anac"
set "CORP=C:\Backup\FRAPORT BRASIL S.A AEROPORTO DE PORTO ALEGRE\BI Operações - BI"
set "CORP_ANAC=%CORP%\Anac"
set "BASES=%CORP%\Bases"

set "PESSOAL=C:\Backup\OneDrive\Sync\Fraport"
set "PESSOAL_ANAC=%PESSOAL%\Anac"
set "PESSOAL_BASES=%PESSOAL%\Bases"

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
echo   PRINCIPAL
echo   1. Processar TUDO que falta (detecta sozinho, ^>= 2026)
echo   2. Processar tudo de um ANO especifico
echo.
echo   AVULSO (um mes)
echo   3. Movimentacao (mes)
echo   4. Ticket DOM (mes)
echo   5. Ticket INT (mes)
echo   6. Agrupar Ticket DOM+INT (mes)
echo   7. Mesclar Ticket + flip (mes)
echo   8. Siros (voos futuros)
echo.
echo   FECHAMENTO E HISTORICO
echo   9. Fechar ano (12 finais -^> AAAA.csv)
echo  10. Gerar stack multi-ano (Agrupado)
echo.
echo   MANUTENCAO
echo  11. Mover Pessoal -^> Corp + sincronizar Bases
echo  12. Atualizar cotacao do dolar (IPEA)
echo.
echo   0. Sair
echo.
set /p OP=Escolha uma opcao:

if "%OP%"=="1" goto TUDO
if "%OP%"=="2" goto TUDO_ANO
if "%OP%"=="3" goto MOV
if "%OP%"=="4" goto TKT_DOM
if "%OP%"=="5" goto TKT_INT
if "%OP%"=="6" goto AGRUPA
if "%OP%"=="7" goto MESCLA
if "%OP%"=="8" goto SIROS
if "%OP%"=="9" goto FECHA
if "%OP%"=="10" goto STACK
if "%OP%"=="11" goto MOVER
if "%OP%"=="12" goto DOLAR
if "%OP%"=="0" goto FIM
goto MENU

:TUDO
echo.
echo Detectando e processando tudo que falta (^>= 2026)...
python -m robo.processa_tudo --corp "%CORP_ANAC%" --bases "%BASES%"
pause
goto MENU

:TUDO_ANO
set /p A=Ano (AAAA):
python -m robo.processa_tudo --corp "%CORP_ANAC%" --bases "%BASES%" --ano %A%
pause
goto MENU

:MOV
set /p P=Periodo (AAAA-MM):
python -m robo.processa_mes %P% --brutos "%MOV_RAW%" --aircrafts "%BASES%\Aircraft.xlsx" --saida "%MOV_PROC%"
pause
goto MENU

:TKT_DOM
set /p P=Periodo (AAAA-MM):
set "AAAA=%P:~0,4%"
set "MM=%P:~5,2%"
if not exist "%TKT_RAW%\%AAAA%%MM%.CSV" ( echo [!] nao encontrado: %TKT_RAW%\%AAAA%%MM%.CSV & pause & goto MENU )
python -m robo.processa_ticket "%TKT_RAW%\%AAAA%%MM%.CSV" --saida "%TKT_PROC%" --tipo dom
pause
goto MENU

:TKT_INT
set /p P=Periodo (AAAA-MM):
if not exist "%TKT_RAW%\INTERNACIONAL_%P%.CSV" ( echo [!] nao encontrado: %TKT_RAW%\INTERNACIONAL_%P%.CSV & pause & goto MENU )
python -m robo.processa_ticket "%TKT_RAW%\INTERNACIONAL_%P%.CSV" --saida "%TKT_PROC%" --bases "%BASES%" --tipo int
pause
goto MENU

:AGRUPA
set /p P=Periodo (AAAA-MM):
python -m robo.agrupa_ticket %P% --pasta "%TKT_PROC%"
pause
goto MENU

:MESCLA
set /p P=Periodo (AAAA-MM):
set "TKTARG="
if exist "%TKT_PROC%\ticket_%P%.csv" set "TKTARG=--ticket "%TKT_PROC%\ticket_%P%.csv""
python -m robo.mescla_final %P% --mov "%MOV_PROC%\anac_%P%.csv" %TKTARG% --saida "%MOV_PROC%"
pause
goto MENU

:SIROS
python -m robo.processa_siros "%SIROS_RAW%\voos.csv" --saida "%SIROS_PROC%" --bases "%BASES%"
pause
goto MENU

:FECHA
set /p A=Ano a fechar (AAAA):
python -m robo.fecha_ano --ano %A% --finais "%MOV_PROC%" --saida "%HIST_ANUAL%"
pause
goto MENU

:STACK
set /p INI=Ano inicial:
set /p FIM=Ano final:
python -m robo.fecha_ano --stack %INI% %FIM% --anual "%HIST_ANUAL%" --saida "%HIST_AGRUP%"
pause
goto MENU

:MOVER
python -m robo.move_arquivos --pessoal "%PESSOAL_ANAC%" --corp "%CORP_ANAC%" --bases-corp "%BASES%" --bases-pessoal "%PESSOAL_BASES%"
pause
goto MENU

:DOLAR
python -m robo.dolar --atualizar --bases "%BASES%"
pause
goto MENU

:FIM
endlocal
exit /b 0
