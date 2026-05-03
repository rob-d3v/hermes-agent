"""
Frases de saudação e espera em pt-BR com sotaque goiano.
Usadas pelo pipeline de voz do Avatar.

Carrega de phrases.json (editável pela UI). Se o arquivo não existir,
usa os defaults hardcoded e cria o JSON.
"""
import json
import random
from collections import deque
from pathlib import Path
from typing import List

_PHRASES_PATH = Path(__file__).parent / "phrases.json"

# Fallback mínimo caso o JSON não exista e não possa ser criado
_DEFAULT_GREETINGS: List[str] = [
    "Uai, tô aqui! Pode falar.",
    "Oi! Em que posso te ajudar hoje?",
    "Ocê me chamou? Tô ouvindo.",
    "Pois não! Diga o que quiser.",
    "Oi! Pode falar, tô todo ouvido.",
]

_DEFAULT_WAITINGS: List[str] = [
    "Uai, deixa eu pensar aqui...",
    "Só um instante, tô buscando isso pra você.",
    "Hmm, deixa eu ver...",
    "Aguenta aí, tô processando.",
    "Um momentinho, tá chegando.",
]


def _load_phrases() -> dict:
    if _PHRASES_PATH.exists():
        try:
            with open(_PHRASES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "greetings": data.get("greetings") or _DEFAULT_GREETINGS,
                "waitings": data.get("waitings") or _DEFAULT_WAITINGS,
            }
        except Exception:
            pass
    return {"greetings": list(_DEFAULT_GREETINGS), "waitings": list(_DEFAULT_WAITINGS)}


def save_phrases(greetings: List[str], waitings: List[str]) -> None:
    with open(_PHRASES_PATH, "w", encoding="utf-8") as f:
        json.dump({"greetings": greetings, "waitings": waitings},
                  f, ensure_ascii=False, indent=2)


class PhrasePool:
    """Seleciona frases aleatórias sem repetição imediata."""

    def __init__(self, phrases: List[str]) -> None:
        self._pool = list(phrases)
        self._queue: deque = deque()
        self._shuffle_into_queue()

    def _shuffle_into_queue(self) -> None:
        shuffled = list(self._pool)
        random.shuffle(shuffled)
        self._queue.extend(shuffled)

    def reload(self, phrases: List[str]) -> None:
        self._pool = list(phrases)
        self._queue.clear()
        self._shuffle_into_queue()

    def next(self) -> str:
        if not self._queue:
            self._shuffle_into_queue()
        return self._queue.popleft()


_data = _load_phrases()
_greeting_pool = PhrasePool(_data["greetings"])
_waiting_pool = PhrasePool(_data["waitings"])


def random_greeting() -> str:
    return _greeting_pool.next()


def random_waiting() -> str:
    return _waiting_pool.next()


def reload_phrases() -> None:
    data = _load_phrases()
    _greeting_pool.reload(data["greetings"])
    _waiting_pool.reload(data["waitings"])
