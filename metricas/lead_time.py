"""Lead time for changes (RQ 02), em horas, nas variantes (a) por release e (b) por commit."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from statistics import median


@dataclass(frozen=True)
class ReleaseCommits:
    """Release com as datas (`commit.author.date`) dos commits do compare com a anterior.

    `tag_anterior` é None na primeira release do histórico; `datas_commits` é None
    quando o compare falhou (ex.: 404 por tag apagada).
    """

    tag: str
    publicada_em: datetime
    tag_anterior: str | None
    datas_commits: tuple[datetime, ...] | None


@dataclass(frozen=True)
class LeadTime:
    por_release_horas: float | None
    por_commit_horas: float | None
    releases_avaliadas: int
    releases_primeiras: int
    releases_sem_commits: int
    releases_compare_falhou: int
    commits_data_futura: int


def _horas(inicio: datetime, fim: datetime) -> float:
    return (fim - inicio).total_seconds() / 3600


def lead_times_commits(release: ReleaseCommits) -> list[float]:
    """Lead time de cada commit da release, ignorando datas posteriores à publicação."""
    if release.tag_anterior is None or not release.datas_commits:
        return []
    return [
        _horas(data, release.publicada_em)
        for data in release.datas_commits
        if data <= release.publicada_em
    ]


def lead_time_release(release: ReleaseCommits) -> float | None:
    """Variante (a): publicação menos o commit mais antigo; None se não há o que medir."""
    valores = lead_times_commits(release)
    return max(valores) if valores else None


def calcular_lead_time(releases: Iterable[ReleaseCommits]) -> LeadTime:
    por_release: list[float] = []
    por_commit: list[float] = []
    primeiras = sem_commits = compare_falhou = data_futura = 0

    for release in releases:
        if release.tag_anterior is None:
            primeiras += 1
            continue
        if release.datas_commits is None:
            compare_falhou += 1
            continue
        valores = lead_times_commits(release)
        data_futura += len(release.datas_commits) - len(valores)
        if not valores:
            sem_commits += 1
            continue
        por_release.append(max(valores))
        por_commit.extend(valores)

    return LeadTime(
        por_release_horas=median(por_release) if por_release else None,
        por_commit_horas=median(por_commit) if por_commit else None,
        releases_avaliadas=len(por_release),
        releases_primeiras=primeiras,
        releases_sem_commits=sem_commits,
        releases_compare_falhou=compare_falhou,
        commits_data_futura=data_futura,
    )
