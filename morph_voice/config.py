"""
Carrega e valida config.yaml para o pipeline morph_voice.
"""
import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    print("ERRO: PyYAML não instalado. Execute: pip install PyYAML", file=sys.stderr)
    sys.exit(1)

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"


@dataclass
class AgentConfig:
    base_url: str = "http://localhost:11434/v1"
    model: str = "mascote"
    api_key: str = "ollama"
    temperature: float = 0.9
    max_tokens: int = 150
    history_turns: int = 6
    history_reset_minutes: int = 10


@dataclass
class WakeWordConfig:
    model_path: str = "../wake_word_models/central.onnx"
    threshold: float = 0.5
    cooldown_seconds: float = 2.0
    vad_rms_min: int = 50
    fallback_mode: Optional[str] = None  # None | "keyboard"


@dataclass
class TTSConfig:
    piper_binary: str = ""  # auto-detected if empty
    model_path: str = "../piper_models/nanda_ptbr.onnx"
    length_scale: float = 0.95
    noise_scale: float = 0.667
    noise_w: float = 0.8
    pitch_semitones: int = 0
    volume: float = 1.0
    chunk_max_chars: int = 80


@dataclass
class STTConfig:
    model: str = "base"
    language: str = "pt"
    device: str = "auto"
    silence_threshold_rms: int = 200
    silence_duration_seconds: float = 1.5
    followup_timeout_seconds: float = 5.0
    max_session_seconds: float = 20.0


@dataclass
class AudioConfig:
    input_device: Optional[int] = None
    output_device: Optional[int] = None
    sample_rate: int = 16000


@dataclass
class LoggingConfig:
    level: str = "INFO"
    show_scores: bool = False


@dataclass
class Config:
    agent: AgentConfig = field(default_factory=AgentConfig)
    wake_word: WakeWordConfig = field(default_factory=WakeWordConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _detect_piper_binary() -> str:
    """Auto-detect piper binary name based on OS."""
    if platform.system() == "Windows":
        return "piper.exe"
    return "piper"


def _resolve_path(raw: str, base_dir: Path) -> str:
    """Resolve relative paths relative to the morph_voice directory."""
    p = Path(raw)
    if p.is_absolute():
        return str(p)
    return str((base_dir / p).resolve())


def load_config(config_path: Optional[str] = None) -> Config:
    """Load and validate config.yaml. Returns Config with defaults for missing keys."""
    if config_path:
        path = Path(config_path)
    else:
        path = _DEFAULT_CONFIG_PATH

    base_dir = Path(__file__).parent

    raw: dict = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    else:
        print(f"AVISO: config.yaml não encontrado em {path}. Usando defaults.", file=sys.stderr)

    def _get(d: dict, *keys, default=None):
        cur = d
        for k in keys:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(k, default)
        return cur

    # --- agent ---
    a = raw.get("agent", {}) or {}
    agent = AgentConfig(
        base_url=a.get("base_url", AgentConfig.base_url),
        model=a.get("model", AgentConfig.model),
        api_key=a.get("api_key", AgentConfig.api_key),
        temperature=float(a.get("temperature", AgentConfig.temperature)),
        max_tokens=int(a.get("max_tokens", AgentConfig.max_tokens)),
        history_turns=int(a.get("history_turns", AgentConfig.history_turns)),
        history_reset_minutes=int(a.get("history_reset_minutes", AgentConfig.history_reset_minutes)),
    )

    # --- wake_word ---
    ww = raw.get("wake_word", {}) or {}
    ww_model_raw = ww.get("model_path", WakeWordConfig.model_path)
    wake_word = WakeWordConfig(
        model_path=_resolve_path(ww_model_raw, base_dir),
        threshold=float(ww.get("threshold", WakeWordConfig.threshold)),
        cooldown_seconds=float(ww.get("cooldown_seconds", WakeWordConfig.cooldown_seconds)),
        vad_rms_min=int(ww.get("vad_rms_min", WakeWordConfig.vad_rms_min)),
        fallback_mode=ww.get("fallback_mode", WakeWordConfig.fallback_mode),
    )

    # --- tts ---
    t = raw.get("tts", {}) or {}
    tts_bin = t.get("piper_binary", "") or ""
    if not tts_bin:
        tts_bin = _detect_piper_binary()
    tts_model_raw = t.get("model_path", TTSConfig.model_path)
    tts = TTSConfig(
        piper_binary=tts_bin,
        model_path=_resolve_path(tts_model_raw, base_dir),
        length_scale=float(t.get("length_scale", TTSConfig.length_scale)),
        noise_scale=float(t.get("noise_scale", TTSConfig.noise_scale)),
        noise_w=float(t.get("noise_w", TTSConfig.noise_w)),
        pitch_semitones=int(t.get("pitch_semitones", TTSConfig.pitch_semitones)),
        volume=float(t.get("volume", TTSConfig.volume)),
        chunk_max_chars=int(t.get("chunk_max_chars", TTSConfig.chunk_max_chars)),
    )

    # --- stt ---
    s = raw.get("stt", {}) or {}
    stt = STTConfig(
        model=s.get("model", STTConfig.model),
        language=s.get("language", STTConfig.language),
        device=s.get("device", STTConfig.device),
        silence_threshold_rms=int(s.get("silence_threshold_rms", STTConfig.silence_threshold_rms)),
        silence_duration_seconds=float(s.get("silence_duration_seconds", STTConfig.silence_duration_seconds)),
        followup_timeout_seconds=float(s.get("followup_timeout_seconds", STTConfig.followup_timeout_seconds)),
        max_session_seconds=float(s.get("max_session_seconds", STTConfig.max_session_seconds)),
    )

    # --- audio ---
    au = raw.get("audio", {}) or {}
    input_dev = au.get("input_device", None)
    output_dev = au.get("output_device", None)
    audio = AudioConfig(
        input_device=int(input_dev) if input_dev is not None else None,
        output_device=int(output_dev) if output_dev is not None else None,
        sample_rate=int(au.get("sample_rate", AudioConfig.sample_rate)),
    )

    # --- logging ---
    lg = raw.get("logging", {}) or {}
    logging_cfg = LoggingConfig(
        level=lg.get("level", LoggingConfig.level).upper(),
        show_scores=bool(lg.get("show_scores", LoggingConfig.show_scores)),
    )

    return Config(
        agent=agent,
        wake_word=wake_word,
        tts=tts,
        stt=stt,
        audio=audio,
        logging=logging_cfg,
    )
