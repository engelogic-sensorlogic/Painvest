@echo off
REM Envia o projeto (com o historico de commits) para o GitHub
REM Repositorio: https://github.com/engelogic-sensorlogic/Painvest.git
cd /d "%~dp0"
git remote get-url origin >nul 2>&1 || git remote add origin https://github.com/engelogic-sensorlogic/Painvest.git
git branch -M main
git push -u origin main
pause
