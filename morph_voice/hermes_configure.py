"""
hermes_configure.py — Reconfigura ~/.hermes/config.yaml para um provider específico.

Uso:
  python hermes_configure.py openai    --key sk-...   [--model gpt-4o-mini]
  python hermes_configure.py ollama                   [--model mascote]
  python hermes_configure.py openrouter --key sk-or-... [--model openai/gpt-4o-mini]
  python hermes_configure.py show      # mostra config atual
"""
import argparse
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERRO: PyYAML não instalado. Execute: pip install PyYAML")
    sys.exit(1)

HERMES_CONFIG = Path.home() / ".hermes" / "config.yaml"
HERMES_ENV    = Path.home() / ".hermes" / ".env"

PRESETS = {
    "openai": {
        "model":          "gpt-4o-mini",
        "provider":       "custom",
        "base_url":       "https://api.openai.com/v1",
        "context_length": 128000,
        "env_key":        "OPENAI_API_KEY",
        "toolsets":       ["hermes-cli"],
    },
    "ollama": {
        "model":          "mascote",
        "provider":       "custom",
        "base_url":       "http://host.docker.internal:11434/v1",
        "context_length": 65536,
        "env_key":        None,
        "api_key_value":  "ollama",
        "toolsets":       [],
    },
    "openrouter": {
        "model":          "openai/gpt-4o-mini",
        "provider":       "openrouter",
        "base_url":       "https://openrouter.ai/api/v1",
        "context_length": 128000,
        "env_key":        "OPENROUTER_API_KEY",
        "toolsets":       ["hermes-cli"],
    },
}


def load_config() -> dict:
    if not HERMES_CONFIG.exists():
        print(f"ERRO: {HERMES_CONFIG} não encontrado. Hermes instalado?")
        sys.exit(1)
    with open(HERMES_CONFIG, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_config(cfg: dict) -> None:
    with open(HERMES_CONFIG, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def update_env(key: str, value: str) -> None:
    """Adiciona ou atualiza uma variável no ~/.hermes/.env."""
    lines = []
    found = False
    if HERMES_ENV.exists():
        with open(HERMES_ENV, "r", encoding="utf-8") as f:
            lines = f.readlines()
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}\n")
    with open(HERMES_ENV, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    print(f"  .env: {key}=***{value[-4:]}")


def configure(provider_name: str, api_key: str | None, model_override: str | None) -> None:
    if provider_name not in PRESETS:
        print(f"ERRO: provider '{provider_name}' inválido. Opções: {', '.join(PRESETS)}")
        sys.exit(1)

    preset = PRESETS[provider_name]
    model = model_override or preset["model"]

    # Resolver API key
    resolved_key = api_key or ""
    if not resolved_key and preset.get("env_key"):
        resolved_key = os.environ.get(preset["env_key"], "")
    if not resolved_key:
        resolved_key = preset.get("api_key_value", "")

    if preset.get("env_key") and not resolved_key:
        print(f"AVISO: {preset['env_key']} não encontrada. Configure antes de iniciar o Hermes.")

    cfg = load_config()

    # Atualizar seção model
    cfg["model"] = {
        "default":        model,
        "provider":       preset["provider"],
        "base_url":       preset["base_url"],
        "context_length": preset["context_length"],
    }
    if resolved_key:
        cfg["model"]["api_key"] = resolved_key

    # Atualizar toolsets
    cfg["toolsets"] = preset["toolsets"]

    # Atualizar auxiliary.compression.context_length
    if "auxiliary" not in cfg or not isinstance(cfg.get("auxiliary"), dict):
        cfg["auxiliary"] = {}
    if "compression" not in cfg["auxiliary"] or not isinstance(cfg["auxiliary"].get("compression"), dict):
        cfg["auxiliary"]["compression"] = {}
    cfg["auxiliary"]["compression"]["context_length"] = preset["context_length"]

    save_config(cfg)

    # Persistir API key no .env se necessário
    if resolved_key and preset.get("env_key"):
        update_env(preset["env_key"], resolved_key)

    print(f"\n  Hermes configurado para: {provider_name.upper()}")
    print(f"  Modelo:    {model}")
    print(f"  Provider:  {preset['provider']}")
    print(f"  Base URL:  {preset['base_url']}")
    print(f"  Toolsets:  {preset['toolsets'] or '(nenhum)'}")
    print()


def show_config() -> None:
    cfg = load_config()
    m = cfg.get("model", {})
    print(f"\n  Config atual: {HERMES_CONFIG}")
    print(f"  Modelo:    {m.get('default', '?')}")
    print(f"  Provider:  {m.get('provider', '?')}")
    print(f"  Base URL:  {m.get('base_url', '?')}")
    print(f"  Context:   {m.get('context_length', 'auto')}")
    print(f"  Toolsets:  {cfg.get('toolsets', [])}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconfigura o Hermes para usar um provider de LLM diferente."
    )
    parser.add_argument(
        "provider",
        nargs="?",
        choices=[*PRESETS, "show"],
        default="show",
        help="Provider: openai | ollama | openrouter | show",
    )
    parser.add_argument("--key", "-k", default=None, help="API key do provider")
    parser.add_argument("--model", "-m", default=None, help="Sobrescrever o modelo padrão")
    args = parser.parse_args()

    if args.provider == "show":
        show_config()
    else:
        configure(args.provider, args.key, args.model)


if __name__ == "__main__":
    main()
