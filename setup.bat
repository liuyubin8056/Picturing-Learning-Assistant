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
if errorlevel 1 (
    echo   [错误] 未检测到 Python。
    echo   请先安装 Python 3.11 或更高版本，并在安装时勾选 "Add to PATH"。
    echo.
    pause
    exit /b 1
)
python --version
echo.

echo [2/5] 创建后端虚拟环境 ...
if not exist "backend\.venv\Scripts\python.exe" (
    python -m venv backend\.venv
    if errorlevel 1 (
        echo   [错误] 虚拟环境创建失败
        pause
        exit /b 1
    )
    echo   已创建 backend\.venv
) else (
    echo   已存在，跳过
)
echo.

echo [3/5] 安装后端依赖（可能需要几分钟）...
backend\.venv\Scripts\python.exe -m pip install --upgrade pip -q
backend\.venv\Scripts\pip.exe install -r backend\requirements.txt
if errorlevel 1 (
    echo.
    echo   [错误] 依赖安装失败。
    echo   如果网络较慢，可换国内镜像重试：
    echo   backend\.venv\Scripts\pip.exe install -r backend\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    pause
    exit /b 1
)
echo.

echo [4/5] 安装前端依赖 ...
where npm >nul 2>&1
if errorlevel 1 (
    echo   [警告] 未检测到 Node.js / npm，跳过前端依赖。
    echo          请安装 Node.js 18+ 后手动执行：cd frontend 然后 npm install
) else (
    pushd frontend
    call npm install
    popd
    if errorlevel 1 (
        echo   [警告] 前端依赖安装失败，请检查网络后重试
    )
)
echo.

echo [5/5] 准备环境变量文件 ...
if not exist "backend\.env" (
    if exist "backend\.env.example" (
        copy "backend\.env.example" "backend\.env" >nul
        echo   已生成 backend\.env
        echo   >>> 请打开 backend\.env，把 DEEPSEEK_API_KEY 填成你自己的密钥 <<<
    ) else (
        echo   [警告] 未找到 backend\.env.example，请手动创建 backend\.env
    )
) else (
    echo   backend\.env 已存在，跳过
)
echo.

echo ============================================================
echo   安装完成
echo ============================================================
echo   下一步：
echo     1. 编辑 backend\.env，填入 DEEPSEEK_API_KEY
echo     2. 双击 start.bat 启动前后端
echo ============================================================
pause
