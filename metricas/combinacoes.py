"""Combinações de definições operacionais da RQ 07 e a classificação DORA em cada uma.

A C1 repete a definição principal do `metricas.csv`. C2 e C3 trocam a unidade de deploy (e
com ela a cadeia de compares), a variante do lead time e a do CFR. O tempo de recuperação vem
dos workflow runs e é o mesmo nas três.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from metricas.classificacao import (
    classificar_cfr,
    classificar_frequencia,
    classificar_lead_time,
    classificar_recuperacao,
    classificar_repositorio,
)
from metricas.consolidacao import Linha, releases_avaliadas, releases_commits
from metricas.corretiva import cfr_entrega
from metricas.lead_time import calcular_lead_time


@dataclass(frozen=True)
class Combinacao:
    nome: str
    cadeia: str
    unidade_deploy: str
    lead_time: str  # "a": por release (commit mais antigo); "b": por commit
    cfr: str  # "a": CI; "b": entrega (release corretiva)


COMBINACOES = (
    Combinacao("C1", "release", "release", "a", "a"),
    Combinacao("C2", "release_prerelease", "release + pré-release", "b", "b"),
    Combinacao("C3", "tag", "tag", "b", "a"),
)

COLUNAS = [
    "repositorio", "combinacao", "unidade_deploy", "lead_time_variante", "cfr_variante", "itens_janela",
    "deploys_por_semana", "lead_time_horas", "cfr", "recuperacao_horas",
    "classe_frequencia", "classe_lead_time", "classe_cfr", "classe_recuperacao", "classe_geral",
]


def _numero(valor: Any) -> float | None:
    return None if valor in (None, "") else float(valor)


def _classe(valor: float | None, funcao) -> str | None:
    return None if valor is None else funcao(valor).rotulo


def calcular_combinacoes(
    metricas: Iterable[dict[str, Any]],
    compares: Iterable[Linha],
    commits: Iterable[Linha],
    semanas_janela: float,
    *,
    fim_janela: datetime,
    dias_corretiva: int,
) -> list[dict[str, Any]]:
    """Uma linha por repositório e combinação, com as métricas e as classes.

    `metricas` são as linhas já calculadas do `metricas.csv`, de onde vêm o CFR de CI e o tempo
    de recuperação.
    """
    compares, commits = list(compares), list(commits)
    por_cadeia = {
        c.cadeia: (releases_commits(compares, commits, c.cadeia), releases_avaliadas(compares, commits, c.cadeia))
        for c in COMBINACOES
    }
    linhas = []
    for repo in metricas:
        nome = repo["repositorio"]
        cfr_ci = _numero(repo["cfr_ci"])
        recuperacao = _numero(repo["recuperacao_horas"])
        for combinacao in COMBINACOES:
            releases, avaliadas = (d.get(nome, []) for d in por_cadeia[combinacao.cadeia])
            frequencia = len(releases) / semanas_janela
            lead = calcular_lead_time(releases)
            lead_time = lead.por_release_horas if combinacao.lead_time == "a" else lead.por_commit_horas
            if combinacao.cfr == "a":
                cfr = cfr_ci
            else:
                cfr = cfr_entrega(avaliadas, fim_janela, dias_corretiva).taxa
            geral = classificar_repositorio(frequencia, lead_time, cfr, recuperacao)
            linhas.append({
                "repositorio": nome,
                "combinacao": combinacao.nome,
                "unidade_deploy": combinacao.unidade_deploy,
                "lead_time_variante": combinacao.lead_time,
                "cfr_variante": combinacao.cfr,
                "itens_janela": len(releases),
                "deploys_por_semana": frequencia,
                "lead_time_horas": lead_time,
                "cfr": cfr,
                "recuperacao_horas": recuperacao,
                "classe_frequencia": _classe(frequencia, classificar_frequencia),
                "classe_lead_time": _classe(lead_time, classificar_lead_time),
                "classe_cfr": _classe(cfr, classificar_cfr),
                "classe_recuperacao": _classe(recuperacao, classificar_recuperacao),
                "classe_geral": None if geral is None else geral.rotulo,
            })
    return linhas
