@echo off
chcp 936 >nul
title 智能拍照学习助手 - 环境自检
cd /d "%~dp0"

echo ============================================================
echo   环境自检
echo   （服务起不来时先跑这个，把结果截图发出来即可定位问题）
echo ============================================================
echo.

echo [1] Python
where python >nul 2>&1
if errorlevel 1 goto NOPY
python --version
goto PYOK
:NOPY
echo   X 未找到 python，请安装 Python 3.11+ 并勾选 Add to PATH
:PYOK
echo.

echo [2] Node.js
where node >nul 2>&1
if errorlevel 1 goto NONODE
for /f "delims=" %%v in ('node -v 2^>nul') do set NODEV=%%v
set NODEV=%NODEV:v=%
for /f "tokens=1 delims=." %%a in ("%NODEV%") do set NODE_MAJOR=%%a
echo   node %NODEV%
if %NODE_MAJOR% LSS 18 echo   X 版本过低：Vite 6 需要 Node 18 及以上，请升级
goto NODEOK
:NONODE
echo   X 未找到 node，请安装 Node.js 18+ (https://nodejs.org)
:NODEOK
echo.

echo [3] 后端环境
if exist "backend\.venv\Scripts\python.exe" goto VENVOK
echo   X 缺少 backend\.venv —— 请先运行 setup.bat
goto ENVCHK
:VENVOK
echo   OK 虚拟环境已存在
:ENVCHK
if exist "backend\.env" goto ENVOK
echo   ! 缺少 backend\.env —— AI 功能不可用（其余功能正常）
goto ENVDONE
:ENVOK
echo   OK backend\.env 已存在
:ENVDONE
echo.

echo [4] 前端依赖
if exist "frontend\node_modules" goto NMOK
echo   X 缺少 frontend\node_modules —— 请运行 setup.bat，或手动 cd frontend 后 npm install
goto NMDONE
:NMOK
echo   OK node_modules 已安装
:NMDONE
echo.

echo [5] 端口占用
netstat -an | findstr ":8000" | findstr "LISTENING" >nul
if errorlevel 1 echo   8000 空闲
if not errorlevel 1 echo   8000 已被占用（可能后端已在运行）
netstat -an | findstr ":5173" | findstr "LISTENING" >nul
if errorlevel 1 echo   5173 空闲
if not errorlevel 1 echo   5173 已被占用（可能前端已在运行）
echo.

echo [6] 数据库与题库
if exist "backend\dev.db" goto DBOK
echo   X 缺少 backend\dev.db
goto DBDONE
:DBOK
echo   OK dev.db 已存在
:DBDONE
if exist "backend\kb_images\problems" goto IMGOK
echo   X 缺少题目图片目录
goto IMGDONE
:IMGOK
echo   OK 题目图片目录已存在
:IMGDONE
echo.

echo ============================================================
echo   自检结束。若有 X 项，按提示处理后重试。
echo   若全部 OK 但仍无法访问，请截图「后端服务」「前端服务」
echo   两个窗口里的报错内容。
echo ============================================================
pause
