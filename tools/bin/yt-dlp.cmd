@echo off
rem yt-dlp.cmd - 通用下载器包装脚本（推特/YouTube 等平台）
rem 用法：yt-dlp <url> [options]，等价于 python -m yt_dlp <url> [options]
set "PYTHON_EXE=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
"%PYTHON_EXE%" -m yt_dlp %*
exit /b %ERRORLEVEL%
