@echo off
chcp 936 >nul
title 智能拍照学习助手 - 环境安装
cd /d "%~dp0"

echo ============================================================
echo   智能拍照学习助手 - 一键安装
echo ============================================================
echo.

echo [1/5] 检查 Python ...
python --version >nul 2>&1
if errorlevel 1 goto NOPYTHON
python --version
echo.

echo [2/5] 创建后端虚拟环境 ...
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

echo [3/5] 安装后端依赖（可能需要几分钟）...
backend\.venv\Scripts\python.exe -m pip install --upgrade pip -q
backend\.venv\Scripts\pip.exe install -r backend\requirements.txt
if errorlevel 1 goto PIPFAIL
echo.

echo [4/5] 安装前端依赖 ...
where npm >nul 2>&1
if errorlevel 1 goto NONPM
pushd frontend
call npm install
popd
goto ENVFILE

:NONPM
echo   [警告] 未检测到 Node.js，跳过前端依赖。
echo   请安装 Node.js 18+ 后手动执行：cd frontend 然后 npm install
goto ENVFILE

:ENVFILE
echo.
echo [5/5] 准备环境变量文件 ...
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
