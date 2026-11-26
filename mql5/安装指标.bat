@echo off
chcp 65001 >nul
setlocal

set SRC=%~dp0
set DST=%APPDATA%\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Indicators
set ME=C:\Program Files\MetaTrader 5\MetaEditor64.exe

echo ============================================
echo   安装 OsMA / ATRP 指标到 MT5
echo ============================================
echo 源目录: %SRC%
echo 目标:   %DST%
echo.

if not exist "%DST%" (
    echo [X] 找不到 MT5 的 Indicators 目录
    echo     请先打开 MT5 一次
    pause
    exit /b 1
)

echo [1] 复制指标文件...
copy /Y "%SRC%OsMA_Risk.mq5"   "%DST%\" >nul && echo     OK OsMA_Risk.mq5
copy /Y "%SRC%OsMA_Signal.mq5" "%DST%\" >nul && echo     OK OsMA_Signal.mq5
copy /Y "%SRC%ATRP_Risk.mq5"   "%DST%\" >nul && echo     OK ATRP_Risk.mq5
echo.

echo [2] 编译...
if not exist "%ME%" (
    echo     [!] 找不到 MetaEditor，跳过编译
    echo         请手动在 MT5 里 打开 MetaEditor 编译
) else (
    "%ME%" /compile:"%DST%\OsMA_Risk.mq5" /log:"%SRC%compile_OsMA_Risk.log"
    "%ME%" /compile:"%DST%\OsMA_Signal.mq5" /log:"%SRC%compile_OsMA_Signal.log"
    "%ME%" /compile:"%DST%\ATRP_Risk.mq5" /log:"%SRC%compile_ATRP_Risk.log"

    echo     --- OsMA_Risk ---
    type "%SRC%compile_OsMA_Risk.log" 2>nul
    echo     --- OsMA_Signal ---
    type "%SRC%compile_OsMA_Signal.log" 2>nul
    echo     --- ATRP_Risk ---
    type "%SRC%compile_ATRP_Risk.log" 2>nul
)
echo.

echo ============================================
echo   完成
echo.
echo   在 MT5 里的用法：
echo     1. 打开 XAUUSD 图表
echo     2. 顶部菜单 插入 - 指标 - 自定义
echo     3. 选 OsMA_Signal（副图）
echo     4. 选 ATRP_Risk（副图）
echo     5. 选 OsMA_Risk（主图，显示箭头）
echo ============================================
pause
