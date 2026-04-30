#!/usr/bin/env bash
# Hermes Voice Pipeline — Instalação Linux/macOS
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPER_DIR="$HOME/.local/bin"
PIPER_VERSION="2023.11.14-2"

echo "=== Hermes Voice Pipeline — Setup ==="
echo ""

# ── Python deps ────────────────────────────────────────────────────────────
echo "[1/4] Instalando dependências Python..."
pip install -r "$SCRIPT_DIR/requirements.txt"
echo "      OK"

# ── PortAudio (sounddevice dep) ────────────────────────────────────────────
echo "[2/4] Verificando PortAudio..."
OS="$(uname -s)"
if [[ "$OS" == "Linux" ]]; then
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y libportaudio2 portaudio19-dev sox
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y portaudio-devel sox
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm portaudio sox
    else
        echo "      AVISO: instale libportaudio2 e sox manualmente para sua distro."
    fi
elif [[ "$OS" == "Darwin" ]]; then
    if command -v brew &>/dev/null; then
        brew install portaudio sox
    else
        echo "      AVISO: instale Homebrew e depois: brew install portaudio sox"
    fi
fi
echo "      OK"

# ── Piper TTS binary ──────────────────────────────────────────────────────
echo "[3/4] Verificando Piper TTS..."
if command -v piper &>/dev/null; then
    echo "      Piper já instalado: $(which piper)"
else
    echo "      Baixando Piper $PIPER_VERSION..."
    ARCH="$(uname -m)"
    mkdir -p "$PIPER_DIR"

    if [[ "$OS" == "Linux" ]]; then
        if [[ "$ARCH" == "x86_64" ]]; then
            PIPER_ARCHIVE="piper_linux_x86_64.tar.gz"
        elif [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; then
            PIPER_ARCHIVE="piper_linux_aarch64.tar.gz"
        else
            echo "      AVISO: Arquitetura $ARCH não suportada. Baixe Piper manualmente."
            PIPER_ARCHIVE=""
        fi
    elif [[ "$OS" == "Darwin" ]]; then
        PIPER_ARCHIVE="piper_macos_x86_64.tar.gz"
    else
        PIPER_ARCHIVE=""
    fi

    if [[ -n "$PIPER_ARCHIVE" ]]; then
        TMP=$(mktemp -d)
        curl -fsSL \
            "https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/${PIPER_ARCHIVE}" \
            -o "$TMP/$PIPER_ARCHIVE"
        tar -xzf "$TMP/$PIPER_ARCHIVE" -C "$TMP"
        cp "$TMP/piper/piper" "$PIPER_DIR/piper"
        chmod +x "$PIPER_DIR/piper"
        rm -rf "$TMP"
        echo "      Piper instalado em $PIPER_DIR/piper"
        echo "      Certifique-se de que $PIPER_DIR está no seu PATH."
    fi
fi

# ── Config ────────────────────────────────────────────────────────────────
echo "[4/4] Configuração..."
CONFIG_FILE="$SCRIPT_DIR/config.yaml"
if [[ ! -f "$CONFIG_FILE" ]]; then
    cp "$SCRIPT_DIR/config.yaml.example" "$CONFIG_FILE"
    echo "      config.yaml criado a partir do exemplo."
    echo "      Edite $CONFIG_FILE para ajustar o modelo e caminhos."
else
    echo "      config.yaml já existe."
fi

echo ""
echo "=== Instalação concluída! ==="
echo ""
echo "Para iniciar:"
echo "  cd $SCRIPT_DIR"
echo "  python main.py --list-devices    # veja os dispositivos de áudio"
echo "  python main.py                   # inicia o pipeline"
echo ""
echo "Se o modelo de wake word ainda não existe, use fallback_mode: keyboard em config.yaml"
