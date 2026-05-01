"""
STT using faster-whisper.

Records from microphone with sounddevice, detects silence via RMS,
and transcribes with faster-whisper.
"""
import logging
import os
import tempfile
import time
import wave
from typing import Optional

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
SAMPLE_WIDTH = 2

# Whisper hallucinations on silence (pt-BR common ones included)
_HALLUCINATIONS = {
    "obrigado.", "obrigado", "obrigada.", "obrigada",
    "até logo.", "até logo", "tchau.", "tchau",
    "thank you.", "thank you", "thanks for watching.",
    "bye.", "bye", "you", "the end.",
    "legenda", "legendas", "legendado",
    "produção", "produção musical",
    "amara.org", "www.mooji.org",
}


def _is_hallucination(text: str) -> bool:
    cleaned = text.strip().lower()
    if not cleaned:
        return True
    return cleaned in _HALLUCINATIONS or cleaned.rstrip(".!?") in _HALLUCINATIONS


class WhisperSTT:
    """Records audio and transcribes using faster-whisper."""

    def __init__(
        self,
        model: str = "base",
        language: str = "pt",
        device: str = "auto",
        silence_threshold_rms: int = 200,
        silence_duration_seconds: float = 1.5,
        max_session_seconds: float = 20.0,
        input_device: Optional[int] = None,
    ) -> None:
        self.model_name = model
        self.language = language
        self.device = device
        self.silence_threshold_rms = silence_threshold_rms
        self.silence_duration_seconds = silence_duration_seconds
        self.max_session_seconds = max_session_seconds
        self.input_device = input_device
        self._whisper_model = None

    def _load_model(self):
        if self._whisper_model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError(
                "faster-whisper not installed. Run: pip install faster-whisper"
            )
        logger.info("Loading faster-whisper model '%s'...", self.model_name)
        device = self.device if self.device != "auto" else "auto"
        compute = "auto" if device == "auto" else "int8"
        try:
            self._whisper_model = WhisperModel(
                self.model_name, device=device, compute_type=compute
            )
        except Exception as e:
            logger.warning(
                "faster-whisper load with device=%s failed (%s), retrying CPU", device, e
            )
            self._whisper_model = WhisperModel(
                self.model_name, device="cpu", compute_type="int8"
            )
        logger.info("faster-whisper model loaded.")

    def listen(self, timeout_seconds: Optional[float] = None) -> Optional[str]:
        """
        Record microphone until silence or timeout.

        Args:
            timeout_seconds: Override max session time (uses config default if None).

        Returns:
            Transcribed text, or None if nothing detected / hallucination.
        """
        import sounddevice as sd
        import numpy as np

        timeout = timeout_seconds if timeout_seconds is not None else self.max_session_seconds
        frames = []
        silence_start: Optional[float] = None
        has_spoken = False
        speech_start: Optional[float] = None
        start_time = time.monotonic()

        def callback(indata, frame_count, time_info, status):
            frames.append(indata.copy())

        stream_kwargs = {
            "samplerate": SAMPLE_RATE,
            "channels": CHANNELS,
            "dtype": DTYPE,
            "callback": callback,
        }
        if self.input_device is not None:
            stream_kwargs["device"] = self.input_device

        with sd.InputStream(**stream_kwargs):
            logger.debug("Recording started (timeout=%.1fs)", timeout)
            chunk_size = int(SAMPLE_RATE * 0.05)  # 50ms chunks

            while True:
                elapsed = time.monotonic() - start_time
                if elapsed >= timeout:
                    logger.debug("Recording timeout (%.1fs)", timeout)
                    break

                time.sleep(0.05)

                if not frames:
                    continue

                # Compute RMS of latest chunk
                latest = frames[-1]
                rms = int(np.sqrt(np.mean(latest.astype(np.float64) ** 2)))

                if rms > self.silence_threshold_rms:
                    # Speech detected
                    if speech_start is None:
                        speech_start = time.monotonic()
                    if not has_spoken and (time.monotonic() - speech_start) >= 0.3:
                        has_spoken = True
                        logger.debug("Speech confirmed (RMS=%d)", rms)
                    silence_start = None
                elif has_spoken:
                    # User was speaking, now silent
                    if silence_start is None:
                        silence_start = time.monotonic()
                    elif (time.monotonic() - silence_start) >= self.silence_duration_seconds:
                        logger.debug(
                            "Silence for %.1fs, stopping recording",
                            self.silence_duration_seconds,
                        )
                        break
                else:
                    # No speech yet, check max_wait
                    if elapsed >= timeout and speech_start is None:
                        logger.debug("No speech in %.1fs, aborting", elapsed)
                        break

        if not frames or not has_spoken:
            return None

        # Concatenate and write WAV
        audio = np.concatenate(frames, axis=0)
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = tmp.name
        tmp.close()

        try:
            with wave.open(tmp_path, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(SAMPLE_WIDTH)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(audio.tobytes())

            self._load_model()

            segments, info = self._whisper_model.transcribe(
                tmp_path,
                beam_size=5,
                language=self.language,
            )
            transcript = " ".join(seg.text.strip() for seg in segments).strip()
            logger.info(
                "Transcribed (%.1fs audio, lang=%s): %r",
                info.duration,
                info.language,
                transcript[:80],
            )

            if _is_hallucination(transcript):
                logger.debug("Filtered hallucination: %r", transcript)
                return None

            return transcript if transcript else None

        except Exception as e:
            logger.error("Transcription failed: %s", e)
            return None
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
