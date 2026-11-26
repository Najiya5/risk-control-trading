@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ============================================================
echo   推送到 GitHub: Najiya5/risk-control-trading
echo ============================================================
echo.

REM ── 1. 检查 git ──
where git >nul 2>nul
if errorlevel 1 (
    echo [X] 找不到 git，请先安装 Git for Windows
    pause
    exit /b 1
)

REM ── 2. 询问账号信息 ──
echo 请输入 GitHub 用户名（直接回车用 Najiya5）：
set /p GHUSER=
if "%GHUSER%"=="" set GHUSER=Najiya5

echo.
echo 请输入 GitHub 邮箱（用于 commit 记录）：
set /p GHEMAIL=

echo.
echo 请输入 Personal Access Token
echo   获取地址：https://github.com/settings/tokens
echo   权限勾选：repo（完整仓库权限）
echo.
set /p GHTOKEN=

if "%GHTOKEN%"=="" (
    echo [X] Token 不能为空
    pause
    exit /b 1
)

REM ── 3. 初始化仓库 ──
echo.
echo [1/5] 初始化 git 仓库...
if not exist ".git" (
    git init -b main >nul
    echo      已创建
) else (
    echo      已存在
)

git config user.name "%GHUSER%"
if not "%GHEMAIL%"=="" git config user.email "%GHEMAIL%"

REM ── 4. 添加文件 ──
echo.
echo [2/5] 添加文件...
git add -A
echo      完成

echo.
echo [3/5] 检查将要上传的文件...
echo ------------------------------------------------------------
git status --short
echo ------------------------------------------------------------
echo.

REM ── 5. 安全检查 ──
echo [4/5] 安全检查...
findstr /S /I /C:"password" /C:"api_key" config.example.json >nul 2>nul
if exist "config.json" (
    echo.
    echo [!!] 警告：目录里有 config.json（含你的账号密码）
    echo      它已被 .gitignore 排除，不会上传
    echo.
)

REM ── 6. 提交并推送 ──
echo.
echo [5/5] 提交并推送...
git commit -m "风控系统初始版本：指标 / 风控 / 执行 / 审计" 2>nul
if errorlevel 1 (
    echo      没有新改动，跳过提交
)

git remote remove origin >nul 2>nul
git remote add origin https://%GHUSER%:%GHTOKEN%@github.com/%GHUSER%/risk-control-trading.git

echo.
echo      正在推送...
git push -u origin main

if errorlevel 1 (
    echo.
    echo ============================================================
    echo   [X] 推送失败
    echo.
    echo   常见原因：
    echo     1. Token 错误或已过期
    echo     2. Token 权限不够（需要 repo 权限）
    echo     3. 仓库名不对
    echo     4. 网络问题（国内访问 GitHub 可能需要代理）
    echo.
    echo   如果仓库里已有内容（比如自动创建的 README），试试：
    echo     git pull origin main --allow-unrelated-histories
    echo     git push -u origin main
    echo ============================================================
) else (
    echo.
    echo ============================================================
    echo   [OK] 推送成功
    echo.
    echo   地址：https://github.com/%GHUSER%/risk-control-trading
    echo.
    echo   提示：这个 bat 文件里临时写入过 token，
    echo         可以用下面命令清除：
    echo         git remote set-url origin https://github.com/%GHUSER%/risk-control-trading.git
    echo ============================================================
)

echo.
pause
