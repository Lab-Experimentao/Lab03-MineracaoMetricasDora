import pytest

from metricas.classificacao import (
    UMA_POR_MES_POR_SEMANA,
    Categoria,
    categoria_geral,
    classificar_cfr,
    classificar_frequencia,
    classificar_lead_time,
    classificar_recuperacao,
    classificar_repositorio,
)

E, H, M, L = Categoria.ELITE, Categoria.HIGH, Categoria.MEDIUM, Categoria.LOW


@pytest.fixture
def notas_exemplo():
    """Exemplo do enunciado: (4, 3, 3, 1) tem mediana 3, logo High."""
    return [E, H, H, L]


@pytest.mark.parametrize("valor, esperado", [
    (10, E), (7, E), (6.99, H), (1, H), (0.99, M),
    (UMA_POR_MES_POR_SEMANA, M), (UMA_POR_MES_POR_SEMANA - 0.001, L), (0, L),
])
def test_frequencia(valor, esperado):
    assert classificar_frequencia(valor) is esperado


@pytest.mark.parametrize("horas, esperado", [
    (0, E), (23.9, E), (24, H), (167.9, H), (168, M), (719.9, M), (720, L),
])
def test_lead_time(horas, esperado):
    assert classificar_lead_time(horas) is esperado


@pytest.mark.parametrize("taxa, esperado", [
    (0, E), (0.15, E), (0.1501, H), (0.30, H), (0.3001, M), (0.45, M), (0.4501, L), (1, L),
])
def test_cfr(taxa, esperado):
    assert classificar_cfr(taxa) is esperado


@pytest.mark.parametrize("horas, esperado", [
    (0.5, E), (1, H), (23.9, H), (24, M), (167.9, M), (168, L),
])
def test_recuperacao(horas, esperado):
    assert classificar_recuperacao(horas) is esperado


def test_exemplo_do_enunciado(notas_exemplo):
    assert categoria_geral(notas_exemplo) is H
    assert H.rotulo == "High"


def test_mediana_fracionaria_arredonda_para_baixo():
    assert categoria_geral([E, H, M, L]) is M  # mediana 2,5


def test_metrica_ausente_fica_de_fora():
    assert categoria_geral([E, E, None, L]) is E
    assert categoria_geral([None, None, None, None]) is None


def test_classificar_repositorio():
    # Elite, High, High e Low, como no exemplo do enunciado.
    assert classificar_repositorio(8, 48, 0.2, 200) is H
    assert classificar_repositorio(None, None, None, None) is None
