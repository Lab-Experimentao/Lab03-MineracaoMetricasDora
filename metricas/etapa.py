"""Etapa de métricas: lê os CSVs da coleta e grava as métricas por repositório."""

from __future__ import annotations

import csv
import logging
from collections import Counter
from pathlib import Path

from metricas.consolidacao import calcular_todos
from pipeline.config import Config

log = logging.getLogger(__name__)

ARQUIVO_SAIDA = "metricas.csv"


def _ler(caminho: Path) -> list[dict[str, str]]:
    if not caminho.is_file():
        raise FileNotFoundError(f"{caminho} não encontrado; rode antes a etapa de coleta")
    with caminho.open(encoding="utf-8", newline="") as arquivo:
        return list(csv.DictReader(arquivo))


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
    )

    destino = config.saida_dir / ARQUIVO_SAIDA
    colunas = list(linhas[0]) if linhas else ["repositorio"]
    with destino.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=colunas)
        escritor.writeheader()
        escritor.writerows({c: "" if v is None else v for c, v in linha.items()} for linha in linhas)

    log.info("gravado %s (%d repositórios)", destino, len(linhas))
    log.info("releases ignoradas no lead time por erro no compare (ex.: 404): %d",
             sum(l["releases_compare_erro"] for l in linhas))
    log.info("classificação geral (C1): %s",
             dict(Counter(l["classe_geral"] or "sem dados" for l in linhas).most_common()))
