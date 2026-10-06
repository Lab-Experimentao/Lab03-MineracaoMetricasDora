"""Conversão da coleta em linhas de CSV e gravação em disco.

Datas saem em ISO 8601 (UTC); valores ausentes saem como célula vazia.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from coleta import releases as rel
from coleta.repositorio import ColetaRepositorio
from coleta.selecao import Avaliacao, EtapaFunil, ResumoFaixa


def _celula(valor: Any) -> Any:
    if valor is None:
        return ""
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, bool):
        return int(valor)
    return valor


def gravar_csv(caminho: Path, linhas: Iterable[dict[str, Any]], colunas: list[str]) -> int:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=colunas)
        escritor.writeheader()
        for linha in linhas:
            escritor.writerow({c: _celula(linha.get(c)) for c in colunas})
            total += 1
    return total


def linhas_faixas(resumos: Iterable[ResumoFaixa]) -> list[dict[str, Any]]:
    return [vars(r) for r in resumos]


def linhas_funil(avaliacoes: Iterable[Avaliacao]) -> list[dict[str, Any]]:
    return [
        {
            "repositorio": a.candidato.nome,
            "faixa": a.candidato.faixa,
            "estrelas": a.candidato.estrelas,
            "situacao": a.motivo,
            "n_workflows": a.n_workflows,
            "n_releases_janela": a.n_releases_janela,
            "n_runs_validos": a.n_runs_validos,
            "detalhe": a.detalhe,
        }
        for a in avaliacoes
    ]


def linhas_funil_resumo(etapas: Iterable[EtapaFunil]) -> list[dict[str, Any]]:
    return [vars(e) for e in etapas]


def linhas_repositorios(coletas: Iterable[ColetaRepositorio]) -> list[dict[str, Any]]:
    return [
        {
            "repositorio": c.candidato.nome,
            "url": c.candidato.url,
            "estrelas": c.candidato.estrelas,
            "linguagem": c.candidato.linguagem,
            "criado_em": c.candidato.criado_em,
            "contribuidores": c.contribuidores,
            "branch_padrao": c.candidato.branch_padrao,
            "faixa": c.candidato.faixa,
        }
        for c in coletas
    ]


def linhas_releases(coletas: Iterable[ColetaRepositorio]) -> list[dict[str, Any]]:
    return [
        {"repositorio": c.candidato.nome, **vars(r)}
        for c in coletas for r in c.releases
    ]


def linhas_tags(coletas: Iterable[ColetaRepositorio]) -> list[dict[str, Any]]:
    return [{"repositorio": c.candidato.nome, **vars(t)} for c in coletas for t in c.tags]


def linhas_compares(coletas: Iterable[ColetaRepositorio]) -> list[dict[str, Any]]:
    """Um par por cadeia; `status` é ok, primeira ou o código HTTP do erro (ex.: 404)."""
    linhas = []
    for c in coletas:
        for par in c.pares:
            resultado = c.compares.get((par.tag_anterior, par.tag)) if par.tag_anterior else None
            linhas.append({
                "repositorio": c.candidato.nome,
                "cadeia": par.cadeia,
                "tag": par.tag,
                "publicada_em": par.publicada_em,
                "tag_anterior": par.tag_anterior,
                "status": resultado.status if resultado else rel.COMPARE_PRIMEIRA,
                "n_commits": len(resultado.commits) if resultado else None,
                "total_commits_api": resultado.total_commits if resultado else None,
                "divergencia": resultado.divergencia if resultado else None,
            })
    return linhas


def linhas_commits(coletas: Iterable[ColetaRepositorio]) -> list[dict[str, Any]]:
    return [
        {
            "repositorio": c.candidato.nome,
            "tag_anterior": resultado.tag_anterior,
            "tag": resultado.tag,
            "sha": commit.sha,
            "data_autor": commit.data_autor,
            "titulo": commit.titulo,
            "mensagem": commit.mensagem,
        }
        for c in coletas for resultado in c.compares.values() for commit in resultado.commits
    ]


def linhas_runs(coletas: Iterable[ColetaRepositorio]) -> list[dict[str, Any]]:
    return [{"repositorio": c.candidato.nome, **vars(r)} for c in coletas for r in c.runs]


def linhas_intervalos_runs(coletas: Iterable[ColetaRepositorio]) -> list[dict[str, Any]]:
    return [{"repositorio": c.candidato.nome, **vars(i)} for c in coletas for i in c.intervalos_runs]


# Arquivo -> (função que gera as linhas, colunas).
ARQUIVOS_COLETA = {
    "repositorios.csv": (linhas_repositorios, [
        "repositorio", "url", "estrelas", "linguagem", "criado_em", "contribuidores",
        "branch_padrao", "faixa",
    ]),
    "releases.csv": (linhas_releases, ["repositorio", "tag", "publicada_em", "draft", "prerelease", "url"]),
    "tags.csv": (linhas_tags, ["repositorio", "nome", "sha", "data_autor", "data_committer"]),
    "compares.csv": (linhas_compares, [
        "repositorio", "cadeia", "tag", "publicada_em", "tag_anterior", "status", "n_commits",
        "total_commits_api", "divergencia",
    ]),
    "commits.csv": (linhas_commits, ["repositorio", "tag_anterior", "tag", "sha", "data_autor", "titulo", "mensagem"]),
    "runs.csv": (linhas_runs, [
        "repositorio", "id", "workflow_id", "workflow_nome", "conclusao", "status",
        "criado_em", "iniciado_em", "atualizado_em", "head_sha",
    ]),
    "runs_intervalos.csv": (linhas_intervalos_runs, ["repositorio", "inicio", "fim", "total", "truncado"]),
}

COLUNAS_FAIXAS = ["faixa", "consulta", "disponiveis", "obtidos"]
COLUNAS_FUNIL = [
    "repositorio", "faixa", "estrelas", "situacao", "n_workflows", "n_releases_janela",
    "n_runs_validos", "detalhe",
]
COLUNAS_FUNIL_RESUMO = ["etapa", "restantes", "descartados", "motivo_descarte"]
