"""Etapa de validação: sorteia a amostra-ouro e gera uma planilha de rotulagem por avaliador.

Saída em `<saida.dir>/validacao/`. Não acessa a API: lê `metricas.csv` e os CSVs brutos.
Planilhas já existentes não são sobrescritas, para não apagar rótulos preenchidos.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from pipeline.config import Config
from validacao.amostra import com_textos, sortear_releases, sortear_repositorios
from validacao.planilha import gerar_planilha

log = logging.getLogger(__name__)

ARQUIVO_AMOSTRA = "amostra_ouro.csv"


def _ler(caminho: Path) -> pd.DataFrame:
    if not caminho.is_file():
        raise FileNotFoundError(f"{caminho} não encontrado; rode antes as etapas de coleta e métricas")
    return pd.read_csv(caminho, dtype=str, keep_default_na=False)


def _titulos_commits(caminho: Path, repositorios: list[str]) -> pd.DataFrame:
    """Títulos dos commits só dos repositórios sorteados (o commits.csv tem ~500 MB)."""
    if not caminho.is_file():
        raise FileNotFoundError(f"{caminho} não encontrado; rode antes as etapas de coleta e métricas")
    colunas = ["repositorio", "tag_anterior", "tag", "titulo"]
    blocos = pd.read_csv(caminho, dtype=str, keep_default_na=False, usecols=colunas, chunksize=200_000)
    return pd.concat([b[b["repositorio"].isin(repositorios)] for b in blocos], ignore_index=True)


def arquivo_rotulagem(destino: Path, avaliador: str) -> Path:
    return destino / f"rotulagem_{avaliador}.xlsx"


def executar(config: Config) -> None:
    cfg = config.validacao_manual
    brutos = config.saida_dir / "brutos"
    destino = config.saida_dir / "validacao"

    repositorios = sortear_repositorios(_ler(config.saida_dir / "metricas.csv"), cfg.n_repositorios, cfg.semente)
    compares, releases = _ler(brutos / "compares.csv"), _ler(brutos / "releases.csv")
    if "notas" not in releases.columns:
        raise FileNotFoundError(f"{brutos / 'releases.csv'} sem a coluna 'notas'; rode de novo a etapa de coleta")
    amostra = sortear_releases(compares, releases, repositorios, cfg.releases_por_repositorio, cfg.semente)
    para_rotular = com_textos(amostra, compares, releases, _titulos_commits(brutos / "commits.csv", repositorios))

    destino.mkdir(parents=True, exist_ok=True)
    amostra.to_csv(destino / ARQUIVO_AMOSTRA, index=False, encoding="utf-8")
    log.info("amostra-ouro: %d repositórios, %d releases (semente %d), gravada em %s",
             len(repositorios), len(amostra), cfg.semente, destino / ARQUIVO_AMOSTRA)

    for avaliador in cfg.avaliadores:
        planilha = arquivo_rotulagem(destino, avaliador)
        if planilha.exists():
            log.info("%s já existe; mantida (apague-a para gerar de novo em branco)", planilha)
            continue
        gerar_planilha(planilha, para_rotular)
        log.info("planilha de rotulagem gravada em %s", planilha)
