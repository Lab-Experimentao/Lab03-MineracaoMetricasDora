"""Change failure rate (RQ 03), variante (a): proxy de CI pelos workflow runs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

# Tabela de `conclusion` da seção 3; qualquer outro valor é ignorado.
CONCLUSOES_SUCESSO = frozenset({"success"})
CONCLUSOES_FALHA = frozenset({"failure", "timed_out", "startup_failure"})


class Resultado(Enum):
    SUCESSO = "sucesso"
    FALHA = "falha"


def classificar_conclusao(
    conclusao: str | None,
    sucesso: frozenset[str] = CONCLUSOES_SUCESSO,
    falha: frozenset[str] = CONCLUSOES_FALHA,
) -> Resultado | None:
    """Sucesso, falha ou None (cancelled, skipped, em andamento etc. não entram no cálculo)."""
    if conclusao in sucesso:
        return Resultado.SUCESSO
    if conclusao in falha:
        return Resultado.FALHA
    return None


@dataclass(frozen=True)
class CFR:
    taxa: float | None
    falhas: int
    sucessos: int
    ignorados: int


def cfr_ci(
    conclusoes: Iterable[str | None],
    sucesso: frozenset[str] = CONCLUSOES_SUCESSO,
    falha: frozenset[str] = CONCLUSOES_FALHA,
) -> CFR:
    """Falhas ÷ (falhas + sucessos) sobre todos os workflows juntos; None sem runs válidos."""
    falhas = sucessos = ignorados = 0
    for conclusao in conclusoes:
        resultado = classificar_conclusao(conclusao, sucesso, falha)
        if resultado is Resultado.FALHA:
            falhas += 1
        elif resultado is Resultado.SUCESSO:
            sucessos += 1
        else:
            ignorados += 1
    validos = falhas + sucessos
    return CFR(falhas / validos if validos else None, falhas, sucessos, ignorados)
