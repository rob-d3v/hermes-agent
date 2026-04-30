# Hermes Voice Pipeline — Setup Windows
# Execute como: .\install.ps1
# (requer PowerShell 5+ e permissões de execução: Set-ExecutionPolicy RemoteSigned -Scope CurrentUser)

param(
    [switch]$SkipPiper,
    [switch]$SkipSox
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PiperVersion = "2023.11.14-2"
$PiperDir = "$env:LOCALAPPDATA\piper"

Write-Host "=== Hermes Voice Pipeline — Setup Windows ===" -ForegroundColor Cyan
Write-Host ""

# ── Python deps ─────────────────────────────────────────────────────────────
Write-Host "[1/4] Instalando dependencias Python..." -ForegroundColor Yellow
pip install -r "$ScriptDir\requirements.txt"
Write-Host "      OK" -ForegroundColor Green

# ── Piper TTS ────────────────────────────────────────────────────────────────
Write-Host "[2/4] Verificando Piper TTS..." -ForegroundColor Yellow
if (-not $SkipPiper) {
    $piperExe = Get-Command piper.exe -ErrorAction SilentlyContinue
    if ($piperExe) {
        Write-Host "      Piper ja instalado: $($piperExe.Path)" -ForegroundColor Green
    } else {
        Write-Host "      Baixando Piper $PiperVersion para Windows..."
        $piperZip = "$env:TEMP\piper_windows_amd64.zip"
        $piperUrl = "https://github.com/rhasspy/piper/releases/download/$PiperVersion/piper_windows_amd64.zip"

        try {
            Invoke-WebRequest -Uri $piperUrl -OutFile $piperZip -UseBasicParsing
            if (-not (Test-Path $PiperDir)) { New-Item -ItemType Directory -Path $PiperDir | Out-Null }
            Expand-Archive -Path $piperZip -DestinationPath $PiperDir -Force
            Remove-Item $piperZip -Force

            # Add to user PATH if not already there
            $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
            $piperBinDir = "$PiperDir\piper"
            if ($userPath -notlike "*$piperBinDir*") {
                [Environment]::SetEnvironmentVariable("PATH", "$userPath;$piperBinDir", "User")
                $env:PATH += ";$piperBinDir"
                Write-Host "      Adicionado $piperBinDir ao PATH do usuario." -ForegroundColor Green
            }
            Write-Host "      Piper instalado em $piperBinDir\piper.exe" -ForegroundColor Green
            Write-Host "      IMPORTANTE: Abra um novo terminal para que o PATH seja atualizado." -ForegroundColor Yellow
        } catch {
            Write-Host "      AVISO: Nao foi possivel baixar Piper automaticamente." -ForegroundColor Yellow
            Write-Host "      Baixe manualmente em: https://github.com/rhasspy/piper/releases" -ForegroundColor Yellow
            Write-Host "      Coloque piper.exe em algum diretorio do PATH ou especifique o caminho em config.yaml"
        }
    }
} else {
    Write-Host "      Pulando (--SkipPiper)" -ForegroundColor DarkGray
}

# ── Sox (opcional, para pitch) ───────────────────────────────────────────────
Write-Host "[3/4] Verificando Sox (opcional, para ajuste de pitch)..." -ForegroundColor Yellow
if (-not $SkipSox) {
    $soxExe = Get-Command sox.exe -ErrorAction SilentlyContinue
    if ($soxExe) {
        Write-Host "      Sox ja instalado: $($soxExe.Path)" -ForegroundColor Green
    } else {
        # Try winget first, then choco
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        $choco = Get-Command choco -ErrorAction SilentlyContinue

        if ($winget) {
            Write-Host "      Instalando Sox via winget..."
            try {
                winget install --id SoX.SoX --accept-source-agreements --accept-package-agreements
                Write-Host "      Sox instalado via winget." -ForegroundColor Green
            } catch {
                Write-Host "      Falhou via winget. Sox e opcional — pitch adjustment estara desabilitado." -ForegroundColor Yellow
            }
        } elseif ($choco) {
            Write-Host "      Instalando Sox via chocolatey..."
            try {
                choco install sox -y
                Write-Host "      Sox instalado via choco." -ForegroundColor Green
            } catch {
                Write-Host "      Falhou via choco. Sox e opcional." -ForegroundColor Yellow
            }
        } else {
            Write-Host "      Sox nao encontrado e winget/choco nao disponiveis." -ForegroundColor Yellow
            Write-Host "      Sox e opcional (necessario apenas para pitch_semitones != 0)." -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "      Pulando (--SkipSox)" -ForegroundColor DarkGray
}

# ── Config ────────────────────────────────────────────────────────────────────
Write-Host "[4/4] Configuracao..." -ForegroundColor Yellow
$configFile = "$ScriptDir\config.yaml"
if (-not (Test-Path $configFile)) {
    Copy-Item "$ScriptDir\config.yaml.example" $configFile
    Write-Host "      config.yaml criado a partir do exemplo." -ForegroundColor Green
    Write-Host "      Edite $configFile para ajustar o modelo e caminhos."
} else {
    Write-Host "      config.yaml ja existe." -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Instalacao concluida! ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Para iniciar:" -ForegroundColor White
Write-Host "  cd $ScriptDir"
Write-Host "  python main.py --list-devices    # veja os dispositivos de audio"
Write-Host "  python main.py                   # inicia o pipeline"
Write-Host ""
Write-Host "Dica: Se o modelo de wake word ainda nao existe, use fallback_mode: keyboard em config.yaml" -ForegroundColor DarkCyan
