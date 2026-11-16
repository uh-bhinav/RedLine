# RedLine local demo launcher (Windows PowerShell 5.1)
# Usage: powershell -ExecutionPolicy Bypass -File scripts\redline.ps1 <up|down|status|verify> [-Dashboard]
param(
    [Parameter(Position = 0)][ValidateSet("up", "down", "status", "verify")][string]$Command = "status",
    [switch]$Dashboard,
    [int]$ApiPort = 8000
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RunDir = Join-Path $Root ".run"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Compose = Join-Path $Root "docker-compose.demo.yml"
$DockerBin = "C:\Program Files\Docker\Docker\resources\bin"
if ((Test-Path $DockerBin) -and ($env:Path -notlike "*$DockerBin*")) { $env:Path += ";$DockerBin" }
# init_topics prints a check mark; cp1252 stdout would crash on it when redirected.
$env:PYTHONUTF8 = "1"
New-Item -ItemType Directory -Force $RunDir | Out-Null
Set-Location $Root

function Test-Alive($name) {
    $f = Join-Path $RunDir "$name.pid"
    if (-not (Test-Path $f)) { return $false }
    $procId = [int](Get-Content $f)
    return [bool](Get-Process -Id $procId -ErrorAction SilentlyContinue)
}

function Start-Bg($name, $argList) {
    if (Test-Alive $name) { Write-Host "$name already running"; return }
    $out = Join-Path $RunDir "$name.log"
    $err = Join-Path $RunDir "$name.err.log"
    $p = Start-Process -FilePath $Py -ArgumentList $argList -WorkingDirectory $Root `
        -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden -PassThru
    Set-Content -Path (Join-Path $RunDir "$name.pid") -Value $p.Id
    Write-Host "started $name (pid $($p.Id)), logs in .run\$name.log / .err.log"
}

function Stop-Bg($name) {
    $f = Join-Path $RunDir "$name.pid"
    if (Test-Path $f) {
        $procId = [int](Get-Content $f)
        # /T kills the child tree (npm -> node, uvicorn reloaders)
        if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
            & taskkill /PID $procId /T /F | Out-Null
        }
        Remove-Item $f -Force
        Write-Host "stopped $name"
    }
}

function Wait-Http($url, $seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { return $true }
        } catch { Start-Sleep -Seconds 1 }
    }
    return $false
}

function Invoke-Up {
    if (-not (Test-Path $Py)) { throw ".venv missing. Create it: python -m venv .venv; .venv\Scripts\pip install -r apps\api\requirements.txt" }
    if (-not (Test-Path (Join-Path $Root ".env"))) { throw ".env missing (copy .env.example and adjust; DATABASE_URL port 5433)" }
    & docker compose -f $Compose up -d --wait
    if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }
    & $Py -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "alembic failed" }
    & $Py -m apps.api.scripts.init_topics
    if ($LASTEXITCODE -ne 0) { throw "init_topics failed" }
    & $Py -m apps.api.scripts.init_clickhouse
    if ($LASTEXITCODE -ne 0) { throw "init_clickhouse failed" }

    Start-Bg "api" @("-m", "uvicorn", "apps.api.main:app", "--host", "127.0.0.1", "--port", "$ApiPort")
    Start-Bg "worker" @("-m", "apps.api.workers.eval_worker_v2")
    # Load tests are consumed from their own topic by a separate worker; without it they stay queued.
    Start-Bg "load-worker" @("-m", "apps.api.workers.load_worker")

    if (Wait-Http "http://127.0.0.1:$ApiPort/health" 60) { Write-Host "API healthy on :$ApiPort" }
    else { Write-Host "API did not become healthy; see .run\api.err.log" }

    if ($Dashboard) {
        $dash = Join-Path $Root "apps\dashboard"
        if (-not (Test-Path (Join-Path $dash "node_modules"))) { throw "run 'npm ci' in apps\dashboard first" }
        if (-not (Test-Alive "vite")) {
            $env:API_TARGET = "http://127.0.0.1:$ApiPort"
            $p = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm run dev" -WorkingDirectory $dash `
                -RedirectStandardOutput (Join-Path $RunDir "vite.log") -RedirectStandardError (Join-Path $RunDir "vite.err.log") `
                -WindowStyle Hidden -PassThru
            Set-Content -Path (Join-Path $RunDir "vite.pid") -Value $p.Id
        }
        if (Wait-Http "http://localhost:5173/" 60) { Write-Host "Dashboard on http://127.0.0.1:5173" }
        else { Write-Host "Vite did not respond; see .run\vite.err.log" }
    }
}

function Invoke-Down {
    Stop-Bg "vite"
    Stop-Bg "worker"
    Stop-Bg "load-worker"
    Stop-Bg "api"
    & docker compose -f $Compose down
}

function Invoke-Status {
    foreach ($n in "api", "worker", "load-worker", "vite") {
        $state = "stopped"
        if (Test-Alive $n) { $state = "running" }
        Write-Host ("{0,-8} {1}" -f $n, $state)
    }
    & docker compose -f $Compose ps
}

function Invoke-Verify {
    $base = "http://127.0.0.1:$ApiPort"
    $h = Invoke-RestMethod "$base/health"
    Write-Host "health: $($h.status)"
    $email = "verify_$([guid]::NewGuid().ToString('N').Substring(0,8))@example.com"
    $body = @{ email = $email; password = "Demo-Passw0rd!x"; name = "Verify" } | ConvertTo-Json
    $reg = Invoke-RestMethod -Method Post -Uri "$base/auth/register" -ContentType "application/json" -Body $body
    Write-Host "register: ok ($email)"
    $loginBody = @{ email = $email; password = "Demo-Passw0rd!x" } | ConvertTo-Json
    $login = Invoke-RestMethod -Method Post -Uri "$base/auth/login" -ContentType "application/json" -Body $loginBody
    $hdr = @{ Authorization = "Bearer $($login.access_token)" }
    $agents = Invoke-WebRequest -Uri "$base/dashboard/agents" -Headers $hdr -UseBasicParsing
    Write-Host "login + /dashboard/agents: HTTP $($agents.StatusCode)"
    if (Test-Alive "vite") {
        $v = Invoke-WebRequest -Uri "http://localhost:5173/" -UseBasicParsing
        Write-Host "vite: HTTP $($v.StatusCode)"
    }
}

switch ($Command) {
    "up" { Invoke-Up }
    "down" { Invoke-Down }
    "status" { Invoke-Status }
    "verify" { Invoke-Verify }
}
