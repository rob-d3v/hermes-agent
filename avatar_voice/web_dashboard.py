"""
Dashboard web para o avatar_voice pipeline.
Mostra o estado em tempo real via SSE e permite injetar mensagens de texto.

Uso interno: importado por main.py
"""
import json
import queue
import threading
from datetime import datetime
from typing import Generator

_event_queue: queue.Queue = queue.Queue(maxsize=200)
_inject_queue: queue.Queue = queue.Queue()


def publish(event_type: str, **data) -> None:
    """Publica um evento para o dashboard (chamado pelo pipeline)."""
    payload = {"type": event_type, "ts": datetime.now().strftime("%H:%M:%S"), **data}
    try:
        _event_queue.put_nowait(payload)
    except queue.Full:
        pass  # descarta se fila cheia


def get_injected() -> str | None:
    """Retorna mensagem injetada pelo dashboard (não bloqueia)."""
    try:
        return _inject_queue.get_nowait()
    except queue.Empty:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────────────────────────────────────

_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>avatar_voice</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Courier New', monospace; background: #0e0e14; color: #cdd6f4; height: 100vh; display: flex; flex-direction: column; }

  header { padding: 16px 24px; display: flex; align-items: center; gap: 20px; border-bottom: 1px solid #1e1e2e; }
  h1 { font-size: 1.2em; color: #89b4fa; letter-spacing: 2px; }

  #state-badge {
    padding: 6px 16px; border-radius: 20px; font-size: 0.85em; font-weight: bold;
    letter-spacing: 1px; transition: all 0.3s;
  }
  .SLEEPING  { background: #1e1e2e; color: #585b70; }
  .GREETING  { background: #2a1a3e; color: #cba6f7; }
  .LISTENING { background: #0d2b1f; color: #a6e3a1; }
  .WAITING   { background: #2b2014; color: #f9e2af; }
  .PROCESSING{ background: #1e1430; color: #89b4fa; }
  .RESPONDING{ background: #0d1f2b; color: #89dceb; }
  .FOLLOWUP  { background: #1a2b0d; color: #a6e3a1; }

  #dot { width: 10px; height: 10px; border-radius: 50%; background: #585b70; transition: background 0.3s; }
  .dot-active { background: #a6e3a1 !important; animation: pulse 1s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }

  #log {
    flex: 1; overflow-y: auto; padding: 16px 24px;
    display: flex; flex-direction: column; gap: 8px;
  }

  .entry { padding: 8px 12px; border-radius: 6px; max-width: 85%; font-size: 0.9em; line-height: 1.4; }
  .entry-user      { background: #1e3a2b; color: #a6e3a1; align-self: flex-end; }
  .entry-assistant { background: #1a2550; color: #89b4fa; align-self: flex-start; }
  .entry-system    { background: transparent; color: #585b70; font-size: 0.75em; align-self: center; font-style: italic; }
  .entry-tts       { background: #1f1a2e; color: #cba6f7; align-self: flex-start; font-style: italic; }
  .label { font-size: 0.7em; opacity: 0.6; margin-bottom: 2px; }

  footer { padding: 12px 24px; border-top: 1px solid #1e1e2e; display: flex; gap: 10px; }
  #msg {
    flex: 1; background: #1e1e2e; color: #cdd6f4; border: 1px solid #313244;
    border-radius: 6px; padding: 10px 14px; font-size: 0.95em; font-family: inherit;
    outline: none;
  }
  #msg:focus { border-color: #89b4fa; }
  #msg::placeholder { color: #45475a; }
  button {
    background: #89b4fa; color: #1e1e2e; border: none; border-radius: 6px;
    padding: 10px 20px; cursor: pointer; font-weight: bold; font-family: inherit;
  }
  button:hover { background: #b4befe; }
  button:active { opacity: 0.8; }
</style>
</head>
<body>
<header>
  <h1>avatar_voice</h1>
  <div id="dot"></div>
  <div id="state-badge" class="SLEEPING">SLEEPING</div>
</header>

<div id="log"></div>

<footer>
  <input id="msg" placeholder="Injetar mensagem (bypassa wake word)..." autocomplete="off" />
  <button onclick="sendMsg()">Enviar</button>
</footer>

<script>
const log = document.getElementById('log');
const badge = document.getElementById('state-badge');
const dot = document.getElementById('dot');

function addEntry(cls, label, text) {
  const wrap = document.createElement('div');
  wrap.className = 'entry ' + cls;
  if (label) {
    const l = document.createElement('div');
    l.className = 'label';
    l.textContent = label;
    wrap.appendChild(l);
  }
  const t = document.createElement('div');
  t.textContent = text;
  wrap.appendChild(t);
  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
}

const ACTIVE = new Set(['GREETING','LISTENING','WAITING','PROCESSING','RESPONDING','FOLLOWUP']);

const es = new EventSource('/events');
es.onmessage = (e) => {
  const ev = JSON.parse(e.data);
  if (ev.type === 'ping') return;

  if (ev.type === 'state') {
    badge.textContent = ev.state;
    badge.className = ev.state;
    dot.className = ACTIVE.has(ev.state) ? 'dot-active' : '';
    addEntry('entry-system', null, ev.ts + '  →  ' + ev.state);
  } else if (ev.type === 'transcript') {
    addEntry('entry-user', 'você disse', ev.text);
  } else if (ev.type === 'response') {
    addEntry('entry-assistant', 'avatar', ev.text);
  } else if (ev.type === 'tts') {
    addEntry('entry-assistant', 'avatar', ev.text);
  } else if (ev.type === 'inject') {
    addEntry('entry-user', 'injetado via dashboard', ev.text);
  }
};
es.onerror = () => {
  addEntry('entry-system', null, 'conexão perdida — reconectando...');
};

function sendMsg() {
  const input = document.getElementById('msg');
  const text = input.value.trim();
  if (!text) return;
  fetch('/send', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({text})
  });
  input.value = '';
}

document.getElementById('msg').addEventListener('keydown', e => {
  if (e.key === 'Enter') sendMsg();
});
</script>
</body>
</html>"""


def _build_app():
    try:
        from fastapi import FastAPI
        from fastapi.responses import HTMLResponse, StreamingResponse
        from pydantic import BaseModel
    except ImportError:
        return None

    app = FastAPI(docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return _HTML

    def _stream() -> Generator:
        while True:
            try:
                ev = _event_queue.get(timeout=15)
                yield f"data: {json.dumps(ev)}\n\n"
            except queue.Empty:
                yield 'data: {"type":"ping"}\n\n'

    @app.get("/events")
    def events():
        return StreamingResponse(_stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    class Msg(BaseModel):
        text: str

    @app.post("/send")
    def send(msg: Msg):
        text = msg.text.strip()
        if text:
            _inject_queue.put(text)
            publish("inject", text=text)
        return {"ok": True}

    return app


def start(port: int = 3005) -> bool:
    """Inicia o dashboard em background thread. Retorna True se iniciou com sucesso."""
    try:
        import uvicorn
    except ImportError:
        return False

    app = _build_app()
    if app is None:
        return False

    def _run():
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return True
