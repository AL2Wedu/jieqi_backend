# 停止独立启动的后端(PID 文件优先,端口残留兜底)
# 用法: powershell -ExecutionPolicy Bypass -File scripts\stop_server.ps1
$ErrorActionPreference = "SilentlyContinue"
$ServerDir = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ServerDir "logs"
$pidFile = Join-Path $LogDir "server.pid"

if (Test-Path $pidFile) {
    $savedPid = Get-Content $pidFile | Select-Object -First 1
    if ($savedPid -match '^\d+$' -and (Get-Process -Id $savedPid -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $savedPid -Force
        Write-Host "已按 PID 停止 $savedPid"
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# uvicorn 的 python 子进程可能残留,按端口兜底清理
$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Stop-Process -Id $listener.OwningProcess -Force
    Write-Host "已按端口清理残留进程 $($listener.OwningProcess)"
}
Write-Host "停止完成"
