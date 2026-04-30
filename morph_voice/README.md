# morph_voice 🎙️

> Pipeline de voz 100% local: **Wake Word → TTS greeting → Whisper STT → Ollama → TTS response**
> Funciona offline, sem cloud, sem assinaturas.

```
┌──────────────┐    ┌──────────┐    ┌─────────┐    ┌─────────────┐    ┌──────────┐
│  Wake Word   │───▶│ Greeting │───▶│ Whisper │───▶│   Ollama    │───▶│  Piper   │
│ OpenWakeWord │    │  Piper   │    │  (STT)  │    │   (LLM)     │    │  (TTS)   │
└──────────────┘    └──────────┘    └─────────┘    └─────────────┘    └──────────┘
       ▲                                                                      │
       └──────────────────── loop (follow-up ou dormir) ◀────────────────────┘
```

---

## O que é

`morph_voice` é uma camada de voz local que conecta quatro componentes open-source:

| Componente | Tecnologia | Descrição |
|---|---|---|
| Wake Word | [OpenWakeWord](https://github.com/dscripka/openWakeWord) | Detecta a palavra de ativação via modelo ONNX |
| STT | [faster-whisper](https://github.com/guillaumekln/faster-whisper) | Transcrição em pt-BR local, sem internet |
| LLM | [Ollama](https://ollama.com) | Qualquer modelo local (ou API OpenAI-compatible) |
| TTS | [Piper](https://github.com/rhasspy/piper) | Voz sintética pt-BR, baixa latência, offline |

Inclui **dashboard web em tempo real** para monitorar e interagir via browser.

---

## Requisitos mínimos

- Python **3.10+**
- Ollama instalado e rodando
- ~2 GB livre em disco (modelos Whisper + Ollama)
- Microfone e caixas de som

---

## Instalação em 3 passos

### Linux / macOS

```bash
git clone <este-repo>
cd morph_voice
bash install.sh
```

### Windows

```powershell
# Abra o PowerShell como usuário normal (não precisa de admin)
cd morph_voice
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser   # apenas 1x
.\install.ps1
```

O script faz tudo automaticamente:
- Instala dependências Python
- Baixa e instala o Piper TTS
- Baixa os modelos do OpenWakeWord
- Cria o `config.yaml` pronto para uso
- Verifica se o Ollama está instalado

---

## Configuração

Edite o arquivo `config.yaml` (criado automaticamente pelo install):

### 1. Escolha o modelo Ollama

```yaml
agent:
  base_url: "http://localhost:11434/v1"
  model: "mascote"          # qualquer modelo do: ollama list
  api_key: "ollama"         # pode ser qualquer string para Ollama local
```

Para criar o modelo `mascote` (personalidade pt-BR com sotaque goiano):
```bash
ollama create mascote -f ../mascote.mf
```

Ou use qualquer modelo já instalado:
```bash
ollama list              # veja os modelos disponíveis
# phi3, llama3.2, gemma2:2b, qwen2.5...
```

### 2. Wake Word

```yaml
wake_word:
  model_path: "../wake_word_models/central.onnx"   # seu modelo customizado
  threshold: 0.5
  # fallback_mode: "keyboard"   # descomente para testar sem modelo
```

> **Sem modelo ainda?** Descomente `fallback_mode: keyboard` e pressione Enter para ativar.

### 3. Voz (TTS Piper)

```yaml
tts:
  model_path: "../piper_models/nanda_ptbr.onnx"   # modelo de voz
  length_scale: 0.95     # velocidade: 0.8 = mais rápido, 1.2 = mais lento
  pitch_semitones: 0     # tom: +2 = mais agudo, -2 = mais grave (requer sox)
  volume: 1.0
```

> Outros modelos Piper pt-BR: [Hugging Face — rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices/tree/main/pt/pt_BR)

### 4. Reconhecimento de voz (Whisper)

```yaml
stt:
  model: "small"       # tiny (rápido) | base | small (recomendado) | medium | large-v3
  language: "pt"
  device: "auto"       # auto = usa GPU se disponível
```

---

## Rodando

```bash
cd morph_voice

# Ver dispositivos de áudio disponíveis
python main.py --list-devices

# Iniciar (com dashboard em localhost:3005)
python main.py

# Especificar microfone pelo índice
python main.py --device 2

# Porta diferente para o dashboard
python main.py --port 8080

# Sem dashboard
python main.py --no-dashboard
```

Acesse o dashboard: **http://localhost:3005**

---

## Dashboard Web

Abra `http://localhost:3005` no browser enquanto o pipeline roda:

```
┌────────────────────────────────────────────────┐
│  morph_voice          ● LISTENING              │
├────────────────────────────────────────────────┤
│  [SLEEPING]                          13:42:01  │
│  [GREETING]                          13:42:02  │
│  você disse   como funciona isso aqui?         │
│  morph        Uai, mô do céu! É simples...     │
│  [SLEEPING]                          13:42:15  │
├────────────────────────────────────────────────┤
│  [ Digite para injetar mensagem... ] [Enviar]  │
└────────────────────────────────────────────────┘
```

- **Estados em tempo real** com badge colorido
- **Histórico da conversa** — o que você falou e o que a IA respondeu
- **Injetar mensagem** — manda texto direto sem precisar falar (bypassa wake word)

---

## Fluxo de estados

```
SLEEPING ──(wake word detectada)──▶ GREETING
                                        │
                                        ▼
                                    LISTENING ──(silêncio)──▶ SLEEPING
                                        │ (fala detectada)
                                        ▼
                                    WAITING (toca frase de espera)
                                        │
                                     PROCESSING (chama Ollama)
                                        │
                                        ▼
                                    RESPONDING (Piper fala a resposta)
                                        │
                                        ▼
                                    FOLLOWUP ──(silêncio 5s)──▶ SLEEPING
                                        │ (nova fala)
                                        └──────────▶ WAITING (loop)
```

---

## Trocar de provider (LLM)

Use a flag `--provider` para trocar rapidamente:

```bash
# Ollama local (padrão)
python main.py --provider ollama

# OpenRouter (quando tiver API key)
set OPENROUTER_API_KEY=sk-or-...      # Windows
export OPENROUTER_API_KEY=sk-or-...   # Linux/macOS
python main.py --provider openrouter

# Hermes Agent (self-hosted)
python main.py --provider hermes
```

Ou edite diretamente o `config.yaml` para qualquer API OpenAI-compatible:

```yaml
# LM Studio
agent:
  base_url: "http://localhost:1234/v1"
  model: "local-model"
  api_key: "lm-studio"

# OpenAI
agent:
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o-mini"
  api_key: "sk-..."

# Groq (ultra-rápido, requer conta free)
agent:
  base_url: "https://api.groq.com/openai/v1"
  model: "llama-3.1-8b-instant"
  api_key: "gsk_..."
```

---

## Personalizar a voz e personalidade

### Criar seu próprio modelo Ollama

Edite o arquivo `../mascote.mf` (Modelfile do Ollama):

```
FROM gemma2:2b
PARAMETER temperature 0.9
SYSTEM """
Aqui você define a personalidade do assistente.
Exemplos: tom formal, casual, engraçado, técnico...
Mantenha as respostas curtas (2-3 frases) para o TTS não demorar.
"""
```

Depois:
```bash
ollama create meu-assistente -f ../mascote.mf
# Atualize agent.model no config.yaml
```

### Trocar a voz do Piper

1. Baixe um modelo em [Hugging Face — rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices/tree/main/pt/pt_BR)
2. Coloque o `.onnx` e o `.onnx.json` em `../piper_models/`
3. Atualize `tts.model_path` no `config.yaml`

### Ajustar velocidade e tom

```yaml
tts:
  length_scale: 0.85    # 20% mais rápido
  pitch_semitones: 2    # 2 semitons mais agudo (requer sox instalado)
```

---

## Troubleshooting

**Piper não encontrado**
```bash
# Teste se está no PATH:
piper --version        # Linux/macOS
piper.exe --version    # Windows

# Ou especifique o caminho completo no config.yaml:
tts:
  piper_binary: "C:/Users/seu-usuario/AppData/Local/piper/piper/piper.exe"
```

**Microfone errado**
```bash
python main.py --list-devices
# Anote o índice do seu microfone
python main.py --device 3
# Ou salve no config.yaml:
# audio:
#   input_device: 3
```

**Wake word não detecta / detecta errado**
```yaml
# Aumente o threshold para menos falsos positivos (0.5 a 0.9):
wake_word:
  threshold: 0.7

# Ou use modo teclado para testar o resto do pipeline:
wake_word:
  fallback_mode: "keyboard"
```

**Whisper lento**
```yaml
# Use modelo menor:
stt:
  model: "tiny"     # mais rápido, menos preciso
  model: "base"     # bom custo-benefício
  device: "cuda"    # force GPU se tiver NVIDIA
```

**Ollama não responde / demora muito**
```bash
# Verifique se está rodando:
ollama list
ollama ps

# Teste direto:
curl http://localhost:11434/v1/models

# Se demorar muito (cold start), aumente o timeout no config.yaml:
agent:
  # O timeout padrão é 240s — suficiente para a maioria dos casos
```

**Erro de áudio no Linux**
```bash
sudo apt install libportaudio2 portaudio19-dev
# Adicione seu usuário ao grupo audio:
sudo usermod -a -G audio $USER
# Faça logout e login novamente
```

**Windows: erro de Unicode no terminal**
```bash
# O pipeline já configura UTF-8 automaticamente.
# Se ainda tiver problemas:
chcp 65001
python main.py
```

---

## Estrutura de arquivos

```
morph_voice/
├── main.py              # Entry point + máquina de estados
├── config.py            # Carrega e valida config.yaml
├── wake_word.py         # Detecção OpenWakeWord (ONNX)
├── tts_piper.py         # Piper TTS subprocess wrapper
├── stt_whisper.py       # faster-whisper STT
├── agent_client.py      # HTTP client OpenAI-compat
├── audio_player.py      # Playback cross-platform
├── phrases.py           # 20 saudações + 20 esperas pt-BR
├── web_dashboard.py     # Dashboard web (FastAPI + SSE)
├── config.yaml          # Sua configuração (gitignored)
├── config.yaml.example  # Template de configuração
├── requirements.txt     # Dependências Python
├── install.sh           # Setup automático Linux/macOS
└── install.ps1          # Setup automático Windows

../piper_models/
└── nanda_ptbr.onnx      # Modelo de voz pt-BR (+ .json)

../wake_word_models/
└── central.onnx         # Modelo de wake word (substitua pelo seu)

../mascote.mf            # Modelfile Ollama — personalidade do assistente
```

---

## Integração com aplicações externas (avatares, VTubing, etc.)

O pipeline expõe saída de áudio padrão do sistema. Para sincronizar com avatares:

1. **Capture a saída de áudio** do sistema enquanto o Piper fala
2. **Monitore os eventos SSE** do dashboard em `http://localhost:3005/events`:

```javascript
const es = new EventSource('http://localhost:3005/events');
es.onmessage = (e) => {
  const ev = JSON.parse(e.data);
  if (ev.type === 'tts')   { /* Piper começou a falar — ative animação */ }
  if (ev.type === 'state' && ev.state === 'SLEEPING') { /* parou de falar */ }
  if (ev.type === 'response') { /* texto completo da resposta do LLM */ }
};
```

3. **Injete contexto** via `POST http://localhost:3005/send` com `{ "text": "..." }` para que o assistente responda a eventos externos (doações, follows, etc.)

---

## Licença

MIT — faça o que quiser, mas dá crédito se distribuir. 😄
