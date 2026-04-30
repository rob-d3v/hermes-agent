#!/usr/bin/env bash
# morph_voice — Setup automático Linux/macOS
# Uso: bash install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPER_VERSION="2023.11.14-2"
PIPER_DIR="$HOME/.local/bin"

GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; NC="\033[0m"
ok()   { echo -e "${GREEN}  ✔ $*${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $*${NC}"; }
info() { echo -e "  → $*"; }

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║      morph_voice — Instalação            ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. Python ─────────────────────────────────────────────────────────────────
echo "[1/6] Verificando Python..."
if ! command -v python3 &>/dev/null; then
    warn "Python 3 não encontrado. Instale Python 3.10+ e rode novamente."
    exit 1
fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "Python $PY_VER encontrado"

# ── 2. PortAudio + Sox ────────────────────────────────────────────────────────
echo "[2/6] Instalando dependências de sistema..."
OS="$(uname -s)"
if [[ "$OS" == "Linux" ]]; then
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y -q libportaudio2 portaudio19-dev sox ffmpeg 2>/dev/null || warn "apt falhou — tente instalar libportaudio2 manualmente"
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y portaudio-devel sox ffmpeg 2>/dev/null || warn "dnf falhou"
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm portaudio sox ffmpeg 2>/dev/null || warn "pacman falhou"
    else
        warn "Instale libportaudio2 e sox manualmente para sua distro."
    fi
elif [[ "$OS" == "Darwin" ]]; then
    if command -v brew &>/dev/null; then
        brew install portaudio sox ffmpeg 2>/dev/null || warn "brew falhou"
    else
        warn "Instale Homebrew: https://brew.sh — depois: brew install portaudio sox"
    fi
fi
ok "Dependências de sistema verificadas"

# ── 3. Python packages ────────────────────────────────────────────────────────
echo "[3/6] Instalando pacotes Python..."
pip install -r "$SCRIPT_DIR/requirements.txt" -q
ok "Pacotes Python instalados"

# ── 4. Piper TTS ──────────────────────────────────────────────────────────────
echo "[4/6] Verificando Piper TTS..."
if command -v piper &>/dev/null; then
    ok "Piper já instalado: $(which piper)"
else
    info "Baixando Piper $PIPER_VERSION..."
    ARCH="$(uname -m)"
    PIPER_ARCHIVE=""
    if [[ "$OS" == "Linux" ]]; then
        [[ "$ARCH" == "x86_64" ]]  && PIPER_ARCHIVE="piper_linux_x86_64.tar.gz"
        [[ "$ARCH" == "aarch64" ]] && PIPER_ARCHIVE="piper_linux_aarch64.tar.gz"
    elif [[ "$OS" == "Darwin" ]]; then
        PIPER_ARCHIVE="piper_macos_x86_64.tar.gz"
    fi

    if [[ -n "$PIPER_ARCHIVE" ]]; then
        TMP=$(mktemp -d)
        curl -fsSL \
            "https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/${PIPER_ARCHIVE}" \
            -o "$TMP/$PIPER_ARCHIVE"
        tar -xzf "$TMP/$PIPER_ARCHIVE" -C "$TMP"
        mkdir -p "$PIPER_DIR"
        cp "$TMP/piper/piper" "$PIPER_DIR/piper"
        chmod +x "$PIPER_DIR/piper"
        rm -rf "$TMP"
        ok "Piper instalado em $PIPER_DIR/piper"
        if [[ ":$PATH:" != *":$PIPER_DIR:"* ]]; then
            warn "Adicione ao seu .bashrc ou .zshrc:"
            warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        fi
    else
        warn "Arquitetura $ARCH/$OS não suportada. Baixe em: https://github.com/rhasspy/piper/releases"
    fi
fi

# ── 5. OpenWakeWord models ────────────────────────────────────────────────────
echo "[5/6] Baixando modelos OpenWakeWord..."
python3 -c "
import sys
try:
    import openwakeword
    openwakeword.utils.download_models()
    print('  → Modelos OpenWakeWord baixados.')
except Exception as e:
    print(f'  ⚠ {e}')
" 2>/dev/null || warn "Não foi possível baixar modelos OpenWakeWord automaticamente."
ok "OpenWakeWord pronto"

# ── 6. Config ─────────────────────────────────────────────────────────────────
echo "[6/6] Configuração..."
CONFIG_FILE="$SCRIPT_DIR/config.yaml"
if [[ ! -f "$CONFIG_FILE" ]]; then
    cp "$SCRIPT_DIR/config.yaml.example" "$CONFIG_FILE"
    ok "config.yaml criado"
else
    ok "config.yaml já existe (não sobrescrito)"
fi

# ── Verificar Ollama ──────────────────────────────────────────────────────────
echo ""
echo "── Verificando Ollama..."
if command -v ollama &>/dev/null; then
    ok "Ollama encontrado: $(ollama --version 2>/dev/null | head -1)"
    if curl -s http://localhost:11434/api/version &>/dev/null; then
        ok "Ollama está rodando"
        MODELS=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' | tr '\n' ' ')
        [[ -n "$MODELS" ]] && info "Modelos disponíveis: $MODELS"
    else
        warn "Ollama não está rodando. Inicie com: ollama serve"
    fi
else
    warn "Ollama não encontrado. Instale em: https://ollama.com"
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║      Instalação concluída!               ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Próximos passos:"
echo ""
echo "  1. Inicie o Ollama e baixe um modelo:"
echo "     ollama pull gemma2:2b"
echo "     ollama create mascote -f ../mascote.mf   # opcional: personalidade pt-BR"
echo ""
echo "  2. Edite o config.yaml se necessário:"
echo "     nano $CONFIG_FILE"
echo ""
echo "  3. Rode:"
echo "     python3 main.py --list-devices   # veja os dispositivos de áudio"
echo "     python3 main.py                  # inicia (dashboard em localhost:3005)"
echo ""
echo "  4. Para testar sem wake word (pressione Enter para ativar):"
echo "     Descomente 'fallback_mode: keyboard' no config.yaml"
echo ""
