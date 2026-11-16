<#
.SYNOPSIS
  Operate the RedLine stack: docker compose (default) or local processes.

.EXAMPLE
  powershell -File scripts/redline.ps1 up
  powershell -File scripts/redline.ps1 verify
  powershell -File scripts/redline.ps1 up -Mode local
  powershell -File scripts/redline.ps1 down -Mode docker -Purge   # DELETES the postgres volume (asks first)
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'down', 'status', 'logs', 'verify')]
    [string]$Action = 'status',

    [ValidateSet('docker', 'local')]
    [string]$Mode = 'docker',

    # docker mode only: also remove volumes (data loss). Requires typed confirmation.
    [switch]$Purge,

    [int]$Tail = 100,
    [string]$Service = '',
    [int]$SmokeTimeoutSec = 120
)

$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$RunDir = Join-Path $Root '.run'
$ApiUrl = 'http://localhost:8000'
$DemoEmail = 'demo@redline.dev'
$DemoPassword = 'DemoPass123!'

# ---------------------------------------------------------------- helpers
function Resolve-Docker {
    $cmd = Get-Command docker -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Docker\Docker\resources\bin\docker.exe')
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) {
            # compose needs sibling helpers (docker-credential-*) on PATH
            $env:PATH = (Split-Path -Parent $c) + ';' + $env:PATH
            return $c
        }
    }
    throw 'docker.exe not found. Install Docker Desktop or use -Mode local.'
}

function Invoke-Compose {
    param([string[]]$ComposeArgs)
    $docker = Resolve-Docker
    & $docker compose @ComposeArgs | Out-Host
    return $LASTEXITCODE
}

function Get-Python {
    $venv = Join-Path $Root '.venv\Scripts\python.exe'
    if (Test-Path $venv) { return $venv }
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    throw 'python not found (create .venv or install Python 3.11+).'
}

function Get-DotEnv {
    param([string]$Key)
    $f = Join-Path $Root '.env'
    if (-not (Test-Path $f)) { return $null }
    foreach ($line in Get-Content $f) {
        if ($line -match ('^' + [regex]::Escape($Key) + '=(.*)$')) { return $Matches[1].Trim() }
    }
    return $null
}

function Test-TcpPort {
    param([string]$HostName, [int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne(2000)) { return $false }
        $client.EndConnect($iar)
        return $true
    }
    catch { return $false }
    finally { $client.Close() }
}

# Returns @{ Status = <int or 0>; Body = <string> }; never throws.
function Invoke-Http {
    param([string]$Method = 'GET', [string]$Url, [string]$Token = '', $Json = $null, [int]$TimeoutSec = 15)
    $headers = @{}
    if ($Token) { $headers['Authorization'] = 'Bearer ' + $Token }
    $params = @{ Uri = $Url; Method = $Method; Headers = $headers; UseBasicParsing = $true; TimeoutSec = $TimeoutSec }
    if ($null -ne $Json) {
        $params['Body'] = ($Json | ConvertTo-Json -Depth 6 -Compress)
        $params['ContentType'] = 'application/json'
    }
    try {
        $r = Invoke-WebRequest @params
        return @{ Status = [int]$r.StatusCode; Body = [string]$r.Content }
    }
    catch {
        $resp = $_.Exception.Response
        if ($resp) {
            $body = ''
            try {
                $sr = New-Object System.IO.StreamReader($resp.GetResponseStream())
                $body = $sr.ReadToEnd()
            }
            catch { }
            return @{ Status = [int]$resp.StatusCode; Body = $body }
        }
        return @{ Status = 0; Body = $_.Exception.Message }
    }
}

# ---------------------------------------------------------------- local mode
function Get-PidFile { param([string]$Name) return (Join-Path $RunDir ($Name + '.pid')) }

