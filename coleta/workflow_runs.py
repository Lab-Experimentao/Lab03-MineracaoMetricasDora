"""Coleta de workflow runs do default branch, com a janela dividida em meses (seção 4)."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import chain
from typing import Any

from coleta.modelos import RunColetado
from pipeline.config import Janela

log = logging.getLogger(__name__)

# Com filtros, a listagem de runs devolve no máximo 1.000 resultados por consulta.
LIMITE_RESULTADOS = 1000


@dataclass(frozen=True)
class Intervalo:
    """Consulta feita: `total` é o total_count; `truncado` indica que nem tudo coube."""

    inicio: date
    fim: date
    total: int
    truncado: bool


def meses_da_janela(janela: Janela) -> list[tuple[date, date]]:
    """Intervalos inclusivos de cada mês civil, recortados pelos limites da janela."""
    meses = []
    inicio = janela.inicio
    while inicio <= janela.fim:
        proximo_mes = (inicio.replace(day=1) + timedelta(days=32)).replace(day=1)
        fim = min(proximo_mes - timedelta(days=1), janela.fim)
        meses.append((inicio, fim))
        inicio = fim + timedelta(days=1)
    return meses


def dividir(inicio: date, fim: date) -> tuple[tuple[date, date], tuple[date, date]] | None:
    """Divide um intervalo inclusivo ao meio; None se ele tem um único dia."""
    if inicio >= fim:
        return None
    meio = inicio + (fim - inicio) // 2
    return (inicio, meio), (meio + timedelta(days=1), fim)


def _caminho(repo: str) -> str:
    return f"/repos/{repo}/actions/runs"


def _filtros(branch: str, evento: str, inicio: date, fim: date) -> dict[str, Any]:
    return {"branch": branch, "event": evento, "created": f"{inicio.isoformat()}..{fim.isoformat()}"}


def coletar_runs(
    cliente, repo: str, branch: str, evento: str, janela: Janela
) -> tuple[list[RunColetado], list[Intervalo]]:
    """Todos os runs da janela, mês a mês; meses no teto são subdivididos até caber."""
    runs: dict[int, RunColetado] = {}
    intervalos: list[Intervalo] = []
    for inicio, fim in meses_da_janela(janela):
        antes = len(runs)
        _coletar_intervalo(cliente, repo, branch, evento, inicio, fim, runs, intervalos)
        log.info("%s: runs de %s: %d", repo, inicio.strftime("%Y-%m"), len(runs) - antes)
    truncados = [i for i in intervalos if i.truncado]
    if truncados:
        log.warning("%s: %d dia(s) com mais de %d runs; dados incompletos",
                    repo, len(truncados), LIMITE_RESULTADOS)
    return sorted(runs.values(), key=lambda r: (r.criado_em, r.id)), intervalos


def _coletar_intervalo(
    cliente, repo: str, branch: str, evento: str, inicio: date, fim: date,
    runs: dict[int, RunColetado], intervalos: list[Intervalo],
) -> None:
    params = {**_filtros(branch, evento, inicio, fim), "per_page": 100}
    paginas = cliente.paginas(_caminho(repo), params)
    primeira = next(paginas, None)
    total = (primeira.dados or {}).get("total_count", 0) if primeira else 0

    metades = dividir(inicio, fim)
    if total > LIMITE_RESULTADOS and metades is not None:
        paginas.close()
        log.debug("%s: %d runs em %s..%s; subdividindo", repo, total, inicio, fim)
        for meio_inicio, meio_fim in metades:
            _coletar_intervalo(cliente, repo, branch, evento, meio_inicio, meio_fim, runs, intervalos)
        return

    for pagina in chain([primeira] if primeira else [], paginas):
        for item in (pagina.dados or {}).get("workflow_runs", []):
            run = RunColetado.da_api(item)
            runs[run.id] = run
    intervalos.append(Intervalo(inicio, fim, total, truncado=total > LIMITE_RESULTADOS))


def contar_validos(
    runs: Iterable[RunColetado], sucesso: frozenset[str], falha: frozenset[str]
) -> int:
    validas = sucesso | falha
    return sum(1 for run in runs if run.conclusao in validas)
