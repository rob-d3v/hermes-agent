"""
Wake word detection using OpenWakeWord.

Modes:
  custom   — load a custom .onnx model (e.g. avatar.onnx)
  builtin  — use a built-in openwakeword model (e.g. hey_jarvis)
  keyboard — press ENTER to activate (dev/test mode)
"""
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

CHUNK = 1280  # 80ms @ 16kHz — required by openwakeword


class WakeWordDetector:
    """Listens on the microphone and blocks until the wake word is detected."""

    def __init__(
        self,
        model_path: str,
        threshold: float = 0.5,
        cooldown_seconds: float = 2.0,
        vad_rms_min: int = 50,
        fallback_mode: Optional[str] = None,
        input_device: Optional[int] = None,
        show_scores: bool = False,
    ) -> None:
        self.model_path = model_path
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self.vad_rms_min = vad_rms_min
        self.input_device = input_device
        self.show_scores = show_scores
        self._stop_event = threading.Event()

        # Determine mode
        import os
        if fallback_mode == "keyboard":
            self.mode = "keyboard"
        elif os.path.isfile(model_path):
            self.mode = "custom"
        else:
            logger.warning(
                "Wake word model not found: %s. Falling back to keyboard mode.",
                model_path,
            )
            self.mode = "keyboard"

        if self.mode != "keyboard":
            self._init_oww()

    def _init_oww(self) -> None:
        """Initialize openwakeword model."""
        try:
            import openwakeword
            from openwakeword.model import Model
        except ImportError:
            logger.warning(
                "openwakeword not installed. Falling back to keyboard mode. "
                "Install with: pip install openwakeword"
            )
            self.mode = "keyboard"
            return

        try:
            if self.mode == "custom":
                logger.info("Loading custom wake word model: %s", self.model_path)
                self._oww = Model(wakeword_models=[self.model_path], inference_framework="onnx")
            else:
                logger.info("Loading builtin wake word model: %s", self.model_path)
                self._oww = Model(wakeword_models=[self.model_path], inference_framework="onnx")
        except Exception as e:
            logger.warning(
                "Failed to load wake word model (%s). Falling back to keyboard mode.", e
            )
            self.mode = "keyboard"

    def wait_for_wakeword(self) -> None:
        """Block until wake word is detected. Raises KeyboardInterrupt on stop()."""
        self._stop_event.clear()

        if self.mode == "keyboard":
            self._wait_keyboard()
        else:
            self._wait_oww()

    def stop(self) -> None:
        """Signal the detector to stop waiting."""
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Keyboard fallback
    # ------------------------------------------------------------------

    def _wait_keyboard(self) -> None:
        import platform
        import sys
        import threading

        logger.info("[keyboard mode] Press ENTER to activate the assistant...")
        print("\n[Wake Word] Pressione ENTER para ativar o assistente...", flush=True)

        entered = threading.Event()

        def _read_stdin():
            try:
                sys.stdin.readline()
                entered.set()
            except Exception:
                entered.set()

        reader = threading.Thread(target=_read_stdin, daemon=True)
        reader.start()

        while not self._stop_event.is_set():
            if entered.wait(timeout=0.2):
                logger.info("Keyboard activation triggered.")
                return

        raise KeyboardInterrupt

    # ------------------------------------------------------------------
    # OpenWakeWord loop
    # ------------------------------------------------------------------

    def _wait_oww(self) -> None:
        try:
            import pyaudio
            import numpy as np
        except ImportError:
            logger.error("pyaudio or numpy not installed. Cannot run wake word detection.")
            self._wait_keyboard()
            return

        pa = pyaudio.PyAudio()
        stream_kwargs = {
            "format": pyaudio.paInt16,
            "channels": 1,
            "rate": 16000,
            "input": True,
            "frames_per_buffer": CHUNK,
        }
        if self.input_device is not None:
            stream_kwargs["input_device_index"] = self.input_device

        stream = pa.open(**stream_kwargs)
        last_detection = 0.0
        logger.info("Listening for wake word (mode=%s, threshold=%.2f)...", self.mode, self.threshold)

        try:
            while not self._stop_event.is_set():
                try:
                    raw = stream.read(CHUNK, exception_on_overflow=False)
                except OSError as e:
                    logger.debug("Audio read error: %s", e)
                    time.sleep(0.05)
                    continue

                audio_chunk = np.frombuffer(raw, dtype=np.int16)

                # VAD gate
                rms = int(np.sqrt(np.mean(audio_chunk.astype(np.float64) ** 2)))
                if rms < self.vad_rms_min:
                    continue

                # Run prediction
                self._oww.predict(audio_chunk)
                scores = self._oww.prediction_buffer

                if self.show_scores:
                    for model_name, preds in scores.items():
                        if preds:
                            logger.info("WW [%s]: %.3f", model_name, preds[-1])

                # Check threshold
                now = time.monotonic()
                if now - last_detection < self.cooldown_seconds:
                    continue

                for model_name, preds in scores.items():
                    if preds and preds[-1] >= self.threshold:
                        logger.info(
                            "Wake word detected! model=%s score=%.3f",
                            model_name,
                            preds[-1],
                        )
                        last_detection = now
                        # Clear buffer to avoid re-triggering
                        self._oww.prediction_buffer.clear()
                        return

        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

        if self._stop_event.is_set():
            raise KeyboardInterrupt
