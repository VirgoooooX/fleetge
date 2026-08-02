@echo off
chcp 65001 >nul
title Fleetge Dev Servers

echo ========================================================
echo               Fleetge 开发服务器启动脚本
echo ========================================================
echo.

set "ROOT=%~dp0..\"

echo [1/2] 正在启动后端 FastAPI 服务 (http://127.0.0.1:8000)...
set "LOCAL_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312"
if exist "%LOCAL_PYTHON%\python.exe" (
    set "PATH=%LOCAL_PYTHON%;%PATH%"
)
start "Fleetge Backend (Port 8000)" cmd /k "cd /d "%ROOT%backend" && python -m uvicorn app.main:app --reload --port 8000"

echo [2/2] 正在启动前端 Vite 服务 (http://localhost:5173)...
start "Fleetge Frontend (Port 5173)" cmd /k "cd /d "%ROOT%frontend" && npm run dev"

echo.
echo ========================================================
echo  开发服务器已在独立的终端窗口中启动！
echo.
echo  - 前端开发界面:  http://localhost:5173/
echo  - 后端 API 文档:  http://127.0.0.1:8000/api/docs
echo ========================================================
echo.
pause