function Get-RunningPid {
    param([string]$Name)
    $f = Get-PidFile $Name
    if (-not (Test-Path $f)) { return $null }
    $raw = (Get-Content $f -ErrorAction SilentlyContinue | Select-Object -First 1)
    $procId = 0
    if (-not [int]::TryParse([string]$raw, [ref]$procId)) { return $null }
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($p) { return $procId }
    return $null
}

function Start-LocalProc {
    param([string]$Name, [string[]]$ArgList)
    $existing = Get-RunningPid $Name
    if ($existing) { Write-Host "$Name already running (pid $existing)"; return }
    $py = Get-Python
    $p = Start-Process -FilePath $py -ArgumentList $ArgList -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $RunDir ($Name + '.log')) `
        -RedirectStandardError (Join-Path $RunDir ($Name + '.err.log'))
    Set-Content -Path (Get-PidFile $Name) -Value $p.Id
    Write-Host "started $Name (pid $($p.Id)), logs: .run/$Name.log"
}

function Stop-LocalProc {
    param([string]$Name)
    $procId = Get-RunningPid $Name
    if ($procId) {
        # /T kills the whole tree (uvicorn reload/children), /F forces
        & taskkill.exe /PID $procId /T /F | Out-Null
        Write-Host "stopped $Name (pid $procId)"
    }
    else { Write-Host "$Name not running" }
    Remove-Item (Get-PidFile $Name) -ErrorAction SilentlyContinue
}

function Start-Local {
    if (-not (Test-Path $RunDir)) { New-Item -ItemType Directory -Path $RunDir | Out-Null }
    $py = Get-Python

    # 1. Postgres: reuse whatever .env DATABASE_URL points at, else start embedded pgserver.
    $dbUrl = Get-DotEnv 'DATABASE_URL'
    $dbHost = 'localhost'; $dbPort = 5433
    if ($dbUrl -match '@([^:/]+):(\d+)/') { $dbHost = $Matches[1]; $dbPort = [int]$Matches[2] }
    if ($dbUrl -and (Test-TcpPort $dbHost $dbPort)) {
        Write-Host "Postgres reachable at ${dbHost}:${dbPort}"
    }
    else {
        Write-Host 'Postgres not reachable; starting embedded Postgres (scripts/dev_db.py)'
        & $py (Join-Path $Root 'scripts\dev_db.py')
        if ($LASTEXITCODE -ne 0) { throw 'scripts/dev_db.py failed' }
    }

    # 2. Migrations
    Write-Host 'alembic upgrade head'
    & $py -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade head failed' }

    # 3. Processes
    if (Test-TcpPort 'localhost' 8000) {
        if (-not (Get-RunningPid 'api')) { throw 'port 8000 already in use by another process' }
    }
    Start-LocalProc -Name 'api' -ArgList @('-m', 'uvicorn', 'apps.api.main:app', '--host', '0.0.0.0', '--port', '8000')
    Start-LocalProc -Name 'worker' -ArgList @('-m', 'apps.api.workers.eval_worker')

    # 4. Wait for API
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        $r = Invoke-Http -Url "$ApiUrl/health" -TimeoutSec 3
        if ($r.Status -eq 200) { Write-Host 'API is up.'; return }
        Start-Sleep -Seconds 1
    }
    throw 'API did not become healthy within 60s; see .run/api.err.log'
}

function Stop-Local {
    Stop-LocalProc 'worker'
    Stop-LocalProc 'api'
    Write-Host 'Embedded Postgres (if any) is left running; data is in .pgdata.'
}

# ---------------------------------------------------------------- actions
function Do-Up {
    if ($Mode -eq 'docker') {
        $code = Invoke-Compose @('up', '-d', '--build', '--wait')
        if ($code -ne 0) { throw "docker compose up failed (exit $code)" }
    }
    else { Start-Local }
}

function Do-Down {
    if ($Mode -eq 'docker') {
        if ($Purge) {
            Write-Host 'WARNING: -Purge removes docker volumes, including ALL postgres data (demo data too).' -ForegroundColor Yellow
            $answer = Read-Host "Type 'PURGE' to continue"
            if ($answer -cne 'PURGE') { Write-Host 'Aborted; nothing changed.'; return }
            $code = Invoke-Compose @('down', '-v')
        }
        else { $code = Invoke-Compose @('down') }
        if ($code -ne 0) { throw "docker compose down failed (exit $code)" }
    }
    else {
        if ($Purge) { Write-Host '-Purge is ignored in local mode (delete .pgdata manually if desired).' }
        Stop-Local
    }
}

function Do-Status {
    if ($Mode -eq 'docker') {
        $code = Invoke-Compose @('ps')
        if ($code -ne 0) { throw "docker compose ps failed (exit $code)" }
    }
    else {
        foreach ($n in @('api', 'worker')) {
            $procId = Get-RunningPid $n
            if ($procId) { Write-Host ("{0,-8} running (pid {1})" -f $n, $procId) }
            else { Write-Host ("{0,-8} stopped" -f $n) }
        }
        $r = Invoke-Http -Url "$ApiUrl/health" -TimeoutSec 3
        Write-Host "GET /health -> $($r.Status)"
    }
}

function Do-Logs {
    if ($Mode -eq 'docker') {
        $a = @('logs', '--tail', [string]$Tail)
        if ($Service) { $a += $Service }
        $code = Invoke-Compose $a
        if ($code -ne 0) { throw "docker compose logs failed (exit $code)" }
    }
    else {
        foreach ($f in @('api.log', 'api.err.log', 'worker.log', 'worker.err.log')) {
            $p = Join-Path $RunDir $f
            if (Test-Path $p) {
                Write-Host "==== .run/$f ===="
                Get-Content $p -Tail $Tail
            }
        }
    }
}

function Do-Verify {
    $results = New-Object System.Collections.ArrayList
    function Add-Result {
        param([string]$Name, [string]$State, [string]$Detail)
        [void]$results.Add([pscustomobject]@{ Check = $Name; Result = $State; Detail = $Detail })
    }
    $dashUrl = 'http://localhost:8080'
    if ($Mode -eq 'local') { $dashUrl = 'http://localhost:5173' }

    # /health
    $r = Invoke-Http -Url "$ApiUrl/health"
    if ($r.Status -eq 200) { Add-Result 'GET /health' 'PASS' '200' }
    else { Add-Result 'GET /health' 'FAIL' "status $($r.Status) $($r.Body)" }

    # /ready
    $r = Invoke-Http -Url "$ApiUrl/ready"
    $ready = $false
    if ($r.Status -eq 200) {
        try { $ready = ((ConvertFrom-Json $r.Body).status -eq 'ready') } catch { $ready = $false }
    }
    if ($ready) { Add-Result 'GET /ready' 'PASS' 'status=ready' }
    else { Add-Result 'GET /ready' 'FAIL' "status $($r.Status) $($r.Body)" }

    # demo login
    $token = ''
    $r = Invoke-Http -Method 'POST' -Url "$ApiUrl/auth/login" -Json @{ email = $DemoEmail; password = $DemoPassword }
    if ($r.Status -eq 200) {
        try { $token = (ConvertFrom-Json $r.Body).access_token } catch { $token = '' }
    }
    if ($token) { Add-Result 'demo login' 'PASS' $DemoEmail }
    elseif ($r.Status -eq 401) { Add-Result 'demo login' 'WARN' 'demo data not seeded (python -m scripts.seed_demo)' }
    else { Add-Result 'demo login' 'FAIL' "status $($r.Status) $($r.Body)" }

    # dashboard summary
    if ($token) {
        $r = Invoke-Http -Url "$ApiUrl/dashboard/summary" -Token $token
        if ($r.Status -eq 200) { Add-Result 'GET /dashboard/summary' 'PASS' '200' }
        else { Add-Result 'GET /dashboard/summary' 'FAIL' "status $($r.Status) $($r.Body)" }
    }
    else { Add-Result 'GET /dashboard/summary' 'SKIP' 'no token (demo data not seeded)' }

    # dashboard web UI
    $r = Invoke-Http -Url $dashUrl
    if ($r.Status -eq 200) { Add-Result "dashboard $dashUrl" 'PASS' '200' }
    else { Add-Result "dashboard $dashUrl" 'FAIL' "status $($r.Status)" }

    # smoke eval job
    if (-not $token) {
        Add-Result 'smoke eval run' 'FAIL' 'needs demo data (login failed)'
    }
    else {
        $detail = ''
        $state = 'FAIL'
        $agents = Invoke-Http -Url "$ApiUrl/dashboard/agents" -Token $token
        $agentId = $null
        if ($agents.Status -eq 200) {
            foreach ($a in (ConvertFrom-Json $agents.Body)) {
                if ($a.name -eq 'stateful-support-agent') { $agentId = $a.id }
            }
        }
        if (-not $agentId) { $detail = 'agent stateful-support-agent not found' }
        else {
            $d = Invoke-Http -Url "$ApiUrl/dashboard/agents/$agentId" -Token $token
            $versionId = $null; $suiteId = $null
            if ($d.Status -eq 200) {
                $dj = ConvertFrom-Json $d.Body
                if ($dj.latest_version) { $versionId = $dj.latest_version.id }
                if ($dj.suites -and @($dj.suites).Count -gt 0) { $suiteId = @($dj.suites)[0].id }
            }
            if (-not $versionId -or -not $suiteId) { $detail = 'agent has no version or suite' }
            else {
                $c = Invoke-Http -Method 'POST' -Url "$ApiUrl/eval-runs" -Token $token `
                    -Json @{ agent_version_id = $versionId; suite_id = $suiteId; triggered_by = 'manual' }
                if ($c.Status -ne 201) { $detail = "create failed: status $($c.Status) $($c.Body)" }
                else {
                    $runId = (ConvertFrom-Json $c.Body).id
                    $deadline = (Get-Date).AddSeconds($SmokeTimeoutSec)
                    $status = 'pending'
                    $t0 = Get-Date
                    while ((Get-Date) -lt $deadline) {
                        $g = Invoke-Http -Url "$ApiUrl/eval-runs/$runId" -Token $token
                        if ($g.Status -eq 200) {
                            $status = (ConvertFrom-Json $g.Body).status
                            if ($status -eq 'completed' -or $status -eq 'failed') { break }
                        }
                        Start-Sleep -Seconds 2
                    }
                    $secs = [int]((Get-Date) - $t0).TotalSeconds
                    if ($status -eq 'completed') { $state = 'PASS'; $detail = "run $runId completed in ${secs}s" }
                    else { $detail = "run $runId ended as '$status' after ${secs}s (timeout ${SmokeTimeoutSec}s)" }
                }
            }
        }
        Add-Result 'smoke eval run' $state $detail
    }

    Write-Host ''
    Write-Host "RedLine verify (mode: $Mode)"
    $results | Format-Table -AutoSize -Wrap | Out-String -Width 200 | Write-Host
    $failed = @($results | Where-Object { $_.Result -eq 'FAIL' }).Count
    if ($failed -gt 0) { Write-Host "OVERALL: FAIL ($failed failed)" -ForegroundColor Red; return 1 }
    Write-Host 'OVERALL: PASS' -ForegroundColor Green
    return 0
}

# ---------------------------------------------------------------- dispatch
try {
    switch ($Action) {
        'up' { Do-Up }
        'down' { Do-Down }
        'status' { Do-Status }
        'logs' { Do-Logs }
        'verify' { $rc = Do-Verify; exit ([int]($rc | Select-Object -Last 1)) }
    }
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
exit 0
