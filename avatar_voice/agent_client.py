"""
HTTP client for OpenAI-compatible chat completion APIs (Ollama, Hermes, etc).

Maintains a sliding-window conversation history.
"""
import logging
import time
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = (
    "Você é um mascote de stream sem filtro. "
    "Fala com sotaque de Goiás, usando expressões como 'uai', 'trem', 'anêim', 'tá doido' e 'mô do céu'. "
    "Seja engraçado, meio sarcástico e trate o pessoal como se fosse todo mundo de casa. "
    "Responda de forma breve e natural, em português brasileiro, como em uma conversa falada. "
    "NUNCA use emojis, asteriscos, underlines, cerquilhas, til, travessões, "
    "bullets, markdown ou qualquer símbolo especial. "
    "Escreva apenas texto simples, sem formatação. "
    "Máximo de 2 frases curtas por resposta."
)


class AgentClient:
    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        model: str = "mascote",
        api_key: str = "ollama",
        temperature: float = 0.9,
        max_tokens: int = 150,
        history_turns: int = 6,
        history_reset_minutes: int = 10,
        timeout: int = 240,
        system_prompt: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.history_turns = history_turns
        self.history_reset_minutes = history_reset_minutes
        self.timeout = timeout
        self.system_prompt = system_prompt.strip() or _DEFAULT_SYSTEM_PROMPT

        self._history: List[dict] = []
        self._last_interaction: Optional[float] = None
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    def chat(self, user_message: str) -> str:
        """
        Send a message and return the assistant's response text.
        Returns empty string on error.
        """
        user_message = user_message.strip()
        if not user_message:
            return ""

        # Reset history if idle too long
        if (
            self.history_reset_minutes > 0
            and self._last_interaction is not None
        ):
            idle_minutes = (time.monotonic() - self._last_interaction) / 60.0
            if idle_minutes >= self.history_reset_minutes:
                logger.info(
                    "History reset after %.1f minutes idle", idle_minutes
                )
                self._history = []

        self._history.append({"role": "user", "content": user_message})
        self._last_interaction = time.monotonic()

        # Build messages: system + sliding window
        max_pairs = max(1, self.history_turns)
        window = self._history[-(max_pairs * 2):]  # each turn = 1 user + 1 assistant

        messages = [{"role": "system", "content": self.system_prompt}] + window

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }

        url = f"{self.base_url}/chat/completions"
        logger.debug("POST %s  model=%s", url, self.model)
        try:
            response = self._session.post(url, json=payload, timeout=self.timeout)
            if not response.ok:
                logger.error(
                    "Agent HTTP %d at %s — body: %s",
                    response.status_code, url, response.text[:500],
                )
                self._history.pop()
                return ""
            data = response.json()

            text = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )

            if text:
                self._history.append({"role": "assistant", "content": text})
            else:
                logger.warning("Agent returned empty content. Full response: %s", data)
                self._history.pop()

            logger.info("Agent response (%d chars): %r", len(text), text[:80])
            return text

        except requests.exceptions.ConnectionError:
            logger.error("Cannot connect to agent at %s — server running?", self.base_url)
            self._history.pop()
            return ""
        except requests.exceptions.Timeout:
            logger.error("Agent request timed out after %ds at %s", self.timeout, url)
            self._history.pop()
            return ""
        except Exception as e:
            logger.error("Agent request failed: %s", e)
            self._history.pop()
            return ""

    def reset_history(self) -> None:
        """Clear conversation history."""
        self._history = []
        logger.debug("Conversation history cleared")
