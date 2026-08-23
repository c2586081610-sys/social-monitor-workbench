@echo off
rem yutto.cmd - B 站下载器包装脚本（确保 yutto 可在 PATH 中找到）
rem 用法：yutto <url> [options]，等价于 python -m yutto <url> [options]
rem 若 Python 路径变化，只需修改 PYTHON_EXE 一行。
set "PYTHON_EXE=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
"%PYTHON_EXE%" -m yutto %*
exit /b %ERRORLEVEL%
