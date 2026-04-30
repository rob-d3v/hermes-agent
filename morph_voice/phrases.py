"""
Frases de saudação e espera em pt-BR com sotaque goiano.
Usadas pelo pipeline de voz do Morpheus.
"""
import random
from collections import deque
from typing import List

# 20 saudações — tom informal goiano, sem emoji no texto falado
GREETINGS: List[str] = [
    "Uai, tô aqui! Pode falar.",
    "Oi! Em que posso te ajudar hoje?",
    "Ocê me chamou? Tô ouvindo.",
    "Pois não! Diga o que quiser.",
    "Oi! Pode falar, tô todo ouvido.",
    "Tô aqui sim! O que ocê precisa?",
    "Uai, me chamou? Pode falar.",
    "Oi! Estou à disposição, pode mandar.",
    "Sim! Tô te ouvindo, pode falar.",
    "Pois não! O que você gostaria de saber?",
    "Oi! Que bom te ouvir. Pode falar.",
    "Tô aqui, uai! Fala o que precisa.",
    "Oi! Estou pronto pra te ajudar.",
    "Uai! Pode falar, tô escutando.",
    "Oi! O que você tem pra me perguntar?",
    "Pois não! Estou aqui pra isso.",
    "Oi! Diga o que tá precisando.",
    "Tô aqui! Me conta o que você quer.",
    "Uai, boa! Pode perguntar à vontade.",
    "Oi! Tô de plantão, pode falar.",
]

# 20 mensagens de espera — enquanto processa a resposta
WAITINGS: List[str] = [
    "Uai, deixa eu pensar aqui...",
    "Só um instante, tô buscando isso pra você.",
    "Hmm, deixa eu ver...",
    "Aguenta aí, tô processando.",
    "Um momentinho, tá chegando.",
    "Uai, interessante! Deixa eu checar.",
    "Só um segundo, tô pensando aqui.",
    "Tô buscando a resposta, pode esperar.",
    "Deixa eu procurar isso pra você.",
    "Uai, boa pergunta! Um instante.",
    "Hmm, deixa eu raciocinar aqui.",
    "Só um instantinho, tá?",
    "Aguenta um segundo, tô verificando.",
    "Deixa eu pensar com calma...",
    "Uai, vou buscar isso agora.",
    "Um momento, tô consultando aqui.",
    "Só um segundo, já volto com a resposta.",
    "Tô pensando, pode aguardar.",
    "Uai, deixa eu ver o que tenho sobre isso.",
    "Hmm, aguenta aí que tô processando.",
]


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

    def next(self) -> str:
        if not self._queue:
            self._shuffle_into_queue()
        return self._queue.popleft()


_greeting_pool = PhrasePool(GREETINGS)
_waiting_pool = PhrasePool(WAITINGS)


def random_greeting() -> str:
    return _greeting_pool.next()


def random_waiting() -> str:
    return _waiting_pool.next()
