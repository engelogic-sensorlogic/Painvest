@echo off
REM ===================================================================
REM  Painvest - Build completo: ambiente, testes, executavel e instalador
REM  Requisitos: Python 3.11+ no PATH e Inno Setup 7 instalado
REM  Uso: build.bat [versao]     ex.: build.bat 1.0.1
REM ===================================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "VERSAO=%~1"
if "%VERSAO%"=="" set "VERSAO=1.0.1"

echo.
echo [1/6] Ambiente virtual...
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv || goto :erro
)
call ".venv\Scripts\activate.bat" || goto :erro

echo [2/6] Dependencias...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt pyinstaller pytest || goto :erro

echo [3/6] Testes automaticos...
python -m pytest -q tests || goto :erro

echo [4/6] Gerando executavel (PyInstaller)...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
pyinstaller --noconfirm --clean --name Painvest --noconsole ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --collect-all yfinance ^
  --collect-all curl_cffi ^
  --hidden-import waitress ^
  app.py || goto :erro

echo [5/6] Localizando Inno Setup 7...
set "ISCC="
for %%P in (
  "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
  "%ProgramFiles%\Inno Setup 7\ISCC.exe"
  "%LocalAppData%\Programs\Inno Setup 7\ISCC.exe"
) do if exist %%P set "ISCC=%%~P"
if not defined ISCC (
  for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do set "ISCC=%%I"
)
if not defined ISCC (
  echo ERRO: ISCC.exe do Inno Setup 7 nao encontrado. Ajuste o caminho neste build.bat.
  goto :erro
)
echo     %ISCC%

echo [6/6] Compilando instalador...
"%ISCC%" /DMyAppVersion=%VERSAO% "installer\Painvest.iss" || goto :erro

echo.
echo ===================================================================
echo  OK! Instalador: dist_installer\Painvest_Setup_%VERSAO%.exe
echo ===================================================================
endlocal
exit /b 0

:erro
echo.
echo *** BUILD FALHOU - veja as mensagens acima ***
endlocal
exit /b 1
