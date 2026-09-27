@echo off
rem One-shot installer bootstrap. Delegates all logic to install.ps1.
rem 2026-09-27：参数逐个加引号再透传 —— %* 对含空格/&/^/% 的参数（比如
rem 密码）不健壮。更推荐不带密码直接跑，交互式录入见 tools/setup_account.py。
setlocal EnableDelayedExpansion
set "ARGS="
:loop
if "%~1"=="" goto run
set "ARGS=!ARGS! "%~1""
shift
goto loop
:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" !ARGS!
