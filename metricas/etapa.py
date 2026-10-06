"""Etapa de métricas: lê o cache da coleta e grava os CSVs de métricas."""

from __future__ import annotations

import logging

from pipeline.config import Config

log = logging.getLogger(__name__)


def executar(config: Config) -> None:
    # Implementada nas issues de lead time, CFR e tempo de recuperação.
    log.warning("etapa de métricas ainda não implementada")
