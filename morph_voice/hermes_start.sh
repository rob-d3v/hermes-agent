#!/usr/bin/env bash
# hermes_start.sh — Inicia o Hermes com o provider escolhido
#
# Uso:
#   bash hermes_start.sh                    # usa OpenAI (padrão)
#   bash hermes_start.sh openai             # OpenAI   (requer OPENAI_API_KEY)
#   bash hermes_start.sh ollama             # Ollama local
#   bash hermes_start.sh openrouter         # OpenRouter (requer OPENROUTER_API_KEY)
#   bash hermes_start.sh down               # para o Hermes
#   bash hermes_start.sh status             # mostra status

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_ROOT="$(dirname "$SCRIPT_DIR")"
PROVIDER="${1:-openai}"

GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; CYAN="\033[0;36m"; NC="\033[0m"
ok()   { echo -e "${GREEN}  [OK] $*${NC}"; }
warn() { echo -e "${YELLOW}  [!]  $*${NC}"; }
info() { echo -e "${CYAN}   ->  $*${NC}"; }
err()  { echo -e "${RED}  [X]  $*${NC}"; }

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║          Hermes Agent — Control          ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── Verificar docker ────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    err "Docker não encontrado. Instale: https://docs.docker.com/get-docker/"
    exit 1
fi

# ── Status ──────────────────────────────────────────────────────────────────
if [[ "$PROVIDER" == "status" ]]; then
    info "Status dos containers:"
    docker compose -f "$HERMES_ROOT/docker-compose.yml" \
                   -f "$HERMES_ROOT/docker-compose.override.yml" ps 2>/dev/null || true
    echo ""
    info "Config atual do Hermes:"
    python3 "$SCRIPT_DIR/hermes_configure.py" show
    exit 0
fi

# ── Down ────────────────────────────────────────────────────────────────────
if [[ "$PROVIDER" == "down" ]]; then
    info "Parando Hermes..."
    cd "$HERMES_ROOT"
    docker compose down
    ok "Hermes parado."
    exit 0
fi

# ── Validar provider ─────────────────────────────────────────────────────────
if [[ ! "$PROVIDER" =~ ^(openai|ollama|openrouter)$ ]]; then
    err "Provider inválido: $PROVIDER"
    echo "  Opções: openai | ollama | openrouter | down | status"
    exit 1
fi

# ── Resolver API key ─────────────────────────────────────────────────────────
EXTRA_ARGS=()
if [[ "$PROVIDER" == "openai" ]]; then
    KEY="${OPENAI_API_KEY:-}"
    if [[ -z "$KEY" ]]; then
        err "OPENAI_API_KEY não definida."
        echo "  Configure com: export OPENAI_API_KEY='sk-...'"
        exit 1
    fi
    ok "OPENAI_API_KEY encontrada"
    EXTRA_ARGS+=(--key "$KEY")
elif [[ "$PROVIDER" == "openrouter" ]]; then
    KEY="${OPENROUTER_API_KEY:-}"
    if [[ -z "$KEY" ]]; then
        err "OPENROUTER_API_KEY não definida."
        echo "  Configure com: export OPENROUTER_API_KEY='sk-or-...'"
        exit 1
    fi
    ok "OPENROUTER_API_KEY encontrada"
    EXTRA_ARGS+=(--key "$KEY")
fi

# ── Configurar Hermes ────────────────────────────────────────────────────────
info "Configurando Hermes para: ${PROVIDER^^}"
python3 "$SCRIPT_DIR/hermes_configure.py" "$PROVIDER" "${EXTRA_ARGS[@]}"

# ── Subir docker compose ─────────────────────────────────────────────────────
info "Iniciando containers..."
cd "$HERMES_ROOT"
docker compose down 2>/dev/null || true
docker compose up -d

# ── Aguardar API server ──────────────────────────────────────────────────────
info "Aguardando API server (localhost:8642)..."
ATTEMPTS=0
MAX=15
READY=false
while [[ $ATTEMPTS -lt $MAX ]]; do
    sleep 2
    ATTEMPTS=$((ATTEMPTS + 1))
    HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer aa6531e6c0db6b2fba53bb133fac2e0a" \
        "http://localhost:8642/v1/models" --max-time 3 2>/dev/null || echo "000")
    if [[ "$HTTP" == "200" ]]; then
        READY=true
        break
    fi
    printf "   ... aguardando (%d/%d)\r" "$ATTEMPTS" "$MAX"
done
echo ""

if $READY; then
    ok "Hermes API rodando em http://localhost:8642"
    ok "Dashboard em     http://localhost:9119"
    echo ""
    echo "  Para usar com morph_voice:"
    echo -e "    ${CYAN}python3 main.py --provider hermes${NC}"
    echo ""
    echo "  Para parar:"
    echo -e "    ${CYAN}bash hermes_start.sh down${NC}"
else
    warn "API server ainda não respondeu após $((MAX * 2))s."
    warn "Verifique com: docker logs hermes"
fi
echo ""
