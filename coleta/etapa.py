"""Etapa de coleta: lê da API do GitHub e grava os dados brutos em cache."""

from __future__ import annotations

import logging

from pipeline.config import Config

log = logging.getLogger(__name__)


def executar(config: Config, token: str) -> None:
    # Implementada nas issues de seleção/funil, releases/commits e workflow runs.
    log.warning("etapa de coleta ainda não implementada")
