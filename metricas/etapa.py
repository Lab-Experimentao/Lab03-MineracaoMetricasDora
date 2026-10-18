"""Etapa de métricas: lê os CSVs da coleta e grava as métricas por repositório
(`metricas.csv`) e a classificação em cada combinação da RQ 07 (`metricas_combinacoes.csv`)."""

from __future__ import annotations

import csv
import logging
from collections import Counter
from pathlib import Path

from metricas.combinacoes import COLUNAS as COLUNAS_COMBINACOES
from metricas.combinacoes import calcular_combinacoes
from metricas.consolidacao import calcular_todos
from pipeline.config import Config

log = logging.getLogger(__name__)

ARQUIVO_SAIDA = "metricas.csv"
ARQUIVO_COMBINACOES = "metricas_combinacoes.csv"


def _ler(caminho: Path) -> list[dict[str, str]]:
    if not caminho.is_file():
        raise FileNotFoundError(f"{caminho} não encontrado; rode antes a etapa de coleta")
    with caminho.open(encoding="utf-8", newline="") as arquivo:
        return list(csv.DictReader(arquivo))


def _gravar(destino: Path, linhas: list[dict], colunas: list[str]) -> None:
    with destino.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=colunas)
        escritor.writeheader()
        escritor.writerows({c: "" if v is None else v for c, v in linha.items()} for linha in linhas)


def executar(config: Config) -> None:
    brutos = config.saida_dir / "brutos"
    runs_cfg = config.workflow_runs
    linhas = calcular_todos(
        _ler(brutos / "repositorios.csv"),
        _ler(brutos / "compares.csv"),
        _ler(brutos / "commits.csv"),
        _ler(brutos / "runs.csv"),
        config.janela.semanas,
        runs_cfg.conclusoes_sucesso,
        runs_cfg.conclusoes_falha,
        fim_janela=config.janela.fim_exclusivo_dt,
        dias_corretiva=config.metricas.janela_release_corretiva_dias,
    )

    destino = config.saida_dir / ARQUIVO_SAIDA
    _gravar(destino, linhas, list(linhas[0]) if linhas else ["repositorio"])
    log.info("gravado %s (%d repositórios)", destino, len(linhas))

    combinacoes = calcular_combinacoes(
        linhas,
        _ler(brutos / "compares.csv"),
        _ler(brutos / "commits.csv"),
        config.janela.semanas,
        fim_janela=config.janela.fim_exclusivo_dt,
        dias_corretiva=config.metricas.janela_release_corretiva_dias,
    )
    _gravar(config.saida_dir / ARQUIVO_COMBINACOES, combinacoes, COLUNAS_COMBINACOES)
    log.info("gravado %s (%d linhas)", config.saida_dir / ARQUIVO_COMBINACOES, len(combinacoes))
    log.info("releases ignoradas no lead time por erro no compare (ex.: 404): %d",
             sum(l["releases_compare_erro"] for l in linhas))
    log.info("flaky: %d falhas seguidas de sucesso no mesmo commit; %d runs reexecutados, %d deles com sucesso",
             sum(l["falhas_flaky_mesmo_commit"] for l in linhas), sum(l["runs_reexecutados"] for l in linhas),
             sum(l["runs_flaky_reexecucao"] for l in linhas))
    log.info("classificação geral (C1): %s",
             dict(Counter(l["classe_geral"] or "sem dados" for l in linhas).most_common()))
