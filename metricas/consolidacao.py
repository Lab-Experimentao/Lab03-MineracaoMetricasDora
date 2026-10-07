"""Monta as entradas das métricas a partir das linhas dos CSVs da coleta e calcula
as métricas de cada repositório (definição principal: release, lead time e CFR (a)).

Recebe as linhas já lidas (dicts do csv.DictReader), sem acessar o disco.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from metricas.cfr import cfr_ci
from metricas.classificacao import (
    classificar_cfr,
    classificar_frequencia,
    classificar_lead_time,
    classificar_recuperacao,
    classificar_repositorio,
)
from metricas.lead_time import ReleaseCommits, calcular_lead_time
from metricas.recuperacao import Run, tempo_recuperacao

Linha = dict[str, str]

CADEIA_PRINCIPAL = "release"
STATUS_OK = "ok"


def _data(valor: str) -> datetime | None:
    return datetime.fromisoformat(valor) if valor else None


def releases_commits(
    compares: Iterable[Linha], commits: Iterable[Linha], cadeia: str = CADEIA_PRINCIPAL
) -> dict[str, list[ReleaseCommits]]:
    """Releases da cadeia com as datas dos commits do compare com a anterior.

    Compare com erro (ex.: 404) vira `datas_commits=None`, que o lead time conta à parte.
    """
    datas: dict[tuple[str, str, str], list[datetime]] = defaultdict(list)
    for commit in commits:
        datas[(commit["repositorio"], commit["tag_anterior"], commit["tag"])].append(_data(commit["data_autor"]))

    resultado: dict[str, list[ReleaseCommits]] = defaultdict(list)
    for linha in compares:
        if linha["cadeia"] != cadeia:
            continue
        repo, anterior = linha["repositorio"], linha["tag_anterior"] or None
        if anterior is None:
            datas_commits: tuple[datetime, ...] | None = ()
        elif linha["status"] == STATUS_OK:
            datas_commits = tuple(datas.get((repo, anterior, linha["tag"]), ()))
        else:
            datas_commits = None
        resultado[repo].append(ReleaseCommits(linha["tag"], _data(linha["publicada_em"]), anterior, datas_commits))
    return resultado


def runs(linhas: Iterable[Linha]) -> dict[str, list[Run]]:
    resultado: dict[str, list[Run]] = defaultdict(list)
    for linha in linhas:
        resultado[linha["repositorio"]].append(Run(
            workflow_id=int(linha["workflow_id"]),
            conclusao=linha["conclusao"] or None,
            # run_started_at pode faltar em runs antigos; created_at é o início mais próximo.
            iniciado_em=_data(linha["iniciado_em"]) or _data(linha["criado_em"]),
            atualizado_em=_data(linha["atualizado_em"]),
        ))
    return resultado


def calcular_repositorio(
    releases: list[ReleaseCommits],
    runs_repo: list[Run],
    semanas_janela: float,
    sucesso: frozenset[str],
    falha: frozenset[str],
) -> dict[str, Any]:
    """Métricas de um repositório e a classificação DORA de referência (C1)."""
    frequencia = len(releases) / semanas_janela
    lead = calcular_lead_time(releases)
    cfr = cfr_ci((r.conclusao for r in runs_repo), sucesso, falha)
    recuperacao = tempo_recuperacao(runs_repo, sucesso, falha)

    def classe(valor, funcao):
        return None if valor is None else funcao(valor).rotulo

    geral = classificar_repositorio(frequencia, lead.por_release_horas, cfr.taxa, recuperacao.mediana_horas)
    return {
        "releases_janela": len(releases),
        "deploys_por_semana": frequencia,
        "lead_time_release_horas": lead.por_release_horas,
        "lead_time_commit_horas": lead.por_commit_horas,
        "releases_lead_time": lead.releases_avaliadas,
        "releases_primeira": lead.releases_primeiras,
        "releases_sem_commits": lead.releases_sem_commits,
        "releases_compare_erro": lead.releases_compare_falhou,
        "commits_data_futura": lead.commits_data_futura,
        "cfr_ci": cfr.taxa,
        "runs_falha": cfr.falhas,
        "runs_sucesso": cfr.sucessos,
        "runs_ignorados": cfr.ignorados,
        "recuperacao_horas": recuperacao.mediana_horas,
        "episodios_recuperados": recuperacao.episodios_recuperados,
        "episodios_censurados": recuperacao.episodios_censurados,
        "proporcao_censurados": recuperacao.proporcao_censurados,
        "classe_frequencia": classe(frequencia, classificar_frequencia),
        "classe_lead_time": classe(lead.por_release_horas, classificar_lead_time),
        "classe_cfr": classe(cfr.taxa, classificar_cfr),
        "classe_recuperacao": classe(recuperacao.mediana_horas, classificar_recuperacao),
        "classe_geral": None if geral is None else geral.rotulo,
    }


def calcular_todos(
    repositorios: Iterable[Linha],
    compares: Iterable[Linha],
    commits: Iterable[Linha],
    linhas_runs: Iterable[Linha],
    semanas_janela: float,
    sucesso: frozenset[str],
    falha: frozenset[str],
) -> list[dict[str, Any]]:
    """Uma linha por repositório da amostra: metadados da coleta + métricas."""
    releases_por_repo = releases_commits(compares, commits)
    runs_por_repo = runs(linhas_runs)
    return [
        {
            **repo,
            **calcular_repositorio(
                releases_por_repo.get(repo["repositorio"], []),
                runs_por_repo.get(repo["repositorio"], []),
                semanas_janela, sucesso, falha,
            ),
        }
        for repo in repositorios
    ]
