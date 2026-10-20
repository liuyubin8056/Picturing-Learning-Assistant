@echo off
chcp 936 >nul
title 智能拍照学习助手 - 启动
cd /d "%~dp0"

echo ============================================================
echo   智能拍照学习助手 - 启动服务
echo ============================================================
echo.

if not exist "backend\.venv\Scripts\python.exe" goto NOVENV
if exist "backend\.env" goto BACKSTART
echo [提示] 未找到 backend\.env，AI 功能不可用（题库、组卷、统计不受影响）。
echo.

:BACKSTART
echo 正在启动后端 ...
start "后端服务" /D "%~dp0backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"

echo 等待后端就绪（最多 40 秒）...
set /a W=0
:BACKWAIT
timeout /t 2 >nul
netstat -an | findstr ":8000" | findstr "LISTENING" >nul
if not errorlevel 1 goto BACKOK
set /a W+=1
if %W% lss 20 goto BACKWAIT
echo   [警告] 后端 40 秒内没有起来。
echo   请切换到「后端服务」窗口查看报错，常见原因：
echo     - 依赖没装好（重跑 setup.bat）
echo     - Python 版本低于 3.11
echo     - 8000 端口被占用
goto FRONTSTART

:BACKOK
echo   OK 后端已就绪 http://127.0.0.1:8000
echo.

:FRONTSTART
echo 正在启动前端 ...
start "前端服务" /D "%~dp0frontend" cmd /k "npm run dev"

echo 等待前端就绪（最多 60 秒）...
set /a W=0
:FRONTWAIT
timeout /t 2 >nul
netstat -an | findstr ":5173" | findstr "LISTENING" >nul
if not errorlevel 1 goto FRONTOK
set /a W+=1
if %W% lss 30 goto FRONTWAIT
echo   [警告] 前端 60 秒内没有起来。
echo   请切换到「前端服务」窗口查看报错，常见原因：
echo     - 没有 node_modules（在 frontend 目录执行 npm install）
echo     - Node 版本低于 18（Vite 6 要求）
echo     - 5173 端口被占用
goto OPENBROWSER

:FRONTOK
echo   OK 前端已就绪 http://127.0.0.1:5173

:OPENBROWSER
echo.
echo ============================================================
echo   前端      http://127.0.0.1:5173
echo   接口文档  http://127.0.0.1:8000/docs
echo ============================================================
echo 服务没起来？关掉本窗口，双击 check.bat 做环境自检。
echo.
timeout /t 3 >nul
start http://127.0.0.1:5173
exit /b 0

:NOVENV
echo [错误] 未找到后端虚拟环境。
echo 请先双击运行 setup.bat 完成安装。
echo.
pause
exit /b 1
