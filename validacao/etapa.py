"""Etapa de validação: sorteia a amostra-ouro e gera uma planilha de rotulagem por avaliador.

Saída em `<saida.dir>/validacao/`. Não acessa a API: lê `metricas.csv` e os CSVs brutos.
Planilhas já existentes não são sobrescritas, para não apagar rótulos preenchidos.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from pipeline.config import Config
from validacao.amostra import sortear_releases, sortear_repositorios
from validacao.planilha import gerar_planilha

log = logging.getLogger(__name__)

ARQUIVO_AMOSTRA = "amostra_ouro.csv"


def _ler(caminho: Path) -> pd.DataFrame:
    if not caminho.is_file():
        raise FileNotFoundError(f"{caminho} não encontrado; rode antes as etapas de coleta e métricas")
    return pd.read_csv(caminho, dtype=str, keep_default_na=False)


def arquivo_rotulagem(destino: Path, avaliador: str) -> Path:
    return destino / f"rotulagem_{avaliador}.xlsx"


def executar(config: Config) -> None:
    cfg = config.validacao_manual
    brutos = config.saida_dir / "brutos"
    destino = config.saida_dir / "validacao"

    repositorios = sortear_repositorios(_ler(config.saida_dir / "metricas.csv"), cfg.n_repositorios, cfg.semente)
    amostra = sortear_releases(
        _ler(brutos / "compares.csv"), _ler(brutos / "releases.csv"),
        repositorios, cfg.releases_por_repositorio, cfg.semente,
    )

    destino.mkdir(parents=True, exist_ok=True)
    amostra.to_csv(destino / ARQUIVO_AMOSTRA, index=False, encoding="utf-8")
    log.info("amostra-ouro: %d repositórios, %d releases (semente %d), gravada em %s",
             len(repositorios), len(amostra), cfg.semente, destino / ARQUIVO_AMOSTRA)

    for avaliador in cfg.avaliadores:
        planilha = arquivo_rotulagem(destino, avaliador)
        if planilha.exists():
            log.info("%s já existe; mantida (apague-a para gerar de novo em branco)", planilha)
            continue
        gerar_planilha(planilha, amostra)
        log.info("planilha de rotulagem gravada em %s", planilha)
