"""
Hermes Voice Pipeline — Entry Point

State machine:
  SLEEPING → GREETING → LISTENING → WAITING → PROCESSING → RESPONDING → LISTENING (follow-up) → SLEEPING
"""
import argparse
import logging
import os
import signal
import sys
import threading
import time

# Force UTF-8 output on Windows (mascote uses emojis and accented chars)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from enum import Enum, auto
from pathlib import Path
from typing import Optional

# Add parent dir to path so avatar_voice can run standalone
sys.path.insert(0, str(Path(__file__).parent))

from config import load_config, Config
from agent_client import AgentClient
from audio_player import list_devices
from phrases import random_greeting, random_waiting
from stt_whisper import WhisperSTT
from tts_piper import PiperTTS
from wake_word import WakeWordDetector
import web_dashboard as dashboard


class State(Enum):
    SLEEPING = auto()
    GREETING = auto()
    LISTENING = auto()
    WAITING = auto()
    PROCESSING = auto()
    RESPONDING = auto()
    FOLLOWUP = auto()


def _setup_logging(level: str) -> None:
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _build_components(cfg: Config, input_device: Optional[int]):
    """Instantiate all pipeline components from config."""
    device_override = input_device if input_device is not None else cfg.audio.input_device

    wake = WakeWordDetector(
        model_path=cfg.wake_word.model_path,
        threshold=cfg.wake_word.threshold,
        cooldown_seconds=cfg.wake_word.cooldown_seconds,
        vad_rms_min=cfg.wake_word.vad_rms_min,
        fallback_mode=cfg.wake_word.fallback_mode,
        input_device=device_override,
        show_scores=cfg.logging.show_scores,
        confirm_frames=cfg.wake_word.confirm_frames,
    )

    tts = PiperTTS(
        piper_binary=cfg.tts.piper_binary,
        model_path=cfg.tts.model_path,
        length_scale=cfg.tts.length_scale,
        noise_scale=cfg.tts.noise_scale,
        noise_w=cfg.tts.noise_w,
        pitch_semitones=cfg.tts.pitch_semitones,
        volume=cfg.tts.volume,
        chunk_max_chars=cfg.tts.chunk_max_chars,
        output_device=cfg.audio.output_device,
    )

    stt = WhisperSTT(
        model=cfg.stt.model,
        language=cfg.stt.language,
        device=cfg.stt.device,
        silence_threshold_rms=cfg.stt.silence_threshold_rms,
        silence_duration_seconds=cfg.stt.silence_duration_seconds,
        max_session_seconds=cfg.stt.max_session_seconds,
        input_device=device_override,
    )

    agent = AgentClient(
        base_url=cfg.agent.base_url,
        model=cfg.agent.model,
        api_key=cfg.agent.api_key,
        temperature=cfg.agent.temperature,
        max_tokens=cfg.agent.max_tokens,
        history_turns=cfg.agent.history_turns,
        history_reset_minutes=cfg.agent.history_reset_minutes,
        timeout=cfg.agent.timeout,
        system_prompt=cfg.agent.system_prompt,
        send_system_prompt=cfg.agent.send_system_prompt,
    )

    return wake, tts, stt, agent


def _set_state(state: State) -> State:
    dashboard.publish("state", state=state.name)
    return state


