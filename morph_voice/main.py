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
import time

# Force UTF-8 output on Windows (mascote uses emojis and accented chars)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from enum import Enum, auto
from pathlib import Path
from typing import Optional

# Add parent dir to path so morph_voice can run standalone
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
    )

    return wake, tts, stt, agent


def _set_state(state: State) -> State:
    dashboard.publish("state", state=state.name)
    return state


def run_pipeline(cfg: Config, input_device: Optional[int] = None) -> None:
    logger = logging.getLogger("morph_voice")

    wake, tts, stt, agent = _build_components(cfg, input_device)

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
            greeting = random_greeting()
            logger.info("[GREETING] %s", greeting)
            dashboard.publish("tts", text=greeting)
            tts.speak(greeting)
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
            waiting_msg = random_waiting()
            logger.info("[WAITING] %s", waiting_msg)
            dashboard.publish("tts", text=waiting_msg)

            # Start TTS in background thread while we call the agent
            tts_thread = tts.speak_async(waiting_msg)

            # Call agent while TTS plays
            logger.info("[PROCESSING] Enviando para o agente: %r", _pending_transcript[:80])
            dashboard.publish("state", state="PROCESSING")
            response = agent.chat(_pending_transcript)

            # Wait for waiting TTS to finish before playing response
            tts_thread.join(timeout=15)

            if shutdown:
                break

            state = _set_state(State.RESPONDING)
            _pending_response = response

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
        help="Caminho para config.yaml (default: morph_voice/config.yaml)",
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
        choices=["ollama", "openai", "hermes", "openrouter"],
        default=None,
        help=(
            "Provider do agente: "
            "ollama (local, padrão), "
            "openai (direto, requer OPENAI_API_KEY), "
            "hermes (localhost:8642, requer Hermes rodando), "
            "openrouter (requer OPENROUTER_API_KEY)"
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
    if args.provider == "ollama":
        cfg.agent.base_url = "http://localhost:11434/v1"
        cfg.agent.api_key = "ollama"
        cfg.agent.model = "mascote"
        cfg.agent.timeout = 240
    elif args.provider == "openai":
        cfg.agent.base_url = "https://api.openai.com/v1"
        cfg.agent.api_key = os.environ.get("OPENAI_API_KEY", "")
        cfg.agent.model = "gpt-4o-mini"
        cfg.agent.timeout = 30
        if not cfg.agent.api_key:
            print("ERRO: OPENAI_API_KEY não definida. Configure com:")
            print("  set OPENAI_API_KEY=sk-...   (Windows)")
            print("  export OPENAI_API_KEY=sk-... (Linux/macOS)")
            return
    elif args.provider == "hermes":
        cfg.agent.base_url = "http://localhost:8642/v1"
        cfg.agent.api_key = os.environ.get("HERMES_API_KEY", "aa6531e6c0db6b2fba53bb133fac2e0a")
        cfg.agent.model = "hermes-agent"
        cfg.agent.timeout = 60
    elif args.provider == "openrouter":
        cfg.agent.base_url = "https://openrouter.ai/api/v1"
        cfg.agent.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        cfg.agent.timeout = 30

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
