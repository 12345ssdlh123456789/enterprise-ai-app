# ============================================================
#  Enterprise AI App - 微服务本地启动（SQLite 零依赖模式）
#  用法：双击 start-microservices.cmd，或在 PowerShell 里运行本脚本
#  说明：auth / notification / llm / document / workflow 五个服务各自
#        使用 SQLite 开发库，不需要 PostgreSQL / Redis / MinIO。
#        rag-service 依赖 pgvector 向量检索，仍需 docker compose 起 PostgreSQL。
# ============================================================

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $root 'services\api-gateway\.venv\Scripts\python.exe'
# 服务间签名密钥：本地开发固定值；生产环境必须换成随机长串，并在所有服务保持一致。
$serviceKey = 'dev-internal-key'

function Write-Step($msg) { Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Err2($msg) { Write-Host "[X] $msg" -ForegroundColor Red }

function Test-PortOpen([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connect = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if ($connect.AsyncWaitHandle.WaitOne(500) -and $client.Connected) { return $true }
        return $false
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Wait-Health([int]$Port, [int]$TimeoutSec) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 3
            if ($resp.StatusCode -eq 200) { return $true }
        } catch { }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

Write-Host ''
Write-Host '============================================' -ForegroundColor DarkCyan
Write-Host '  Enterprise AI App - 微服务启动 (SQLite)' -ForegroundColor White
Write-Host '============================================' -ForegroundColor DarkCyan
Write-Host ''

if (-not (Test-Path $python)) {
    Write-Err2 "未找到网关虚拟环境：$python"
    Write-Err2 '请先在 services/api-gateway 下创建 .venv 并安装 requirements.txt'
    exit 1
}

$services = @(
    @{ Name = 'auth-service';         Port = 8007; Env = @('PORT=8007', "SERVICE_API_KEY=$serviceKey") },
    @{ Name = 'notification-service'; Port = 8006; Env = @("SERVICE_API_KEY=$serviceKey") },
    @{ Name = 'llm-service';          Port = 8003; Env = @('DATABASE_URL=sqlite+aiosqlite:///./llm_dev.db', 'DEBUG=false', "SERVICE_API_KEY=$serviceKey") },
    @{ Name = 'document-service';     Port = 8004; Env = @(
        'DATABASE_URL=sqlite+aiosqlite:///./document_dev.db', 'DEBUG=false',
        'STORAGE_PROVIDER=local', 'STORAGE_LOCAL_DIR=./data/storage', 'PUBLIC_BASE_URL=http://127.0.0.1:8004',
        "SERVICE_API_KEY=$serviceKey"
    ) },
    @{ Name = 'workflow-service';     Port = 8005; Env = @('DATABASE_URL=sqlite+aiosqlite:///./workflow_dev.db', 'DEBUG=false', "SERVICE_API_KEY=$serviceKey") }
)

$started = @()

foreach ($svc in $services) {
    Write-Step "启动 $($svc.Name) (http://127.0.0.1:$($svc.Port))..."
    if (Test-PortOpen $svc.Port) {
        Write-Warn2 "端口 $($svc.Port) 已被占用，跳过（视为已在运行）"
        $started += "$($svc.Name)  :$($svc.Port)  (已有的进程)"
        continue
    }

    $command = "title $($svc.Name) :$($svc.Port)"
    # set "NAME=value" 的引号不能省：它会把行尾空格吃进变量值，导致 PYTHONUTF8 非法。
    foreach ($envVar in $svc.Env) { $command += " & set `"$envVar`"" }
    $command += " & set `"PYTHONUTF8=1`" & ..\api-gateway\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port $($svc.Port)"

    Start-Process -FilePath 'cmd.exe' -ArgumentList '/k', $command -WorkingDirectory (Join-Path $root "services\$($svc.Name)") | Out-Null

    if (Wait-Health $svc.Port 45) {
        Write-Ok "$($svc.Name) 已就绪"
        $started += "$($svc.Name)  :$($svc.Port)"
    } else {
        Write-Err2 "$($svc.Name) 45 秒内未就绪，请查看弹出的 “$($svc.Name)” 窗口里的报错"
    }
}

Write-Host ''
Write-Host '--------------------------------------------' -ForegroundColor DarkCyan
if ($started.Count -gt 0) {
    foreach ($line in $started) { Write-Host "  $line" -ForegroundColor White }
}
Write-Host '--------------------------------------------' -ForegroundColor DarkCyan
Write-Host '  冒烟测试：python tests/test_microservices_smoke.py' -ForegroundColor White
Write-Host '  rag-service 需要 pgvector：docker compose up -d postgres redis' -ForegroundColor DarkGray
Write-Host '  关闭服务：在各自弹出的窗口按 Ctrl+C，或直接关窗口' -ForegroundColor DarkGray
Write-Host ''
