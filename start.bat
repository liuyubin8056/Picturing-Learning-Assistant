@echo off
chcp 936 >nul
title 智能拍照学习助手 - 启动
cd /d "%~dp0"

echo ============================================================
echo   智能拍照学习助手 - 启动服务
echo ============================================================
echo.

if not exist "backend\.venv\Scripts\python.exe" goto NOVENV
if exist "backend\.env" goto STARTALL
echo [提示] 未找到 backend\.env，AI 功能不可用（题库、组卷、统计不受影响）。
echo.

:STARTALL
echo 正在启动后端 http://127.0.0.1:8000 ...
start "后端服务" /D "%~dp0backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"

timeout /t 2 >nul

echo 正在启动前端 http://127.0.0.1:5173 ...
start "前端服务" /D "%~dp0frontend" cmd /k "npm run dev"

echo.
echo ============================================================
echo   服务已在新窗口启动
echo   前端      http://127.0.0.1:5173
echo   接口文档  http://127.0.0.1:8000/docs
echo ============================================================
echo 浏览器将在 8 秒后自动打开；若提示无法访问，稍等片刻再刷新。
timeout /t 8 >nul
start http://127.0.0.1:5173
exit /b 0

:NOVENV
echo [错误] 未找到后端虚拟环境。
echo 请先双击运行 setup.bat 完成安装。
echo.
pause
exit /b 1
