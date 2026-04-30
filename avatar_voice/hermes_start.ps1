# hermes_start.ps1 — Inicia o Hermes com o provider escolhido
#
# Uso:
#   .\hermes_start.ps1                         # usa OpenAI (padrão)
#   .\hermes_start.ps1 -Provider openai        # OpenAI   (requer OPENAI_API_KEY)
#   .\hermes_start.ps1 -Provider ollama        # Ollama local
#   .\hermes_start.ps1 -Provider openrouter    # OpenRouter (requer OPENROUTER_API_KEY)
#   .\hermes_start.ps1 -Down                   # para o Hermes
#   .\hermes_start.ps1 -Status                 # mostra status

param(
    [ValidateSet("openai", "ollama", "openrouter")]
    [string]$Provider = "openai",
    [string]$ApiKey   = "",
    [string]$Model    = "",
    [switch]$Down,
    [switch]$Status
)

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$HermesRoot = Split-Path -Parent $ScriptDir   # pasta hermes-agent

function Ok   { param($m) Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn  { param($m) Write-Host "  [!]  $m" -ForegroundColor Yellow }
function Info  { param($m) Write-Host "   ->  $m" -ForegroundColor Cyan }
function Err   { param($m) Write-Host "  [X]  $m" -ForegroundColor Red }

Write-Host ""
Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║          Hermes Agent — Control          ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Verificar docker compose ────────────────────────────────────────────────
if (-not (Get-Command "docker" -ErrorAction SilentlyContinue)) {
    Err "Docker não encontrado. Instale Docker Desktop: https://www.docker.com/products/docker-desktop"
    exit 1
}

# ── Status ──────────────────────────────────────────────────────────────────
if ($Status) {
    Info "Status dos containers:"
    docker compose -f "$HermesRoot\docker-compose.yml" -f "$HermesRoot\docker-compose.override.yml" ps 2>&1
    Write-Host ""
    Info "Config atual do Hermes:"
    python "$ScriptDir\hermes_configure.py" show
    exit 0
}

# ── Down ────────────────────────────────────────────────────────────────────
if ($Down) {
    Info "Parando Hermes..."
    Set-Location $HermesRoot
    docker compose down 2>&1
    Ok "Hermes parado."
    exit 0
}

# ── Configurar provider ─────────────────────────────────────────────────────
Info "Configurando Hermes para: $($Provider.ToUpper())"

# Resolver API key do ambiente se não passada
if (-not $ApiKey) {
    $keyEnvMap = @{
        "openai"     = "OPENAI_API_KEY"
        "openrouter" = "OPENROUTER_API_KEY"
        "ollama"     = ""
    }
    $envVar = $keyEnvMap[$Provider]
    if ($envVar) {
        $ApiKey = [Environment]::GetEnvironmentVariable($envVar, "Process")
        if (-not $ApiKey) {
            $ApiKey = [Environment]::GetEnvironmentVariable($envVar, "User")
        }
        if (-not $ApiKey) {
            Err "$envVar não encontrada no ambiente."
            Write-Host ""
            Write-Host "  Configure com:" -ForegroundColor White
            Write-Host "    `$env:$envVar = 'sua-chave-aqui'"
            Write-Host "  Ou passe diretamente:"
            Write-Host "    .\hermes_start.ps1 -Provider $Provider -ApiKey 'sua-chave'"
            exit 1
        }
        Ok "$envVar encontrada"
    }
}

# Montar args para hermes_configure.py
$configArgs = @($Provider)
if ($ApiKey)  { $configArgs += @("--key",   $ApiKey) }
if ($Model)   { $configArgs += @("--model", $Model) }

python "$ScriptDir\hermes_configure.py" @configArgs
if ($LASTEXITCODE -ne 0) { Err "Falha ao configurar Hermes."; exit 1 }

# ── Subir docker compose ────────────────────────────────────────────────────
Info "Iniciando containers..."
Set-Location $HermesRoot

docker compose down 2>&1 | Out-Null
docker compose up -d 2>&1
if ($LASTEXITCODE -ne 0) { Err "Falha ao iniciar docker compose."; exit 1 }

# ── Aguardar API server ─────────────────────────────────────────────────────
Info "Aguardando API server (localhost:8642)..."
$attempts = 0
$maxAttempts = 15
$ready = $false
while ($attempts -lt $maxAttempts -and -not $ready) {
    Start-Sleep -Seconds 2
    $attempts++
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8642/v1/models" `
            -Headers @{Authorization = "Bearer aa6531e6c0db6b2fba53bb133fac2e0a"} `
            -UseBasicParsing -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $ready = $true }
    } catch {}
    if (-not $ready) { Write-Host "   ... aguardando ($attempts/$maxAttempts)" -NoNewline; Write-Host "`r" -NoNewline }
}

Write-Host ""
if ($ready) {
    Ok "Hermes API rodando em http://localhost:8642"
    Ok "Dashboard em     http://localhost:9119"
    Write-Host ""
    Write-Host "  Para usar com avatar_voice:" -ForegroundColor White
    Write-Host "    python main.py --provider hermes" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Para parar:" -ForegroundColor White
    Write-Host "    .\hermes_start.ps1 -Down" -ForegroundColor Cyan
} else {
    Warn "API server ainda não respondeu após $($maxAttempts*2)s."
    Warn "Verifique com: docker logs hermes"
}
Write-Host ""
