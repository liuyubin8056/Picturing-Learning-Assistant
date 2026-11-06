@echo off
chcp 936 >nul
title 智能拍照学习助手 - 环境安装
cd /d "%~dp0"

echo ============================================================
echo   智能拍照学习助手 - 一键安装
echo ============================================================
echo.

echo [1/6] 检查 Python ...
where python >nul 2>&1
if errorlevel 1 goto NOPYTHON
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYV=%%v
echo   Python %PYV%
for /f "tokens=1,2 delims=." %%a in ("%PYV%") do set PYMAJOR=%%a& set PYMINOR=%%b
if %PYMAJOR% NEQ 3 goto PYOLD
if %PYMINOR% LSS 11 goto PYOLD
goto PYOK

:PYOLD
echo   [警告] 建议使用 Python 3.11 及以上，当前版本可能导致依赖安装失败。
echo   仍将继续安装，若报错请升级 Python 后重试。
:PYOK
echo.

echo [2/6] 检查 Node.js ...
where npm >nul 2>&1
if errorlevel 1 goto NONPM
for /f "delims=" %%v in ('node -v 2^>nul') do set NODEV=%%v
set NODEV=%NODEV:v=%
echo   Node %NODEV%
for /f "tokens=1 delims=." %%a in ("%NODEV%") do set NODE_MAJOR=%%a
if %NODE_MAJOR% LSS 18 echo   [警告] Vite 6 需要 Node 18 及以上，前端可能启动失败。
goto NODEOK
:NONPM
echo   [警告] 未检测到 Node.js / npm，前端将无法启动。
echo   请安装 Node.js 18+ (https://nodejs.org) 后重跑本脚本。
:NODEOK
echo.

echo [3/6] 创建后端虚拟环境 ...
if exist "backend\.venv\Scripts\python.exe" goto VENVOK
python -m venv backend\.venv
if errorlevel 1 goto VENVFAIL
echo   已创建 backend\.venv
goto VENVOK

:VENVFAIL
echo   [错误] 虚拟环境创建失败
pause
exit /b 1

:VENVOK
echo.

echo [4/6] 安装后端依赖（可能需要几分钟）...
backend\.venv\Scripts\python.exe -m pip install --upgrade pip -q
backend\.venv\Scripts\pip.exe install -r backend\requirements.txt
if errorlevel 1 goto PIPFAIL
echo.

echo [5/6] 安装前端依赖 ...
where npm >nul 2>&1
if errorlevel 1 goto ENVFILE
pushd frontend
call npm install
popd
if errorlevel 1 echo   [警告] 前端依赖安装失败，可稍后手动 cd frontend 后执行 npm install
goto ENVFILE

:ENVFILE
echo.
echo [6/6] 准备环境变量文件 ...
if exist "backend\.env" goto DONE
if not exist "backend\.env.example" goto NOEXAMPLE
copy "backend\.env.example" "backend\.env" >nul
echo   已生成 backend\.env
echo   >>> 请打开 backend\.env，把 DEEPSEEK_API_KEY 填成你自己的密钥 <<<
goto DONE

:NOEXAMPLE
echo   [警告] 未找到 backend\.env.example，请手动创建 backend\.env
goto DONE

:DONE
echo.
echo ============================================================
echo   安装完成
echo ============================================================
echo   下一步：
echo     1. 编辑 backend\.env 填入 DEEPSEEK_API_KEY
echo     2. 双击 start.bat 启动前后端
echo   若启动失败，双击 check.bat 做环境自检并把结果发给队友
echo ============================================================
pause
exit /b 0

:PIPFAIL
echo.
echo   [错误] 后端依赖安装失败。
echo   网络较慢时可换国内镜像重试：
echo   backend\.venv\Scripts\pip.exe install -r backend\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
echo.
pause
exit /b 1

:NOPYTHON
echo   [错误] 未检测到 Python。
echo   请安装 Python 3.11 或更高版本，安装时勾选 Add Python to PATH。
echo.
pause
exit /b 1
