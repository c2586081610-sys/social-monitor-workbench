@echo off
rem ============================================================
rem  start_all.bat - 一键启动博主监控工作台
rem  依次启动: 后端(uvicorn :8000) + 前端(vite preview :5173) + 监控层(monitor/main.py)
rem  停止: 运行 stop_all.bat
rem  提示: 重复启动前请先 stop_all.bat，避免端口冲突。
rem  说明: 各启动路径当前无空格，故命令无需嵌套引号；
rem        若环境迁移到含空格路径，请在引号外改用 "" 双引号转义。
rem ============================================================
setlocal
cd /d "%~dp0"
set "ROOT=%CD%"

rem ---- 固定运行时路径（若环境迁移只需改这三行） ----
set "PYTHON=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
set "NODE=C:\Users\Administrator\.workbuddy\binaries\node\versions\22.22.2\node.exe"
set "PYTHON_SCRIPTS=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\Scripts"

rem ---- 将下载工具目录 + ffmpeg + Python Scripts 加入 PATH（yutto/ffmpeg 依赖） ----
set "PATH=%ROOT%\tools\bin;%ROOT%\tools\ffmpeg-exe;%PYTHON_SCRIPTS%;%PATH%"

rem ---- 双保险：把 backend\.env 注入当前会话（config.py 的 load_dotenv 之外的兜底） ----
rem      仅补缺失变量；以 # 开头的行为注释跳过；KEY=VALUE 解析，VALUE 含空格/逗号均保留
if exist "%ROOT%\backend\.env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%ROOT%\backend\.env") do (
        if not "%%a"=="" set "%%a=%%b"
    )
)

rem ---- 前置检查：关键二进制存在 ----
if not exist "%PYTHON%" (
    echo [ERROR] Python not found: %PYTHON%
    pause
    exit /b 1
)
if not exist "%ROOT%\frontend\dist\index.html" (
    echo [WARN] frontend\dist 未构建，请先执行: cd frontend ^&^& npm run build
)

echo ============================================================
echo  启动博主监控工作台
echo   1/3 后端   http://127.0.0.1:8000/docs
echo   2/3 前端   http://127.0.0.1:5173
echo   3/3 监控层 monitor/main.py
echo ============================================================

rem ---- 1. 后端 (uvicorn :8000) ----
start "backend-8000" /min cmd /k "cd /d %ROOT%\backend && %PYTHON% -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

rem ---- 2. 前端 (vite preview :5173) ----
start "frontend-5173" /min cmd /k "cd /d %ROOT%\frontend && %NODE% node_modules\vite\bin\vite.js preview --port 5173 --host 127.0.0.1"

rem ---- 3. 监控层 (monitor/main.py) ----
start "monitor" /min cmd /k "cd /d %ROOT% && %PYTHON% monitor\main.py"

echo.
echo 已在独立最小化窗口启动 3 个服务。等待数秒后访问:
echo   后端: http://127.0.0.1:8000/docs
echo   前端: http://127.0.0.1:5173
echo   停止全部服务: 双击 stop_all.bat
echo.
endlocal
