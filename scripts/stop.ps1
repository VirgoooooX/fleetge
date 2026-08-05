# Fleetge 开发服务器一键停止脚本 (PowerShell)

$ErrorActionPreference = "SilentlyContinue"

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "             Fleetge 开发服务器停止脚本" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

$ports = @(8000, 5173)
$stoppedCount = 0

foreach ($port in $ports) {
    $connections = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($connections) {
        $pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($pidToKill in $pids) {
            if ($pidToKill -gt 0) {
                $proc = Get-Process -Id $pidToKill -ErrorAction SilentlyContinue
                $procName = "PID $pidToKill"
                if ($proc) { $procName = $proc.ProcessName }
                Write-Host "正在停止端口 $port 上的服务: $procName (PID: $pidToKill)..." -ForegroundColor Yellow
                Stop-Process -Id $pidToKill -Force -ErrorAction SilentlyContinue
                $stoppedCount++
            }
        }
    } else {
        Write-Host "端口 $port 当前无运行中的服务。" -ForegroundColor Gray
    }
}

Write-Host ""
if ($stoppedCount -gt 0) {
    Write-Host "========================================================" -ForegroundColor Green
    Write-Host " 已成功停止所有 Fleetge 开发服务器进程！" -ForegroundColor Green
    Write-Host "========================================================" -ForegroundColor Green
} else {
    Write-Host "========================================================" -ForegroundColor Yellow
    Write-Host " 未检测到运行中的 Fleetge 开发服务 (端口 8000 / 5173)。" -ForegroundColor Yellow
    Write-Host "========================================================" -ForegroundColor Yellow
}
Write-Host ""
