# ============================================================
#  Enterprise AI App - 本地一键启动
#  用法：双击 start-dev.cmd，或在 PowerShell 里运行本脚本
#  参数：-NoBrowser  启动完成后不自动打开浏览器
# ============================================================
param([switch]$NoBrowser)

# 让中文在 cmd/PowerShell 5.1 里都能正常显示
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$ErrorActionPreference = 'Stop'
$root       = $PSScriptRoot
$gatewayDir = Join-Path $root 'services\api-gateway'
$webDir     = Join-Path $root 'apps\web'
$adminDir   = Join-Path $root 'apps\admin'
$gatewayUrl = 'http://127.0.0.1:8000'
$webUrl     = 'http://127.0.0.1:3002'
$adminUrl   = 'http://127.0.0.1:3001'

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

function Wait-Http([string]$Url, [int]$TimeoutSec) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) { return $true }
        } catch { }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

Write-Host ''
Write-Host '============================================' -ForegroundColor DarkCyan
Write-Host '  Enterprise AI App - 本地开发环境启动' -ForegroundColor White
Write-Host '============================================' -ForegroundColor DarkCyan
Write-Host ''

# ---------- 1. 环境检查 ----------
Write-Step '检查运行环境...'

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Err2 '未找到 node，请先安装 Node.js >= 20'
    exit 1
}
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Err2 '未找到 pnpm，请先执行：npm i -g pnpm'
    exit 1
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Err2 '未找到 python，请先安装 Python 3.11+'
    exit 1
}
$nodeVersion = (& node -v) 2>$null
Write-Ok ("node " + $nodeVersion + " / pnpm 已找到")

if (-not (Test-Path (Join-Path $root '.env'))) {
    Write-Warn2 '缺少根目录 .env，网关会使用默认配置（SQLite + 演示数据）'
}
if (-not (Test-Path (Join-Path $gatewayDir 'data'))) {
    New-Item -ItemType Directory -Path (Join-Path $gatewayDir 'data') -Force | Out-Null
}
# 依赖是单一 pnpm workspace：只在仓库根装一次（在 apps 子目录装会生成第二份锁文件）
if (-not (Test-Path (Join-Path $root 'node_modules')) -or
    -not (Test-Path (Join-Path $webDir 'node_modules')) -or
    -not (Test-Path (Join-Path $adminDir 'node_modules'))) {
    Write-Warn2 '前端依赖未安装，正在仓库根执行 pnpm install（首次会慢一点）...'
    Push-Location $root
    pnpm install
    Pop-Location
    if ($LASTEXITCODE -ne 0) { Write-Err2 'pnpm install 失败，请检查网络或 pnpm 配置'; exit 1 }
}

# ---------- 2. 启动后端网关 ----------
Write-Step '启动 API 网关 (http://127.0.0.1:8000)...'

if (Test-PortOpen 8000) {
    Write-Warn2 '端口 8000 已被占用，跳过启动（视为网关已在运行）'
} else {
    # 必须在该目录启动，DATABASE_URL 里的 ./data 是相对路径
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/k', 'title API Gateway :8000 & python -m uvicorn app.main:app --host 127.0.0.1 --port 8000' `
        -WorkingDirectory $gatewayDir | Out-Null
    if (Wait-Http "$gatewayUrl/docs" 90) {
        Write-Ok '网关已就绪，接口文档：http://127.0.0.1:8000/docs'
    } else {
        Write-Err2 '网关 90 秒内未就绪，请查看新弹出的 “API Gateway :8000” 窗口里的报错'
    }
}

# ---------- 3. 启动前端 ----------
Write-Step '启动前端 (http://127.0.0.1:3002)...'

if (Test-PortOpen 3002) {
    Write-Warn2 '端口 3002 已被占用，跳过启动（视为前端已在运行）'
} else {
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/k', 'title Web (Next.js) :3002 & pnpm dev' `
        -WorkingDirectory $webDir | Out-Null
    if (Wait-Http $webUrl 120) {
        Write-Ok '前端已就绪'
    } else {
        Write-Err2 '前端 120 秒内未就绪，请查看新弹出的 “Web (Next.js) :3002” 窗口'
    }
}

# ---------- 4. 启动管理后台 ----------
Write-Step '启动管理后台 (http://127.0.0.1:3001)...'

if (Test-PortOpen 3001) {
    Write-Warn2 '端口 3001 已被占用，跳过启动（视为管理后台已在运行）'
} else {
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/k', 'title Admin (Next.js) :3001 & pnpm dev' `
        -WorkingDirectory $adminDir | Out-Null
    if (Wait-Http $adminUrl 120) {
        Write-Ok '管理后台已就绪'
    } else {
        Write-Err2 '管理后台 120 秒内未就绪，请查看新弹出的 “Admin (Next.js) :3001” 窗口'
    }
}

# ---------- 5. 汇总 ----------
Write-Host ''
Write-Host '--------------------------------------------' -ForegroundColor DarkCyan
Write-Host '  前端      http://localhost:3002' -ForegroundColor White
Write-Host '  管理后台  http://localhost:3001' -ForegroundColor White
Write-Host '  接口文档  http://127.0.0.1:8000/docs' -ForegroundColor White
Write-Host '  演示账号  admin@example.com / admin123' -ForegroundColor White
Write-Host '--------------------------------------------' -ForegroundColor DarkCyan
Write-Host '  关闭服务：在各自弹出的窗口按 Ctrl+C，或直接关窗口' -ForegroundColor DarkGray
Write-Host ''

if (-not $NoBrowser) {
    Start-Process $webUrl
}
