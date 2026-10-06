"""Classificação DORA (RQ 07) pela tabela de referência da disciplina."""

from __future__ import annotations

import math
from enum import IntEnum
from statistics import median


class Categoria(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    ELITE = 4

    @property
    def rotulo(self) -> str:
        return self.name.capitalize()


HORAS_DIA = 24
HORAS_SEMANA = 7 * HORAS_DIA
# "1 por mês" convertido para releases por semana (mês médio de 365,25/12 dias).
UMA_POR_MES_POR_SEMANA = 7 / (365.25 / 12)


def classificar_frequencia(releases_por_semana: float) -> Categoria:
    if releases_por_semana >= 7:
        return Categoria.ELITE
    if releases_por_semana >= 1:
        return Categoria.HIGH
    if releases_por_semana >= UMA_POR_MES_POR_SEMANA:
        return Categoria.MEDIUM
    return Categoria.LOW


def classificar_lead_time(horas: float) -> Categoria:
    if horas < HORAS_DIA:
        return Categoria.ELITE
    if horas < HORAS_SEMANA:
        return Categoria.HIGH
    if horas < 30 * HORAS_DIA:
        return Categoria.MEDIUM
    return Categoria.LOW


def classificar_cfr(taxa: float) -> Categoria:
    """`taxa` entre 0 e 1."""
    if taxa <= 0.15:
        return Categoria.ELITE
    if taxa <= 0.30:
        return Categoria.HIGH
    if taxa <= 0.45:
        return Categoria.MEDIUM
    return Categoria.LOW


def classificar_recuperacao(horas: float) -> Categoria:
    if horas < 1:
        return Categoria.ELITE
    if horas < HORAS_DIA:
        return Categoria.HIGH
    if horas < HORAS_SEMANA:
        return Categoria.MEDIUM
    return Categoria.LOW


def categoria_geral(notas: list[Categoria | None]) -> Categoria | None:
    """Mediana das notas, arredondada para baixo; métricas sem valor (None) ficam de fora."""
    validas = [int(n) for n in notas if n is not None]
    if not validas:
        return None
    return Categoria(math.floor(median(validas)))


def classificar_repositorio(
    releases_por_semana: float | None,
    lead_time_horas: float | None,
    cfr: float | None,
    recuperacao_horas: float | None,
) -> Categoria | None:
    return categoria_geral([
        None if releases_por_semana is None else classificar_frequencia(releases_por_semana),
        None if lead_time_horas is None else classificar_lead_time(lead_time_horas),
        None if cfr is None else classificar_cfr(cfr),
        None if recuperacao_horas is None else classificar_recuperacao(recuperacao_horas),
    ])
