# Fleetge 开发服务器一键启动脚本 (PowerShell)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Path $PSScriptRoot -Parent

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "             Fleetge 开发服务器启动脚本" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

# 启动后端
Write-Host "[1/2] 正在启动后端 FastAPI 服务 (http://127.0.0.1:8000)..." -ForegroundColor Yellow
Start-Process -FilePath "cmd.exe" -ArgumentList "/k cd /d `"$projectRoot\backend`" && python -m uvicorn app.main:app --reload --port 8000" -WorkingDirectory "$projectRoot\backend"

# 启动前端
Write-Host "[2/2] 正在启动前端 Vite 服务 (http://localhost:5173)..." -ForegroundColor Yellow
Start-Process -FilePath "cmd.exe" -ArgumentList "/k cd /d `"$projectRoot\frontend`" && npm run dev" -WorkingDirectory "$projectRoot\frontend"

Write-Host ""
Write-Host "========================================================" -ForegroundColor Green
Write-Host " 开发服务器已在独立的终端窗口中启动！" -ForegroundColor Green
Write-Host ""
Write-Host " - 前端开发界面:  http://localhost:5173/" -ForegroundColor White
Write-Host " - 后端 API 文档:  http://127.0.0.1:8000/api/docs" -ForegroundColor White
Write-Host "========================================================" -ForegroundColor Green
Write-Host ""
