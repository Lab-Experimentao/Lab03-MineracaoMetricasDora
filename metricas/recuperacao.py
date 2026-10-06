"""Tempo de recuperação (RQ 04), em horas, por episódios de falha de cada workflow."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from statistics import median

from metricas.cfr import CONCLUSOES_FALHA, CONCLUSOES_SUCESSO, Resultado, classificar_conclusao


@dataclass(frozen=True)
class Run:
    workflow_id: int
    conclusao: str | None
    iniciado_em: datetime  # run_started_at
    atualizado_em: datetime  # updated_at


@dataclass(frozen=True)
class Episodio:
    workflow_id: int
    inicio: datetime
    fim: datetime | None  # None: censurado, sem sucesso até o fim da janela

    @property
    def censurado(self) -> bool:
        return self.fim is None

    @property
    def horas(self) -> float | None:
        return None if self.fim is None else (self.fim - self.inicio).total_seconds() / 3600


@dataclass(frozen=True)
class Recuperacao:
    mediana_horas: float | None
    episodios_recuperados: int
    episodios_censurados: int

    @property
    def proporcao_censurados(self) -> float | None:
        total = self.episodios_recuperados + self.episodios_censurados
        return self.episodios_censurados / total if total else None


def episodios_falha(
    runs: Iterable[Run],
    sucesso: frozenset[str] = CONCLUSOES_SUCESSO,
    falha: frozenset[str] = CONCLUSOES_FALHA,
) -> list[Episodio]:
    """Episódios de cada workflow, em ordem cronológica de `run_started_at`.

    Um episódio começa na primeira falha após um sucesso; falhas antes do primeiro
    sucesso do workflow não abrem episódio, pois seu início real é desconhecido.
    """
    por_workflow: dict[int, list[Run]] = defaultdict(list)
    for run in runs:
        por_workflow[run.workflow_id].append(run)

    episodios = []
    for workflow_id, runs_workflow in por_workflow.items():
        houve_sucesso = False
        inicio: datetime | None = None
        for run in sorted(runs_workflow, key=lambda r: r.iniciado_em):
            resultado = classificar_conclusao(run.conclusao, sucesso, falha)
            if resultado is Resultado.SUCESSO:
                if inicio is not None:
                    episodios.append(Episodio(workflow_id, inicio, run.atualizado_em))
                    inicio = None
                houve_sucesso = True
            elif resultado is Resultado.FALHA and houve_sucesso and inicio is None:
                inicio = run.iniciado_em
        if inicio is not None:
            episodios.append(Episodio(workflow_id, inicio, None))
    return episodios


def tempo_recuperacao(
    runs: Iterable[Run],
    sucesso: frozenset[str] = CONCLUSOES_SUCESSO,
    falha: frozenset[str] = CONCLUSOES_FALHA,
) -> Recuperacao:
    """Mediana dos episódios recuperados de todos os workflows; censurados só são contados."""
    episodios = episodios_falha(runs, sucesso, falha)
    duracoes = [e.horas for e in episodios if e.horas is not None]
    return Recuperacao(
        mediana_horas=median(duracoes) if duracoes else None,
        episodios_recuperados=len(duracoes),
        episodios_censurados=len(episodios) - len(duracoes),
    )
