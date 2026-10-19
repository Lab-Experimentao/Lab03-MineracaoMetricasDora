import math

import pandas as pd
import pytest

from analise.descritiva import (
    COLUNAS_DESCRITIVA,
    METRICAS,
    censura,
    divergencia_lead_time,
    divergencia_lead_time_repositorios,
    impacto_flaky,
    resumo,
    tabela_descritiva,
)

NAN = float("nan")


def metricas(**colunas):
    """DataFrame no formato de metricas.csv, com valores padrão para as colunas não informadas."""
    n = len(next(iter(colunas.values())))
    padrao = {
        "repositorio": [f"dono/repo{i}" for i in range(n)],
        "releases_lead_time": [5] * n,
        "runs_falha": [1] * n, "runs_sucesso": [9] * n,
        "falhas_flaky_mesmo_commit": [0] * n, "runs_flaky_reexecucao": [0] * n,
        "episodios_recuperados": [1] * n, "episodios_censurados": [0] * n,
        "releases_avaliadas_cfr": [5] * n, "releases_censuradas_cfr": [0] * n,
        **{m.coluna: [1.0] * n for m in METRICAS},
    }
    return pd.DataFrame({**padrao, **colunas})


def test_resumo_calcula_quartis_iqr_e_ignora_ausentes():
    estat = resumo(pd.Series([1, 2, 3, 4, 5, NAN]))
    assert estat["n"] == 5 and estat["ausentes"] == 1
    assert (estat["minimo"], estat["q1"], estat["mediana"], estat["q3"], estat["maximo"]) == (1, 2, 3, 4, 5)
    assert estat["iqr"] == 2
    assert estat["media"] == 3


def test_resumo_de_serie_vazia_e_nan():
    estat = resumo(pd.Series([NAN, NAN]))
    assert estat["n"] == 0 and estat["ausentes"] == 2
    assert all(math.isnan(estat[k]) for k in ("q1", "mediana", "q3", "iqr"))


def test_tabela_descritiva_tem_uma_linha_por_metrica():
    tabela = tabela_descritiva(metricas(recuperacao_horas=[1.0, 3.0, NAN]))
    assert list(tabela.columns) == COLUNAS_DESCRITIVA
    assert list(tabela["metrica"]) == [m.coluna for m in METRICAS]
    recuperacao = tabela.set_index("metrica").loc["recuperacao_horas"]
    assert recuperacao["mediana"] == 2.0 and recuperacao["ausentes"] == 1


def test_censura_soma_episodios_e_releases():
    df = metricas(
        episodios_recuperados=[3, 1, 0], episodios_censurados=[1, 0, 0],
        releases_avaliadas_cfr=[8, 5, 4], releases_censuradas_cfr=[2, 0, 1],
        recuperacao_horas=[1.0, 2.0, NAN],
    )
    tabela = censura(df).set_index("rq")
    rq04 = tabela.loc["RQ04"]
    assert (rq04["observados"], rq04["censurados"], rq04["repositorios_com_censura"]) == (4, 1, 1)
    assert rq04["proporcao_censurados"] == pytest.approx(0.2)
    assert rq04["repositorios_sem_valor"] == 1
    cfr_b = tabela.loc["RQ03 (b)"]
    assert (cfr_b["observados"], cfr_b["censurados"], cfr_b["repositorios_com_censura"]) == (17, 3, 2)


def test_censura_sem_episodios_da_nan():
    df = metricas(episodios_recuperados=[0], releases_avaliadas_cfr=[0])
    assert censura(df)["proporcao_censurados"].isna().all()


def test_divergencia_por_repositorio_calcula_diferenca_e_razao():
    df = metricas(lead_time_release_horas=[10.0, 0.0, NAN], lead_time_commit_horas=[30.0, 5.0, 1.0])
    pares = divergencia_lead_time_repositorios(df)
    assert len(pares) == 2  # sem (a), o repositório sai
    assert list(pares["diferenca_horas"]) == [20.0, 5.0]
    assert pares["razao"][0] == 3.0
    assert math.isnan(pares["razao"][1])  # (a) = 0: razão indefinida


def test_divergencia_resumo_conta_sentido_da_diferenca():
    df = metricas(
        lead_time_release_horas=[10.0, 20.0, 30.0, 40.0],
        lead_time_commit_horas=[20.0, 10.0, 30.0, 80.0],
    )
    linha = divergencia_lead_time(divergencia_lead_time_repositorios(df)).iloc[0]
    assert (linha["repositorios"], linha["commit_maior"], linha["commit_menor"], linha["iguais"]) == (4, 2, 1, 1)
    assert linha["mediana_a_horas"] == 25.0 and linha["mediana_b_horas"] == 25.0
    assert linha["mediana_razao"] == pytest.approx(1.5)
    assert linha["spearman"] == pytest.approx(0.8)


def test_divergencia_com_um_repositorio_nao_calcula_spearman():
    df = metricas(lead_time_release_horas=[10.0], lead_time_commit_horas=[20.0])
    assert math.isnan(divergencia_lead_time(divergencia_lead_time_repositorios(df)).iloc[0]["spearman"])


def test_impacto_flaky_nos_tres_cenarios():
    # repo0: 2 falhas (1 flaky), 8 sucessos, 2 reexecuções com sucesso; repo1: sem flaky.
    df = metricas(
        runs_falha=[2, 1], runs_sucesso=[8, 9],
        falhas_flaky_mesmo_commit=[1, 0], runs_flaky_reexecucao=[2, 0],
    )
    tabela = impacto_flaky(df).set_index("cenario")
    assert list(tabela.index) == ["sem_flaky", "atual", "com_reexecucoes"]

    assert (tabela.loc["sem_flaky", "falhas"], tabela.loc["sem_flaky", "runs_validos"]) == (2, 19)
    assert (tabela.loc["atual", "falhas"], tabela.loc["atual", "runs_validos"]) == (3, 20)
    assert (tabela.loc["com_reexecucoes", "falhas"], tabela.loc["com_reexecucoes", "runs_validos"]) == (5, 22)

    assert tabela.loc["atual", "cfr_agregado"] == pytest.approx(0.15)
    assert tabela.loc["atual", "mediana"] == pytest.approx(0.15)  # mediana de 0,2 e 0,1
    assert tabela.loc["atual", "diferenca_mediana_pp"] == 0
    assert tabela.loc["sem_flaky", "diferenca_mediana_pp"] == pytest.approx((1 / 9 + 0.1) / 2 * 100 - 15)
    assert tabela.loc["sem_flaky", "parcela_flaky_agregada"] == 0
    assert tabela.loc["atual", "parcela_flaky_agregada"] == pytest.approx((0.15 - 2 / 19) / 0.15)
    # repo0: (0,2 − 1/9) ÷ 0,2; repo1: 0 → mediana das duas
    assert tabela.loc["atual", "parcela_flaky_mediana"] == pytest.approx((0.2 - 1 / 9) / 0.2 / 2)


def test_impacto_flaky_ignora_repositorio_sem_runs_validos():
    df = metricas(runs_falha=[0, 1], runs_sucesso=[0, 3])
    atual = impacto_flaky(df).set_index("cenario").loc["atual"]
    assert atual["mediana"] == pytest.approx(0.25)
    assert atual["runs_validos"] == 4
