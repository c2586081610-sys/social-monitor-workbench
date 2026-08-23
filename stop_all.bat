@echo off
rem ============================================================
rem  stop_all.bat - 停止 start_all.bat 启动的全部服务
rem  策略（三层兜底）:
rem   1) 按窗口标题 taskkill（后端/前端/监控窗口）
rem   2) 按监听端口 8000/5173 查 PID 强杀
rem   3) 按命令行匹配监控层 python 进程
rem ============================================================
setlocal
cd /d "%~dp0"

echo [1/3] 按窗口标题关闭服务窗口...
taskkill /FI "WINDOWTITLE eq backend-8000*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq frontend-5173*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq monitor*" /T /F >nul 2>&1

echo [2/3] 按监听端口清理残留进程...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /PID %%a /T /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do taskkill /PID %%a /T /F >nul 2>&1

echo [3/3] 按命令行匹配清理监控层进程...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'monitor[\\/]main\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

echo.
echo 已执行停止操作。可用以下命令确认端口已释放:
echo   netstat -ano ^| findstr ":8000 :5173"
echo （无输出 = 已全部停止）
endlocal
