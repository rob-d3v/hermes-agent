# avatar_voice — Setup automático Windows
# Uso: .\install.ps1
# Requer PowerShell 5+
# Permissões: Set-ExecutionPolicy RemoteSigned -Scope CurrentUser

param(
    [switch]$SkipPiper,
    [switch]$SkipSox,
    [switch]$SkipOllama
)

$ErrorActionPreference = "Stop"
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$PiperVersion = "2023.11.14-2"
$PiperDir    = "$env:LOCALAPPDATA\piper"

function Ok   { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Warn  { param($msg) Write-Host "  [!]  $msg" -ForegroundColor Yellow }
function Info  { param($msg) Write-Host "   ->  $msg" -ForegroundColor Cyan }
function Step  { param($n,$msg) Write-Host "`n[$n] $msg" -ForegroundColor White }

Write-Host ""
Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║      avatar_voice — Instalação Windows    ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── 1. Python ──────────────────────────────────────────────────────────────────
Step "1/6" "Verificando Python..."
try {
    $pyVer = python --version 2>&1
    Ok "Python encontrado: $pyVer"
} catch {
    Warn "Python não encontrado. Instale em: https://www.python.org/downloads/"
    Warn "Marque 'Add Python to PATH' durante a instalação."
    exit 1
}

# ── 2. Pacotes Python ──────────────────────────────────────────────────────────
Step "2/6" "Instalando pacotes Python..."
try {
    pip install -r "$ScriptDir\requirements.txt" -q
    Ok "Pacotes Python instalados"
} catch {
    Warn "Falha ao instalar pacotes. Tente: pip install -r requirements.txt"
}

# ── 3. Piper TTS ───────────────────────────────────────────────────────────────
Step "3/6" "Verificando Piper TTS..."
if (-not $SkipPiper) {
    $piperExe = Get-Command piper.exe -ErrorAction SilentlyContinue
    if ($piperExe) {
        Ok "Piper já instalado: $($piperExe.Path)"
    } else {
        Info "Baixando Piper $PiperVersion para Windows..."
        $piperZip = "$env:TEMP\piper_windows_amd64.zip"
        $piperUrl = "https://github.com/rhasspy/piper/releases/download/$PiperVersion/piper_windows_amd64.zip"
        try {
            Invoke-WebRequest -Uri $piperUrl -OutFile $piperZip -UseBasicParsing
            if (-not (Test-Path $PiperDir)) { New-Item -ItemType Directory -Path $PiperDir | Out-Null }
            Expand-Archive -Path $piperZip -DestinationPath $PiperDir -Force
            Remove-Item $piperZip -Force

            $piperBinDir = "$PiperDir\piper"
            $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
            if ($userPath -notlike "*$piperBinDir*") {
                [Environment]::SetEnvironmentVariable("PATH", "$userPath;$piperBinDir", "User")
                $env:PATH += ";$piperBinDir"
            }
            Ok "Piper instalado em $piperBinDir\piper.exe"
            Warn "Abra um NOVO terminal para que o PATH seja atualizado."
        } catch {
            Warn "Não foi possível baixar Piper automaticamente."
            Warn "Baixe manualmente: https://github.com/rhasspy/piper/releases"
            Warn "Extraia e coloque piper.exe em algum diretório do PATH."
            Warn "Ou configure 'tts.piper_binary' no config.yaml com o caminho completo."
        }
    }
} else {
    Info "Piper pulado (--SkipPiper)"
}

# ── 4. Sox (opcional) ──────────────────────────────────────────────────────────
Step "4/6" "Verificando Sox (opcional — necessário apenas para ajuste de pitch)..."
if (-not $SkipSox) {
    $soxExe = Get-Command sox.exe -ErrorAction SilentlyContinue
    if ($soxExe) {
        Ok "Sox já instalado: $($soxExe.Path)"
    } else {
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        $choco  = Get-Command choco  -ErrorAction SilentlyContinue
        if ($winget) {
            Info "Instalando Sox via winget..."
            try {
                winget install --id SoX.SoX --accept-source-agreements --accept-package-agreements --silent
                Ok "Sox instalado via winget"
            } catch { Warn "Falhou via winget. Sox é opcional." }
        } elseif ($choco) {
            Info "Instalando Sox via Chocolatey..."
            try {
                choco install sox -y | Out-Null
                Ok "Sox instalado via choco"
            } catch { Warn "Falhou via choco. Sox é opcional." }
        } else {
            Warn "Sox não encontrado. É opcional — usado apenas se pitch_semitones != 0."
        }
    }
} else {
    Info "Sox pulado (--SkipSox)"
}

# ── 5. OpenWakeWord models ─────────────────────────────────────────────────────
Step "5/6" "Baixando modelos OpenWakeWord..."
try {
    python -c "import openwakeword; openwakeword.utils.download_models()" 2>$null
    Ok "Modelos OpenWakeWord baixados"
} catch {
    Warn "Não foi possível baixar modelos OpenWakeWord automaticamente."
    Warn "Rode manualmente: python -c `"import openwakeword; openwakeword.utils.download_models()`""
}

# ── 6. Config ──────────────────────────────────────────────────────────────────
Step "6/6" "Configuração..."
$configFile = "$ScriptDir\config.yaml"
if (-not (Test-Path $configFile)) {
    Copy-Item "$ScriptDir\config.yaml.example" $configFile
    Ok "config.yaml criado a partir do exemplo"
} else {
    Ok "config.yaml já existe (não sobrescrito)"
}

# ── Verificar Ollama ───────────────────────────────────────────────────────────
Write-Host ""
Write-Host "── Verificando Ollama..." -ForegroundColor White
if (-not $SkipOllama) {
    $ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($ollamaCmd) {
        Ok "Ollama encontrado"
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:11434/api/version" -UseBasicParsing -ErrorAction Stop
            Ok "Ollama está rodando"
            $models = ollama list 2>$null | Select-Object -Skip 1 | ForEach-Object { $_.Split()[0] }
            if ($models) { Info "Modelos disponíveis: $($models -join ', ')" }
        } catch {
            Warn "Ollama não está rodando. Inicie com: ollama serve"
        }
    } else {
        Warn "Ollama não encontrado. Instale em: https://ollama.com"
    }
}

# ── Resultado final ─────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║      Instalação concluída!               ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "Próximos passos:" -ForegroundColor White
Write-Host ""
Write-Host "  1. Baixe um modelo no Ollama:"
Write-Host "       ollama pull gemma2:2b"
Write-Host "       ollama create mascote -f ..\mascote.mf   # personalidade pt-BR (opcional)"
Write-Host ""
Write-Host "  2. Edite o config.yaml se necessário:"
Write-Host "       notepad $configFile"
Write-Host ""
Write-Host "  3. Rode:" -ForegroundColor White
Write-Host "       python main.py --list-devices   # veja os dispositivos de áudio"
Write-Host "       python main.py                  # inicia (dashboard em localhost:3005)"
Write-Host ""
Write-Host "  4. Para testar sem wake word (pressione Enter para ativar):"
Write-Host "       Descomente 'fallback_mode: keyboard' no config.yaml"
Write-Host ""
Write-Host "  Dashboard web: http://localhost:3005" -ForegroundColor Cyan
Write-Host ""
