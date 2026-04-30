# morph_voice

Pipeline de voz local: **Wake Word → TTS → Whisper STT → LLM → TTS**

```
┌──────────────┐   ┌──────────┐   ┌─────────┐   ┌────────────┐   ┌──────────┐
│  Wake Word   │──▶│ Greeting │──▶│ Whisper │──▶│    LLM     │──▶│  Piper   │
│ OpenWakeWord │   │  Piper   │   │  (STT)  │   │ (sua escolha)│  │  (TTS)   │
└──────────────┘   └──────────┘   └─────────┘   └────────────┘   └──────────┘
       ▲                                                                 │
       └─────────────── loop (follow-up ou dormir) ◀───────────────────┘
```

Funciona **100% offline** com Ollama, ou conectado a qualquer API OpenAI-compatible.

---

## Modos de uso

| Modo | LLM | Requer | Ideal para |
|---|---|---|---|
| `--provider ollama` | Ollama local | Ollama instalado | Uso offline, privacidade |
| `--provider hermes` | Qualquer (via Hermes) | Docker + Hermes | Dashboard, histórico, múltiplos providers |
| `--provider openai` | OpenAI direto | `OPENAI_API_KEY` | Resposta rápida sem Hermes |
| `--provider openrouter` | OpenRouter | `OPENROUTER_API_KEY` | Acesso a múltiplos modelos |

---

## Instalação

### Pré-requisitos

- Python 3.10+
- Microfone e caixas de som

### Linux / macOS

```bash
cd morph_voice
bash install.sh
```

### Windows

```powershell
cd morph_voice
# Apenas na 1ª vez:
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
.\install.ps1
```

O script instala automaticamente: dependências Python, Piper TTS, modelos OpenWakeWord e cria o `config.yaml`.

---

## Modo 1 — Ollama local (offline, grátis)

### Passo 1 — Instale o Ollama

Baixe em **https://ollama.com** e instale normalmente.

Verifique:
```bash
ollama --version
```

### Passo 2 — Baixe um modelo

```bash
# Leve e rápido (recomendado para começar):
ollama pull gemma2:2b

# Opcional: criar a personalidade "mascote" (pt-BR, sotaque goiano):
ollama create mascote -f ../mascote.mf
```

> Sem o `mascote`, use qualquer modelo em `config.yaml` → `agent.model`.

### Passo 3 — Configure

Edite `config.yaml`:

```yaml
agent:
  base_url: "http://localhost:11434/v1"
  model: "mascote"    # ou gemma2:2b, llama3.2, phi3...
  api_key: "ollama"
  timeout: 240        # aumente se o modelo demorar para carregar
```

### Passo 4 — Rode

```bash
# Listar dispositivos de áudio (para saber o índice do mic)
python main.py --list-devices

# Iniciar
python main.py

# Ou explícito:
python main.py --provider ollama
```

Acesse o dashboard: **http://localhost:3005**

---

## Modo 2 — Hermes Agent (dashboard + qualquer LLM)

O Hermes roda em Docker e age como um "hub" entre o morph_voice e o LLM da sua escolha.
Todas as conversas aparecem no dashboard do Hermes em **http://localhost:9119**.

### Passo 1 — Instale o Docker Desktop

Baixe em **https://www.docker.com/products/docker-desktop** e inicie.

Verifique:
```bash
docker --version
```

### Passo 2 — Suba o Hermes

```bash
# Na raiz do repositório (hermes-agent/):
docker compose up -d
```

Aguarde os containers subirem:
```bash
docker compose ps
# hermes             running
# hermes-dashboard   running
```

### Passo 3 — Configure o LLM dentro do container

Com o container rodando, abra o wizard interativo do Hermes:

```bash
docker exec -it hermes hermes model
```

Vai aparecer um menu assim:
```
  Select inference provider
  ─────────────────────────
  ▶ OpenRouter         (OPENROUTER_API_KEY)
    OpenAI             (OPENAI_API_KEY)
    Anthropic          (ANTHROPIC_API_KEY)
    Ollama local       (custom endpoint)
    LM Studio          (custom endpoint)
    ...
```

Escolha o provider, insira a API key quando pedido, selecione o modelo e confirme.
A configuração é salva automaticamente em `~/.hermes/config.yaml`.

> **Dica:** Para o wizard completo (plataformas, memória, ferramentas):
> ```bash
> docker exec -it hermes hermes setup
> ```

### Passo 4 — Reinicie o gateway

Após configurar, reinicie para aplicar:

```bash
docker compose restart gateway
```

### Passo 5 — Verifique a API

```bash
curl http://localhost:8642/v1/models \
  -H "Authorization: Bearer aa6531e6c0db6b2fba53bb133fac2e0a"
# Deve retornar: {"object":"list","data":[{"id":"hermes-agent"...}]}
```

### Passo 6 — Rode o pipeline

```bash
python main.py --provider hermes
```

Acesse:
- Dashboard morph_voice: **http://localhost:3005**
- Dashboard Hermes: **http://localhost:9119**

### Parar o Hermes

```bash
docker compose down
```

---

## Modo 3 — OpenAI direto (sem Hermes)

Mais simples que o Hermes, sem dashboard de conversas.

```bash
# Windows
set OPENAI_API_KEY=sk-...
python main.py --provider openai

# Linux/macOS
export OPENAI_API_KEY=sk-...
python main.py --provider openai

# Trocar modelo:
python main.py --provider openai --model gpt-4o
```

---

## Trocar de provider rapidamente

A flag `--provider` aplica presets automáticos — não precisa editar o `config.yaml`:

```bash
python main.py --provider ollama       # Ollama local (padrão)
python main.py --provider openai       # OpenAI direto
python main.py --provider hermes       # Hermes Agent
python main.py --provider openrouter   # OpenRouter
```

