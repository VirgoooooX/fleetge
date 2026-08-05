@echo off
chcp 65001 >nul
title Fleetge Dev Servers Stopper

echo ========================================================
echo               Fleetge 开发服务器停止脚本
echo ========================================================
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0stop.ps1"

echo.
pause
