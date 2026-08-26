@echo off
rem xhs.cmd - XHS-Downloader 包装脚本（小红书下载器）
rem 用法：xhs <XHS-Downloader CLI 参数>，等价于在 tools/xhs-downloader 下运行 python main.py <参数>
set "PYTHON_EXE=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
set "XHS_DIR=C:\Users\Administrator\WorkBuddy\2026-08-22-18-25-30\tools\xhs-downloader"
cd /d "%XHS_DIR%"
"%PYTHON_EXE%" main.py %*
exit /b %ERRORLEVEL%
