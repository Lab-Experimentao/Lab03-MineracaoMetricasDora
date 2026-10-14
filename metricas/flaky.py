"""Falhas intermitentes (flaky) no CFR de CI: runs que falharam e passaram no mesmo commit."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from metricas.cfr import CFR, CONCLUSOES_FALHA, CONCLUSOES_SUCESSO, Resultado, cfr_ci, classificar_conclusao


@dataclass(frozen=True)
class RunCI:
    id: int
    workflow_id: int
    head_sha: str
    tentativa: int  # run_attempt
    conclusao: str | None
    iniciado_em: datetime


@dataclass(frozen=True)
class Flaky:
    reexecutados: int
    reexecutados_com_sucesso: int
    falhas_mesmo_commit: int
    cfr_sem_flaky: CFR


def falhas_seguidas_de_sucesso(
    runs: Iterable[RunCI],
    sucesso: frozenset[str] = CONCLUSOES_SUCESSO,
    falha: frozenset[str] = CONCLUSOES_FALHA,
) -> set[int]:
    """Ids dos runs com falha que têm um sucesso depois, no mesmo workflow e commit."""
    por_commit: dict[tuple[int, str], list[RunCI]] = defaultdict(list)
    for run in runs:
        if run.head_sha:
            por_commit[(run.workflow_id, run.head_sha)].append(run)
    ids = set()
    for runs_commit in por_commit.values():
        sucessos = [r.iniciado_em for r in runs_commit
                    if classificar_conclusao(r.conclusao, sucesso, falha) is Resultado.SUCESSO]
        if not sucessos:
            continue
        ultimo_sucesso = max(sucessos)
        ids.update(r.id for r in runs_commit
                   if classificar_conclusao(r.conclusao, sucesso, falha) is Resultado.FALHA
                   and r.iniciado_em < ultimo_sucesso)
    return ids


def separar_flaky(
    runs: Iterable[RunCI],
    sucesso: frozenset[str] = CONCLUSOES_SUCESSO,
    falha: frozenset[str] = CONCLUSOES_FALHA,
) -> Flaky:
    """Contagens de flaky e o CFR de CI sem as falhas seguidas de sucesso no mesmo commit.

    Um run reexecutado (tentativa > 1) que terminou em sucesso também é flaky, mas a API
    só lista a última tentativa: a falha anterior não está nos dados e ele já conta como
    sucesso no CFR original, então aqui ele só é contado.
    """
    runs = list(runs)
    reexecutados = [r for r in runs if r.tentativa > 1]
    intermitentes = falhas_seguidas_de_sucesso(runs, sucesso, falha)
    return Flaky(
        reexecutados=len(reexecutados),
        reexecutados_com_sucesso=sum(
            classificar_conclusao(r.conclusao, sucesso, falha) is Resultado.SUCESSO for r in reexecutados
        ),
        falhas_mesmo_commit=len(intermitentes),
        cfr_sem_flaky=cfr_ci((r.conclusao for r in runs if r.id not in intermitentes), sucesso, falha),
    )
