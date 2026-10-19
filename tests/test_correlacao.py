import math

import pandas as pd
import pytest

from analise.correlacao import COLUNAS_SPEARMAN, grafico_dispersao, spearman

NAN = float("nan")


def metricas(frequencia, cfr_ci, cfr_entrega):
    return pd.DataFrame({"deploys_por_semana": frequencia, "cfr_ci": cfr_ci, "cfr_entrega": cfr_entrega})


def test_spearman_por_variante():
    df = metricas([0.1, 0.5, 1.0, 2.0, 4.0], [0.0, 0.1, 0.2, 0.3, 0.4], [0.5, 0.4, 0.3, 0.2, 0.1])
    resultado = spearman(df).set_index("variante")
    assert list(spearman(df).columns) == COLUNAS_SPEARMAN
    assert resultado.loc["(a)", "rho"] == pytest.approx(1.0)
    assert resultado.loc["(b)", "rho"] == pytest.approx(-1.0)
    assert resultado.loc["(a)", "cfr_zero"] == 1


def test_spearman_ignora_repositorios_sem_cfr():
    df = metricas([1.0, 2.0, 3.0, 4.0], [0.1, 0.2, 0.3, 0.4], [0.4, NAN, 0.2, 0.1])
    linha = spearman(df).set_index("variante").loc["(b)"]
    assert (linha["n"], linha["sem_par"]) == (3, 1)
    assert linha["rho"] == pytest.approx(-1.0)


def test_spearman_com_menos_de_tres_pares_e_nan():
    linha = spearman(metricas([1.0, 2.0], [0.1, 0.2], [0.1, 0.2])).iloc[0]
    assert linha["n"] == 2 and math.isnan(linha["rho"]) and math.isnan(linha["p_valor"])


def test_grafico_dispersao_grava_png(tmp_path):
    pytest.importorskip("matplotlib")
    df = metricas([0.1, 0.5, 1.0, 2.0], [0.0, 0.1, 0.2, 0.3], [0.0, 0.0, 0.3, 0.1])
    caminho = tmp_path / "rq05.png"
    grafico_dispersao(df, spearman(df), caminho)
    assert caminho.read_bytes()[:4] == b"\x89PNG"
