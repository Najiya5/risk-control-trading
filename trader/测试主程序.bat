@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
echo ==========================================
echo   风控程序 - 无界面模式（命令行）
echo   Ctrl+C 停止
echo ==========================================
echo.
"C:\Users\26217\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" -X utf8 main.py
echo.
echo 程序已退出
pause