Trocar modelo sem mudar o provider:
```bash
python main.py --provider ollama --model llama3.2
python main.py --provider openai --model gpt-4o
```

---

## Referência de configuração

### `config.yaml`

```yaml
agent:
  base_url: "http://localhost:11434/v1"  # URL da API
  model: "mascote"                        # nome do modelo
  api_key: "ollama"                       # API key (qualquer string para Ollama)
  temperature: 0.9                        # criatividade (0.0 a 1.0)
  max_tokens: 150                         # tamanho máximo da resposta
  history_turns: 6                        # turns de conversa mantidos
  history_reset_minutes: 10              # reseta histórico após X min dormindo
  timeout: 240                            # segundos (240 Ollama, 30 OpenAI)

wake_word:
  model_path: "../wake_word_models/central.onnx"
  threshold: 0.5                          # 0.0 a 1.0 (maior = menos falsos positivos)
  # fallback_mode: "keyboard"            # descomente para testar sem modelo (pressione Enter)

tts:
  model_path: "../piper_models/nanda_ptbr.onnx"
  length_scale: 0.95                     # velocidade: 0.8 = rápido, 1.2 = lento
  pitch_semitones: 0                     # tom: +2 agudo, -2 grave (requer sox)
  volume: 1.0

stt:
  model: "small"                          # tiny | base | small | medium | large-v3
  language: "pt"
  device: "auto"                          # auto | cpu | cuda
  followup_timeout_seconds: 5.0          # segundos de silêncio para dormir
```

### Flags da linha de comando

```bash
python main.py --help

  --provider, -p    ollama | openai | hermes | openrouter
  --model, -m       sobrescreve o modelo (ex: gpt-4o-mini)
  --device, -d      índice do microfone (ver --list-devices)
  --port            porta do dashboard web (padrão: 3005)
  --no-dashboard    desabilita o dashboard web
  --config, -c      caminho para config.yaml alternativo
  --list-devices    lista dispositivos de áudio e sai
```

---

## Dashboard web

Disponível em **http://localhost:3005** enquanto o pipeline roda.

- Estado atual do pipeline em tempo real (SLEEPING, LISTENING, PROCESSING...)
- Histórico da conversa (transcrições + respostas)
- Campo de texto para injetar mensagens sem precisar falar (bypassa wake word)

---

## Troubleshooting

**Wake word não detecta / detecta errado**
```yaml
# Aumente o threshold ou use modo teclado para testar:
wake_word:
  threshold: 0.7
  fallback_mode: "keyboard"   # pressione Enter para ativar
```

**Piper não encontrado**
```bash
# Verifique se está no PATH:
piper --version        # Linux/macOS
piper.exe --version    # Windows

# Ou especifique o caminho no config.yaml:
tts:
  piper_binary: "C:/Users/seu-usuario/AppData/Local/piper/piper/piper.exe"
```

**Microfone errado**
```bash
python main.py --list-devices
python main.py --device 3    # use o índice correto
```

**Ollama demora para responder**
```yaml
agent:
  timeout: 300   # aumente o timeout (segundos)
```

**Hermes: porta 8642 não responde**
```bash
# Verifique os logs:
docker logs hermes

# Verifique se o override de porta está aplicado:
docker port hermes
# deve mostrar: 8642/tcp -> 127.0.0.1:8642
```

**Hermes: erro "No LLM provider configured"**
```bash
# Configure o provider dentro do container:
docker exec -it hermes hermes model
docker compose restart gateway
```

**Erro de áudio no Linux**
```bash
sudo apt install libportaudio2 portaudio19-dev
sudo usermod -a -G audio $USER
# Faça logout e login novamente
```

---

## Estrutura de arquivos

```
morph_voice/
├── main.py               # Entry point + máquina de estados
├── config.py             # Carrega e valida config.yaml
├── wake_word.py          # Detecção OpenWakeWord (ONNX)
├── tts_piper.py          # Piper TTS wrapper
├── stt_whisper.py        # faster-whisper STT
├── agent_client.py       # HTTP client OpenAI-compat
├── audio_player.py       # Playback cross-platform
├── phrases.py            # 20 saudações + 20 esperas pt-BR
├── web_dashboard.py      # Dashboard web (FastAPI + SSE)
├── hermes_configure.py   # Reconfigura ~/.hermes/config.yaml (scripts/CI)
├── hermes_start.ps1      # Sobe Hermes com provider escolhido (Windows)
├── hermes_start.sh       # Sobe Hermes com provider escolhido (Linux/macOS)
├── config.yaml           # Sua configuração (não versionado)
├── config.yaml.example   # Template
├── requirements.txt      # Dependências Python
├── install.sh            # Setup automático Linux/macOS
└── install.ps1           # Setup automático Windows

../piper_models/
└── nanda_ptbr.onnx       # Modelo de voz pt-BR

../wake_word_models/
└── central.onnx          # Modelo de wake word

../mascote.mf             # Modelfile Ollama — personalidade pt-BR
```

---

## Integração com avatares e aplicações externas

O pipeline publica eventos via SSE em `http://localhost:3005/events`:

```javascript
const es = new EventSource('http://localhost:3005/events');
es.onmessage = (e) => {
  const ev = JSON.parse(e.data);
  if (ev.type === 'tts')      { /* Piper começou a falar */ }
  if (ev.type === 'response') { /* texto completo da resposta */ }
  if (ev.type === 'state')    { /* mudança de estado: ev.state */ }
};
```

Para injetar mensagens externamente (triggers de stream, doações, etc.):
```bash
curl -X POST http://localhost:3005/send \
  -H "Content-Type: application/json" \
  -d '{"text": "alguém doou 10 reais!"}'
```
