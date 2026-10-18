"""Etapa de análise: lê os CSVs de métricas e gera tabelas e gráficos das RQs."""

from __future__ import annotations

import logging

from analise import rq08_rework
from pipeline.config import Config

log = logging.getLogger(__name__)


def executar(config: Config) -> None:
    # RQ 01 a RQ 07: Sprint 03.
    rq08_rework.executar(config)
