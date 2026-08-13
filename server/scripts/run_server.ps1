# 独立启动后端(脱离 Hermes 等宿主进程,关闭 Hermes 不影响)
# 用法: powershell -ExecutionPolicy Bypass -File scripts\run_server.ps1
# 日志: logs\server.out.log / logs\server.err.log;PID: logs\server.pid
$ErrorActionPreference = "Stop"
$ServerDir = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ServerDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Py = Join-Path $ServerDir ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { Write-Error "未找到 venv: $Py"; exit 1 }

# 端口占用检查(已有实例则提示先停)
$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Host "端口 8000 已被占用(PID $($listener[0].OwningProcess)),如需重启请先运行 stop_server.ps1"
    exit 2
}

# 关键:清掉 Hermes 注入的 PYTHONPATH,避免子进程 import 到宿主 site-packages
$env:PYTHONPATH = ""

$proc = Start-Process -FilePath $Py `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000" `
    -WorkingDirectory $ServerDir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $LogDir "server.out.log") `
    -RedirectStandardError (Join-Path $LogDir "server.err.log")
$proc.Id | Out-File -FilePath (Join-Path $LogDir "server.pid") -Encoding ascii

Start-Sleep -Seconds 3
if (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue) {
    Write-Host "OK 后端已独立启动(PID $($proc.Id))"
    Write-Host "   地址: http://0.0.0.0:8000 (局域网 http://<本机IP>:8000)"
    Write-Host "   日志: $LogDir (out/err),PID 文件: server.pid"
    Write-Host "   停止: powershell -ExecutionPolicy Bypass -File scripts\stop_server.ps1"
} else {
    Write-Host "FAIL 启动失败,请查看 logs\server.err.log"
    exit 3
}
