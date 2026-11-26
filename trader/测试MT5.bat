@echo off
chcp 65001 >nul
cd /d "%~dp0"
"C:\Users\26217\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" -X utf8 test_mt5.py
echo.
pause