def run_pipeline(cfg: Config, input_device: Optional[int] = None) -> None:
    logger = logging.getLogger("avatar_voice")

    wake, tts, stt, agent = _build_components(cfg, input_device)

    # Pré-aquece o Whisper em background — sem bloquear a wake word
    threading.Thread(target=stt._load_model, daemon=True, name="whisper-warmup").start()

    state = State.SLEEPING
    shutdown = False
    _pending_transcript: str = ""
    _pending_response: str = ""

    def _handle_sigint(*_):
        nonlocal shutdown
        logger.info("Shutdown requested (Ctrl+C)")
        shutdown = True
        wake.stop()

    signal.signal(signal.SIGINT, _handle_sigint)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_sigint)

    logger.info("Hermes Voice Pipeline started. Model=%s  Wake word=%s",
                cfg.agent.model, cfg.wake_word.model_path)
    dashboard.publish("state", state=state.name)
    logger.info("State: SLEEPING — waiting for wake word...")

    while not shutdown:
        # ── SLEEPING ──────────────────────────────────────────────────
        if state == State.SLEEPING:
            # Check for message injected via web dashboard first
            injected = dashboard.get_injected()
            if injected:
                logger.info("[INJECT] Mensagem recebida do dashboard: %r", injected)
                _pending_transcript = injected
                state = _set_state(State.WAITING)
                continue

            try:
                wake.wait_for_wakeword()
            except KeyboardInterrupt:
                break
            if shutdown:
                break
            state = _set_state(State.GREETING)

        # ── GREETING ──────────────────────────────────────────────────
        elif state == State.GREETING:
            if cfg.agent.greetings_enabled:
                greeting = random_greeting()
                logger.info("[GREETING] %s", greeting)
                dashboard.publish("tts", text=greeting)
                tts.speak(greeting)
            else:
                logger.info("[GREETING] skipped (disabled)")
            state = _set_state(State.LISTENING)

        # ── LISTENING ─────────────────────────────────────────────────
        elif state == State.LISTENING:
            logger.info("[LISTENING] Ouvindo entrada do usuário...")
            transcript = stt.listen(timeout_seconds=cfg.stt.followup_timeout_seconds)

            if shutdown:
                break

            # Check for injected message even during listening
            injected = dashboard.get_injected()
            if injected:
                transcript = injected
                logger.info("[INJECT] Mensagem injetada durante listening: %r", injected)

            if not transcript:
                logger.info("[LISTENING] Silêncio detectado — voltando a dormir.")
                state = _set_state(State.SLEEPING)
            else:
                logger.info("[LISTENING] Capturado: %r", transcript)
                dashboard.publish("transcript", text=transcript)
                state = _set_state(State.WAITING)
                _pending_transcript = transcript

        # ── WAITING ───────────────────────────────────────────────────
        elif state == State.WAITING:
            dashboard.publish("state", state="PROCESSING")
            logger.info("[PROCESSING] Enviando para o agente: %r", _pending_transcript[:80])

            # Dispara o agent imediatamente, antes de qualquer TTS
            _result: list = [None]
            def _call_agent():
                _result[0] = agent.chat(_pending_transcript)
            agent_thread = threading.Thread(target=_call_agent, daemon=True)
            agent_thread.start()

            # Aguarda brevemente — se LLM já respondeu, pula a mensagem de espera
            agent_thread.join(timeout=1.0)
            if agent_thread.is_alive():
                if cfg.agent.waitings_enabled:
                    waiting_msg = random_waiting()
                    logger.info("[WAITING] %s", waiting_msg)
                    dashboard.publish("tts", text=waiting_msg)
                    tts.speak(waiting_msg)
                else:
                    logger.info("[WAITING] waiting message skipped (disabled)")
                # Aguarda o agent terminar (já estava processando enquanto TTS tocava)
                agent_thread.join(timeout=cfg.agent.timeout + 5)
            else:
                logger.info("[WAITING] LLM respondeu rápido — mensagem de espera ignorada.")

            if shutdown:
                break

            state = _set_state(State.RESPONDING)
            _pending_response = _result[0] or ""

        # ── RESPONDING ────────────────────────────────────────────────
        elif state == State.RESPONDING:
            if not _pending_response:
                logger.warning("[RESPONDING] Agente não retornou resposta.")
                error_msg = "Uai, não consegui processar isso agora. Pode tentar de novo?"
                dashboard.publish("tts", text=error_msg)
                tts.speak(error_msg)
                state = _set_state(State.SLEEPING)
            else:
                logger.info("[RESPONDING] Resposta: %r", _pending_response[:120])
                dashboard.publish("response", text=_pending_response)
                chunks = tts.split_chunks(_pending_response)
                for chunk in chunks:
                    if shutdown:
                        break
                    tts.speak(chunk)
                state = _set_state(State.FOLLOWUP)

        # ── FOLLOWUP ──────────────────────────────────────────────────
        elif state == State.FOLLOWUP:
            if shutdown:
                break
            logger.info("[FOLLOWUP] Ouvindo follow-up (%.1fs)...",
                        cfg.stt.followup_timeout_seconds)
            transcript = stt.listen(timeout_seconds=cfg.stt.followup_timeout_seconds)

            # Also accept injected follow-up
            injected = dashboard.get_injected()
            if injected:
                transcript = injected

            if not transcript:
                logger.info("[FOLLOWUP] Sem follow-up — voltando a dormir.")
                state = _set_state(State.SLEEPING)
            else:
                logger.info("[FOLLOWUP] Follow-up: %r", transcript)
                dashboard.publish("transcript", text=transcript)
                _pending_transcript = transcript
                state = _set_state(State.WAITING)

    logger.info("Pipeline encerrado. Até mais!")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hermes Voice Pipeline — wake word → STT → LLM → TTS"
    )
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Caminho para config.yaml (default: avatar_voice/config.yaml)",
    )
    parser.add_argument(
        "--device", "-d",
        type=int,
        default=None,
        help="Índice do dispositivo de microfone (ver --list-devices)",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="Lista dispositivos de áudio disponíveis e sai",
    )
    parser.add_argument(
        "--provider", "-p",
        default=None,
        help=(
            "Provider do agente (nome definido em config.yaml seção 'providers'). "
            "Built-ins: ollama, openai, hermes, openrouter, openclaw, n8n"
        ),
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help="Sobrescreve o modelo (ex: gpt-4o-mini, gpt-4o, llama3.2)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=3005,
        help="Porta do dashboard web (default: 3005)",
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Desabilita o dashboard web",
    )
    args = parser.parse_args()

    if args.list_devices:
        print(list_devices())
        return

    cfg = load_config(args.config)
    _setup_logging(cfg.logging.level)

    # Aplicar preset de provider se passado na linha de comando
    if args.provider:
        # Lookup: config.yaml providers > built-in presets
        import yaml as _yaml
        _BUILTIN = {
            "ollama":     {"model": "mascote",            "api_key": "ollama",                           "base_url": "http://localhost:11434/v1",      "timeout": 240},
            "openai":     {"model": "gpt-4o-mini",        "api_key": "",                                 "base_url": "https://api.openai.com/v1",     "timeout": 30},
            "hermes":     {"model": "hermes-agent",       "api_key": "aa6531e6c0db6b2fba53bb133fac2e0a", "base_url": "http://localhost:8642/v1",       "timeout": 60},
            "openrouter": {"model": "openai/gpt-4o-mini", "api_key": "",                                 "base_url": "https://openrouter.ai/api/v1",  "timeout": 30},
            "openclaw":   {"model": "openclaw/default",   "api_key": "",                                 "base_url": "http://localhost:18789/v1",      "timeout": 60},
            "n8n":        {"model": "default",            "api_key": "",                                 "base_url": "http://localhost:5678/webhook/v1", "timeout": 30},
        }
        _cfg_path = Path(args.config) if args.config else Path(__file__).parent / "config.yaml"
        _saved_provs = {}
        if _cfg_path.exists():
            with open(_cfg_path, "r", encoding="utf-8") as _f:
                _saved_provs = (_yaml.safe_load(_f) or {}).get("providers", {})
        _all = {**_BUILTIN, **_saved_provs}
        p = _all.get(args.provider)
        if p:
            cfg.agent.base_url = p.get("base_url", cfg.agent.base_url)
            cfg.agent.model = p.get("model", cfg.agent.model)
            cfg.agent.timeout = int(p.get("timeout", cfg.agent.timeout))
            key = p.get("api_key", "")
            # Allow env var override: <PROVIDER_NAME>_API_KEY
            env_key = os.environ.get(f"{args.provider.upper()}_API_KEY", "")
            cfg.agent.api_key = env_key or key or cfg.agent.api_key
        else:
            print(f"ERRO: Provider '{args.provider}' não encontrado.")
            print(f"Disponíveis: {', '.join(_all.keys())}")
            return

    # Sobrescrever modelo se passado explicitamente
    if args.model:
        cfg.agent.model = args.model

    # Iniciar dashboard web
    if not args.no_dashboard:
        ok = dashboard.start(port=args.port)
        if ok:
            print(f"Dashboard: http://localhost:{args.port}")
        else:
            print("Dashboard indisponível (instale: pip install fastapi uvicorn)")

    run_pipeline(cfg, input_device=args.device)


if __name__ == "__main__":
    main()
