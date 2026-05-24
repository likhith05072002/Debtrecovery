# DebtCollector - Start all services
$PG_CTL = "C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe"
$PG_DATA = "C:\Program Files\PostgreSQL\17\data"
$REDIS = "C:\Program Files\Redis\redis-server.exe"
$REDIS_CONF = "C:\Program Files\Redis\redis.windows.conf"

# ── PostgreSQL ────────────────────────────────────────────────────────────────
$pgRunning = (Get-Process -Name "postgres" -ErrorAction SilentlyContinue) -ne $null
if ($pgRunning) {
    Write-Host "PostgreSQL already running." -ForegroundColor Green
} else {
    Write-Host "Starting PostgreSQL..." -ForegroundColor Cyan
    & $PG_CTL start -D $PG_DATA -l "$PG_DATA\log\pg.log" -w
    if ($LASTEXITCODE -eq 0) {
        Write-Host "PostgreSQL started." -ForegroundColor Green
    } else {
        Write-Host "PostgreSQL failed to start. Check log: $PG_DATA\log\pg.log" -ForegroundColor Red
        exit 1
    }
}

# ── Redis ─────────────────────────────────────────────────────────────────────
$redisRunning = (Get-Process -Name "redis-server" -ErrorAction SilentlyContinue) -ne $null
if ($redisRunning) {
    Write-Host "Redis already running." -ForegroundColor Green
} else {
    Write-Host "Starting Redis..." -ForegroundColor Cyan
    Start-Process -FilePath $REDIS -ArgumentList $REDIS_CONF -WindowStyle Minimized
    Start-Sleep -Seconds 2
    Write-Host "Redis started." -ForegroundColor Green
}

# ── Uvicorn ───────────────────────────────────────────────────────────────────
Write-Host "Starting Uvicorn on :8001..." -ForegroundColor Cyan
& "$PSScriptRoot\venv\Scripts\Activate.ps1"
uvicorn app.main:app --reload --port 8001
