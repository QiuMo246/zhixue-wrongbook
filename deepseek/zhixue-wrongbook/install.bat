@echo off
rem One-shot installer bootstrap. Delegates all logic to install.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
