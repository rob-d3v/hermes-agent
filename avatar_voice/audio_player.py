"""
Cross-platform audio playback for WAV files.
Priority: sounddevice → pyaudio → aplay (Linux) → afplay (macOS) → ffplay
"""
import logging
import os
import platform
import shutil
import subprocess
import time
import wave
from typing import Optional

logger = logging.getLogger(__name__)


def play(path: str, output_device: Optional[int] = None) -> bool:
    """Play a WAV file synchronously. Returns True on success."""
    if not os.path.isfile(path):
        logger.warning("Audio file not found: %s", path)
        return False

    # 1. sounddevice (cross-platform, best quality)
    if _play_sounddevice(path, output_device):
        return True

    # 2. System players
    system = platform.system()
    players = []
    if system == "Linux":
        players.append(["aplay", "-q", path])
    elif system == "Darwin":
        players.append(["afplay", path])
    players.append(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path])

    for cmd in players:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, timeout=120, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
                logger.debug("Player %s failed: %s", cmd[0], e)

    logger.warning("No audio player available for %s", path)
    return False


def _play_sounddevice(path: str, output_device: Optional[int] = None) -> bool:
    try:
        import sounddevice as sd
        import numpy as np
    except (ImportError, OSError):
        return False

    try:
        with wave.open(path, "rb") as wf:
            n_channels = wf.getnchannels()
            sample_rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())

        audio = np.frombuffer(frames, dtype=np.int16)
        if n_channels > 1:
            audio = audio.reshape(-1, n_channels)

        kwargs = {"samplerate": sample_rate}
        if output_device is not None:
            kwargs["device"] = output_device

        sd.play(audio, **kwargs)
        duration = len(audio) / (sample_rate * n_channels if n_channels > 1 else sample_rate)
        deadline = time.monotonic() + duration + 3.0
        while sd.get_stream() and sd.get_stream().active:
            if time.monotonic() > deadline:
                break
            time.sleep(0.01)
        sd.stop()
        return True
    except Exception as e:
        logger.debug("sounddevice playback failed: %s", e)
        return False


def list_devices() -> str:
    """Return a formatted string listing available audio devices."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        lines = ["Available audio devices:"]
        for i, d in enumerate(devices):
            marker = ""
            if i == sd.default.device[0]:
                marker = " [default input]"
            elif i == sd.default.device[1]:
                marker = " [default output]"
            in_ch = d.get("max_input_channels", 0)
            out_ch = d.get("max_output_channels", 0)
            lines.append(
                f"  [{i:2d}] {d['name']}  "
                f"(in={in_ch}, out={out_ch}){marker}"
            )
        return "\n".join(lines)
    except (ImportError, OSError) as e:
        return f"sounddevice not available: {e}"
