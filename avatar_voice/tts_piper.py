"""
Piper TTS wrapper.

Runs the piper binary as a subprocess, receives raw PCM audio,
and plays it via sounddevice (low latency) or writes a temp WAV fallback.

Raw audio spec for most Piper models: 22050 Hz, 16-bit signed, mono.
"""
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import wave
from typing import List, Optional

logger = logging.getLogger(__name__)

# Formas dialetais goianas que o espeak-ng não reconhece → substitui antes do TTS.
# O texto escrito no chat permanece inalterado; só o áudio usa a forma padrão.
_DIALECT_MAP = [
    # Pronomes goianos
    (r'\bocê\b',    'você'),
    (r'\bcê\b',     'você'),
    (r'\bprocê\b',  'pra você'),
    (r'\bprocês\b', 'pra vocês'),
    # Interjeições / marcadores
    (r'\banêim\b',  'aí'),
    (r'\bsô\b',     'só'),
    (r'\bmô\b',     'meu'),
    # Formas coloquiais goianas
    (r'\bvéi\b',    'velho'),
    (r'\bvéio\b',   'velho'),
    (r'\bvéia\b',   'velha'),
    (r'\bnóis\b',   'nós'),
    (r'\bmemo\b',   'mesmo'),
    (r'\bmermo\b',  'mesmo'),
    (r'\bcumé\b',   'como é'),
    (r'\bdum\b',    'de um'),
    (r'\bduma\b',   'de uma'),
    (r'\bprum\b',   'para um'),
    (r'\bpruma\b',  'para uma'),
    # Catch-all: remove circunflexo de ê e ô — espeak-ng pt-BR pronuncia
    # "voce", "tres", "cafe", "avo" corretamente sem o acento circunflexo.
    (r'ê',          'e'),
    (r'ô',          'o'),
]

# No Windows, esconde a janela de console dos subprocessos
_POPEN_FLAGS: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if sys.platform == "win32" else {}
)

# Piper raw output spec (validated against nanda_ptbr.onnx.json)
PIPER_SAMPLE_RATE = 22050
PIPER_CHANNELS = 1
PIPER_SAMPLE_WIDTH = 2  # int16


