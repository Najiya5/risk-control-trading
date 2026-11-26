@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=C:\Users\26217\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
set "PYTHONIOENCODING=utf-8"

if /i "%~1"=="cli"      goto :cli
if /i "%~1"=="approve"  goto :approve
if /i "%~1"=="status"   goto :status
if /i "%~1"=="selftest" goto :selftest

start "" "%PY%" -X utf8 ui.py
exit /b 0

:cli
"%PY%" -X utf8 main.py
goto :end

:approve
"%PY%" -X utf8 approve.py
goto :end

:status
"%PY%" -X utf8 approve.py --status
goto :end

:selftest
"%PY%" -X utf8 selftest.py
goto :end

:end
echo.
pause
