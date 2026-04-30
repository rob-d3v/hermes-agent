# morph_voice — Hermes Voice Pipeline

Pipeline de voz local para qualquer agente OpenAI-compatible.

```
Wake Word (morph.onnx) → Greeting TTS (Piper) → STT (Whisper) → Hermes/Ollama → Response TTS (Piper) → loop
```

---

## O que é

`morph_voice` é uma camada de voz completamente local que conecta:

- **Detecção de wake word** — OpenWakeWord com modelo ONNX customizável
- **TTS** — Piper (voz pt-BR, baixa latência, offline)
- **STT** — faster-whisper (pt-BR, roda local)
- **Agente** — qualquer API OpenAI-compatible (Ollama, Hermes, LM Studio, etc.)

Funciona em **Windows e Linux** sem depender de nenhum serviço cloud.

---

## Requisitos

- Python 3.10+
- [Ollama](https://ollama.com) rodando com o modelo `mascote` (ou qualquer modelo)
- [Piper TTS](https://github.com/rhasspy/piper) instalado no PATH
- Modelo de voz Piper: `piper_models/nanda_ptbr.onnx`
- Modelo de wake word: `wake_word_models/central.onnx` (ou `morph.onnx` quando treinado)

---

## Instalação rápida

### Linux / macOS

```bash
cd morph_voice
bash install.sh
```

O script instala deps Python, PortAudio, Sox e Piper automaticamente.

### Windows

```powershell
cd morph_voice
.\install.ps1
```

O script instala deps Python, baixa Piper para `%LOCALAPPDATA%\piper`, e opcionalmente instala Sox via winget/choco.

### Manual (qualquer SO)

```bash
pip install -r requirements.txt
# Instale piper e sox conforme documentação oficial
cp config.yaml.example config.yaml
# Edite config.yaml
```

---

## Configuração

Copie `config.yaml.example` para `config.yaml` e ajuste:

| Parâmetro | Default | Descrição |
|---|---|---|
| `agent.base_url` | `http://localhost:11434/v1` | URL da API OpenAI-compat |
| `agent.model` | `mascote` | Nome do modelo |
| `agent.history_turns` | `6` | Turnos de conversa mantidos |
| `agent.history_reset_minutes` | `10` | Reseta histórico após X min dormindo |
| `wake_word.model_path` | `../wake_word_models/central.onnx` | Modelo ONNX da wake word |
| `wake_word.threshold` | `0.5` | Score mínimo para ativação |
| `wake_word.fallback_mode` | `null` | `"keyboard"` para testar sem modelo |
| `tts.piper_binary` | `piper` | Binário do Piper (ou caminho absoluto) |
| `tts.model_path` | `../piper_models/nanda_ptbr.onnx` | Modelo de voz Piper |
| `tts.length_scale` | `0.95` | Velocidade (menor = mais rápido) |
| `tts.pitch_semitones` | `0` | Ajuste de pitch (requer sox) |
| `stt.model` | `base` | Modelo Whisper (`tiny`, `base`, `small`, `medium`) |
| `stt.language` | `pt` | Idioma do STT |
| `stt.followup_timeout_seconds` | `5.0` | Timeout de escuta antes de dormir |

---

## Rodando

```bash
cd morph_voice

# Listar dispositivos de áudio
python main.py --list-devices

# Iniciar com config padrão
python main.py

# Especificar config alternativo
python main.py --config /caminho/para/config.yaml

# Especificar dispositivo de microfone (índice do --list-devices)
python main.py --device 2
```

### Fluxo de estados

1. **DORMINDO** — detectando wake word
2. **GREETING** — toca frase de saudação aleatória em pt-BR
3. **OUVINDO** — grava áudio com detecção de silêncio (VAD)
4. **AGUARDANDO** — toca frase de espera enquanto chama o agente
5. **RESPONDENDO** — toca resposta do agente em chunks
6. **FOLLOW-UP** — ouve por mais input; se silêncio → volta a dormir

---

## Troubleshooting

**Microfone não detectado**
```
python main.py --list-devices
# Especifique o índice com --device N
```

**Piper não encontrado**
- Certifique-se de que `piper` (Linux/macOS) ou `piper.exe` (Windows) está no PATH
- Ou especifique o caminho completo em `tts.piper_binary`

**Modelo de wake word não encontrado**
- O pipeline cai automaticamente para modo teclado (pressione ENTER para ativar)
- Configure `wake_word.fallback_mode: keyboard` em `config.yaml` para modo explícito

**Ollama não responde**
- Verifique se Ollama está rodando: `ollama list`
- Confirme o model name em `agent.model`
- Teste: `curl http://localhost:11434/v1/models`

**Áudio travado / sem som**
- Linux: instale `libportaudio2` e verifique permissões de áudio
- Windows: certifique-se de que o microfone não está bloqueado por outro app

---

## Distribuindo para outros usuários

1. Compartilhe esta pasta `morph_voice/`
2. O usuário precisa ter Ollama rodando com qualquer modelo
3. Configure `agent.base_url` e `agent.model` conforme o setup do usuário
4. Execute `install.sh` ou `install.ps1`

---

## Integrando com outros agentes

Altere apenas a seção `agent` em `config.yaml`:

```yaml
# LM Studio (porta padrão)
agent:
  base_url: "http://localhost:1234/v1"
  model: "local-model"
  api_key: "lm-studio"

# OpenAI
agent:
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o-mini"
  api_key: "sk-..."
```

---

## Estrutura de arquivos

```
morph_voice/
├── main.py          # Entry point + state machine
├── config.py        # Carrega config.yaml
├── wake_word.py     # Detecção OpenWakeWord
├── tts_piper.py     # Piper TTS subprocess wrapper
├── stt_whisper.py   # faster-whisper STT
├── agent_client.py  # HTTP client OpenAI-compat
├── audio_player.py  # Playback cross-platform
├── phrases.py       # Frases pt-BR sotaque goiano
├── config.yaml.example
├── requirements.txt
├── install.sh       # Setup Linux/macOS
├── install.ps1      # Setup Windows
└── README.md
```
