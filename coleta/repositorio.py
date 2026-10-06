"""Coleta completa de um repositório da amostra."""

from __future__ import annotations

from dataclasses import dataclass

from coleta import releases as rel
from coleta import workflow_runs as wr
from coleta.metadados import contar_contribuidores
from coleta.modelos import Candidato, Release, RunColetado, Tag
from pipeline.config import Config


@dataclass(frozen=True)
class ColetaRepositorio:
    candidato: Candidato
    contribuidores: int | None
    releases: list[Release]
    tags: list[Tag]
    pares: list[rel.Par]
    compares: dict[tuple[str, str], rel.ResultadoCompare]
    runs: list[RunColetado]
    intervalos_runs: list[wr.Intervalo]


def coletar_repositorio(cliente, candidato: Candidato, config: Config) -> ColetaRepositorio:
    repo = candidato.nome
    releases = rel.listar_releases(cliente, repo)
    tags = rel.listar_tags(cliente, repo)
    pares = rel.pares_do_repositorio(releases, tags, config.janela)
    runs, intervalos = wr.coletar_runs(
        cliente, repo, candidato.branch_padrao, config.workflow_runs.evento, config.janela
    )
    return ColetaRepositorio(
        candidato=candidato,
        contribuidores=contar_contribuidores(cliente, repo),
        releases=releases,
        tags=tags,
        pares=pares,
        compares=rel.coletar_compares(cliente, repo, pares, {t.nome for t in tags}),
        runs=runs,
        intervalos_runs=intervalos,
    )
