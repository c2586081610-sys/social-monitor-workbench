@echo off
REM ============================================================
REM  以 CDP 模式启动「日常 Edge」（带远程调试端口，供抓取脚本连接）
REM  用法：先完全关闭日常 Edge（重要！），再双击本脚本
REM  启动后：日常 Edge 正常使用（小红书已登录），保持窗口开着
REM  抓取脚本通过 9222 端口连接它
REM ============================================================
echo [1/3] 检查 9222 端口是否被占用...
netstat -ano | findstr ":9222" >nul 2>&1
if %errorlevel%==0 (
  echo [警告] 9222 端口已被占用，可能已有调试实例。
  echo        如需重启请先完全退出 Edge，再运行本脚本。
  pause
  exit /b 1
)

echo [2/3] 请确认：日常 Edge 已完全关闭（右上角 X 关闭所有窗口）？
echo        按任意键继续（会在本窗口稍后自动打开 Edge）...
pause >nul

echo [3/3] 启动日常 Edge（调试端口 9222）...
start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --no-first-run

echo.
echo ============================================================
echo  Edge 已启动（带调试端口 9222）。
echo  请在 Edge 中正常使用：打开小红书并确认已登录你的账号。
echo  保持本 Edge 窗口开着，然后回来告诉我「已就绪」。
echo ============================================================
pause
