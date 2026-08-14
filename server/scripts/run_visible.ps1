# 可见窗口启动后端(脱离 Hermes,前台运行,日志实时显示在本窗口)
# 用法: powershell -ExecutionPolicy Bypass -File scripts\run_visible.ps1
# 停止: 在该窗口按 Ctrl+C,或运行 scripts\stop_server.ps1
$ErrorActionPreference = "Stop"
$ServerDir = Split-Path -Parent $PSScriptRoot

# 端口占用检查(已有实例则提示先停)
$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Host "端口 8000 已被占用(PID $($listener[0].OwningProcess)),如需重启请先运行 stop_server.ps1"
    exit 2
}

# 打开新的可见 cmd 窗口,前台运行 uvicorn(日志直接滚动显示,窗口关闭服务即停)
# 清掉 Hermes 注入的 PYTHONPATH,避免 import 串包
Start-Process cmd -ArgumentList "/k title jieqi-backend-logs && cd /d $ServerDir && set PYTHONPATH= && .venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000" `
    -WorkingDirectory $ServerDir -WindowStyle Normal

Write-Host "已在新窗口启动后端(前台,日志实时显示)。"
Write-Host "   停止: 在该窗口按 Ctrl+C,或运行 scripts\stop_server.ps1"