class PiperTTS:
    def __init__(
        self,
        piper_binary: str,
        model_path: str,
        length_scale: float = 0.95,
        noise_scale: float = 0.667,
        noise_w: float = 0.8,
        pitch_semitones: int = 0,
        volume: float = 1.0,
        chunk_max_chars: int = 80,
        output_device: Optional[int] = None,
    ) -> None:
        self.piper_binary = piper_binary
        self.model_path = model_path
        self.length_scale = length_scale
        self.noise_scale = noise_scale
        self.noise_w = noise_w
        self.pitch_semitones = pitch_semitones
        self.volume = volume
        self.chunk_max_chars = chunk_max_chars
        self.output_device = output_device
        self._lock = threading.Lock()
        self._warm_proc = None
        self._warm_lock = threading.Lock()

        # Resolve binary
        resolved = shutil.which(piper_binary)
        if resolved:
            self.piper_binary = resolved
        elif os.path.isfile(piper_binary):
            self.piper_binary = piper_binary
        else:
            logger.warning("Piper binary not found: %s", piper_binary)

        if not os.path.isfile(model_path):
            logger.warning("Piper model not found: %s", model_path)

        # Pre-warm: launch piper now so model is loaded before first TTS call
        threading.Thread(target=self._start_warm_proc, daemon=True).start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def clean_text(text: str) -> str:
        """Remove emojis, markdown symbols and non-speakable chars before TTS."""
        # Normaliza formas dialetais que o espeak-ng não reconhece
        cleaned = text
        for pattern, replacement in _DIALECT_MAP:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

        # Strip emoji and pictograph Unicode blocks
        cleaned = re.sub(
            r"[\U0001F300-\U0001FAFF"   # misc symbols, emoticons, transport, etc.
            r"\U00002600-\U000027BF"    # misc symbols, dingbats
            r"\U0000FE00-\U0000FE0F"   # variation selectors
            r"\U0001F900-\U0001F9FF"   # supplemental symbols
            r"\u200d"                   # zero-width joiner
            r"]+",
            " ",
            cleaned,
        )
        # Remove markdown bullet/header lines (lines starting with #, >, -, *)
        cleaned = re.sub(r"(?m)^[#>*\-]+\s*", "", cleaned)
        # Remove inline markdown symbols: *, _, ~, `, |, \
        cleaned = re.sub(r"[*_~`|\\]", "", cleaned)
        # Remove URLs
        cleaned = re.sub(r"https?://\S+", "", cleaned)
        # Collapse extra whitespace and newlines
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def speak(self, text: str) -> None:
        """Speak text synchronously."""
        text = self.clean_text(text).strip()
        if not text:
            return
        with self._lock:
            self._speak_internal(text)

    def speak_async(self, text: str) -> threading.Thread:
        """Speak text in a daemon thread. Returns the thread."""
        t = threading.Thread(target=self.speak, args=(text,), daemon=True)
        t.start()
        return t

    def split_chunks(self, text: str) -> List[str]:
        """Split text into speakable chunks at sentence boundaries."""
        text = text.strip()
        if not text:
            return []

        # Split on sentence-ending punctuation
        parts = re.split(r'([.!?]+\s*)', text)
        raw_chunks: List[str] = []
        i = 0
        while i < len(parts):
            sentence = parts[i]
            punct = parts[i + 1] if i + 1 < len(parts) else ""
            combined = (sentence + punct).strip()
            if combined:
                raw_chunks.append(combined)
            i += 2

        # Handle remainder
        if len(parts) % 2 == 1 and parts[-1].strip():
            raw_chunks.append(parts[-1].strip())

        # Merge short chunks
        result: List[str] = []
        buf = ""
        for chunk in raw_chunks:
            if not buf:
                buf = chunk
            elif len(buf) + 1 + len(chunk) <= self.chunk_max_chars:
                buf += " " + chunk
            else:
                result.append(buf)
                buf = chunk
        if buf:
            result.append(buf)

        return result if result else [text]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _start_warm_proc(self) -> None:
        """Launch a piper process in background so the ONNX model is pre-loaded."""
        if not os.path.isfile(self.piper_binary) and not shutil.which(self.piper_binary):
            return
        try:
            cmd = self._build_piper_cmd()
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                **_POPEN_FLAGS,
            )
            with self._warm_lock:
                self._warm_proc = proc
            logger.debug("Piper warm process ready (pid=%d)", proc.pid)
        except Exception as e:
            logger.debug("Piper warm process failed: %s", e)

    def _take_warm_proc(self):
        """Return the pre-warmed piper process (or None) and launch the next one."""
        with self._warm_lock:
            proc = self._warm_proc
            self._warm_proc = None
        threading.Thread(target=self._start_warm_proc, daemon=True).start()
        return proc

    def _build_piper_cmd(self) -> List[str]:
        cmd = [
            self.piper_binary,
            "--model", self.model_path,
            "--output_raw",
            "--length_scale", str(self.length_scale),
            "--noise_scale", str(self.noise_scale),
            "--noise_w", str(self.noise_w),
        ]
        return cmd

    def _speak_internal(self, text: str) -> None:
        if not os.path.isfile(self.piper_binary) and not shutil.which(self.piper_binary):
            logger.error("Piper binary not available: %s", self.piper_binary)
            return

        piper_cmd = self._build_piper_cmd()
        logger.info("piper cmd: %s", " ".join(piper_cmd))

        if self._speak_via_stream(text, piper_cmd):
            return
        if self._speak_via_sounddevice(text, piper_cmd):
            return
        self._speak_via_wav(text, piper_cmd)

    def _speak_via_stream(self, text: str, piper_cmd: List[str]) -> bool:
        """Buffer piper PCM → optional numpy pitch shift → sd.OutputStream."""
        try:
            import sounddevice as sd
            import numpy as np
        except (ImportError, OSError):
            return False

        piper_proc = None
        try:
            # Prefer warm proc; fall back to fresh with stderr captured for diagnostics
            warm = self._take_warm_proc()
            if warm is not None and warm.poll() is None:
                piper_proc = warm
                stdout_data, _ = piper_proc.communicate(
                    input=text.encode("utf-8") + b"\n", timeout=30
                )
                stderr_text = ""
            else:
                piper_proc = subprocess.Popen(
                    piper_cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    **_POPEN_FLAGS,
                )
                stdout_data, stderr_raw = piper_proc.communicate(
                    input=text.encode("utf-8") + b"\n", timeout=30
                )
                stderr_text = stderr_raw.decode(errors="replace") if stderr_raw else ""

            if stderr_text:
                for line in stderr_text.splitlines():
                    if line.strip():
                        logger.info("piper stderr: %s", line.strip())

            if not stdout_data:
                logger.warning("piper produziu 0 bytes (returncode=%s)", piper_proc.returncode)
                return False

            audio_np = np.frombuffer(stdout_data, dtype=np.int16)
            logger.info("piper: %d amostras (%.2fs)  speed=%.2f",
                        len(audio_np), len(audio_np) / PIPER_SAMPLE_RATE, self.length_scale)

            # Pitch shift via numpy (sem dependência de sox)
            if self.pitch_semitones != 0:
                audio_np = self._pitch_shift_numpy(audio_np, self.pitch_semitones)
                logger.info("pitch aplicado: %+d semitones → %d amostras (%.2fs)",
                            self.pitch_semitones, len(audio_np),
                            len(audio_np) / PIPER_SAMPLE_RATE)

            if self.volume != 1.0:
                audio_np = np.clip(
                    audio_np.astype(np.float32) * self.volume, -32768, 32767
                ).astype(np.int16)

            self._play_numpy_audio(sd, np, audio_np)
            return True

        except Exception as e:
            logger.warning("Stream TTS falhou: %s", e)
            if piper_proc:
                try:
                    piper_proc.kill()
                except Exception:
                    pass
            return False

    def _speak_via_sounddevice(self, text: str, piper_cmd: List[str]) -> bool:
        """Stream raw PCM from piper → sounddevice. Returns True on success."""
        try:
            import sounddevice as sd
            import numpy as np
        except (ImportError, OSError):
            return False

        try:
            piper_proc = subprocess.Popen(
                piper_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                **_POPEN_FLAGS,
            )

            # If sox pitch adjustment requested, pipe through sox
            if self.pitch_semitones != 0 and shutil.which("sox"):
                piper_proc, audio_source = self._add_sox_pipe(piper_proc)
            else:
                if self.pitch_semitones != 0 and not shutil.which("sox"):
                    logger.debug("sox not found — pitch will use numpy fallback")
                audio_source = piper_proc

            # Send text to piper
            try:
                piper_proc.stdin.write(text.encode("utf-8") + b"\n")
                piper_proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

            # Read all raw PCM
            raw_audio = audio_source.stdout.read()

            if audio_source is not piper_proc:
                try:
                    audio_source.wait(timeout=15)
                except Exception:
                    pass
            piper_proc.wait(timeout=15)

            if not raw_audio:
                return False

            audio_np = np.frombuffer(raw_audio, dtype=np.int16)

            # Numpy pitch shift when sox not available
            if self.pitch_semitones != 0 and not shutil.which("sox"):
                audio_np = self._pitch_shift_numpy(audio_np, self.pitch_semitones)

            # Apply volume
            if self.volume != 1.0:
                audio_np = np.clip(
                    audio_np.astype(np.float32) * self.volume, -32768, 32767
                ).astype(np.int16)

            self._play_numpy_audio(sd, np, audio_np)
            return True

        except subprocess.TimeoutExpired:
            logger.warning("Piper TTS timed out")
            return False
        except Exception as e:
            logger.debug("sounddevice TTS path failed: %s", e)
            return False

    def _add_sox_pipe(self, piper_proc) -> tuple:
        """Insert sox for pitch shifting. Returns (piper_proc, sox_proc)."""
        semitones = self.pitch_semitones
        sox_cents = semitones * 100  # sox uses cents

        sox_cmd = [
            "sox",
            "-t", "raw", "-r", str(PIPER_SAMPLE_RATE), "-e", "signed", "-b", "16", "-c", "1", "-",
            "-t", "raw", "-r", str(PIPER_SAMPLE_RATE), "-e", "signed", "-b", "16", "-c", "1", "-",
            "pitch", str(sox_cents),
        ]
        sox_proc = subprocess.Popen(
            sox_cmd,
            stdin=piper_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            **_POPEN_FLAGS,
        )
        piper_proc.stdout.close()
        return piper_proc, sox_proc

    @staticmethod
    def _pitch_shift_numpy(audio: "np.ndarray", semitones: float) -> "np.ndarray":
        """Pitch shift via resampling (changes pitch + duration proportionally).
        Uses scipy if available, falls back to numpy linear interpolation."""
        try:
            import numpy as np
            ratio = 2.0 ** (semitones / 12.0)
            new_len = max(1, int(len(audio) / ratio))
            try:
                from scipy.signal import resample
                shifted = resample(audio.astype(np.float32), new_len)
            except ImportError:
                # Linear interpolation fallback — no scipy needed
                indices = np.linspace(0, len(audio) - 1, new_len)
                shifted = np.interp(indices, np.arange(len(audio)),
                                    audio.astype(np.float32))
            return np.clip(shifted, -32768, 32767).astype(np.int16)
        except Exception:
            return audio

    def _play_numpy_audio(self, sd, np, audio_np: "np.ndarray") -> None:
        """Play a mono int16 ndarray, converting to stereo if the device requires it."""
        try:
            dev_id = self.output_device
            if dev_id is None:
                dev_id = sd.default.device[1]
            info = sd.query_devices(dev_id)
            max_ch = int(info.get("max_output_channels", 2))
        except Exception:
            max_ch = 2

        # Cap at stereo; never below 1
        out_ch = max(1, min(max_ch, 2))

        if out_ch > PIPER_CHANNELS:
            # Mono → stereo: duplicate the single channel
            audio_np = np.column_stack([audio_np] * out_ch)

        out_kw = {"samplerate": PIPER_SAMPLE_RATE, "channels": out_ch, "dtype": "int16"}
        if self.output_device is not None:
            out_kw["device"] = self.output_device

        with sd.OutputStream(**out_kw) as stream:
            stream.write(audio_np)

    def _speak_via_wav(self, text: str, piper_cmd: List[str]) -> None:
        """Fallback: generate WAV file and play it."""
        import audio_player

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = tmp.name
        tmp.close()

        try:
            piper_proc = subprocess.Popen(
                piper_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                **_POPEN_FLAGS,
            )
            try:
                piper_proc.stdin.write(text.encode("utf-8") + b"\n")
                piper_proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

            raw_audio = piper_proc.stdout.read()
            piper_proc.wait(timeout=15)

            if not raw_audio:
                logger.warning("Piper produced no audio for: %r", text[:60])
                return

            with wave.open(tmp_path, "wb") as wf:
                wf.setnchannels(PIPER_CHANNELS)
                wf.setsampwidth(PIPER_SAMPLE_WIDTH)
                wf.setframerate(PIPER_SAMPLE_RATE)
                wf.writeframes(raw_audio)

            audio_player.play(tmp_path, output_device=self.output_device)

        except subprocess.TimeoutExpired:
            logger.warning("Piper WAV fallback timed out")
        except Exception as e:
            logger.error("Piper WAV fallback failed: %s", e)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
