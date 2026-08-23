@echo off
rem ffmpeg.cmd - 兜底包装脚本。同目录 ffmpeg.exe 可直接执行，此脚本仅保证
rem `ffmpeg` 命令在 PATH 中可解析（含 PATHEXT 为 .CMD 的调用场景）。
set "FFMPEG_EXE=%~dp0ffmpeg.exe"
"%FFMPEG_EXE%" %*
exit /b %ERRORLEVEL%
