from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from analise.fatores import (
    COLUNAS_CLIFF,
    COLUNAS_TESTES,
    FATORES,
    OUTRAS,
    cliff_delta,
    graficos_fatores,
    grupos_fatores,
    magnitude_cliff,
    magnitude_epsilon2,
    resumo_grupos,
    tabela_cliff,
    comparar_grupos,
)

FIM = datetime(2026, 10, 1, tzinfo=timezone.utc)
LINGUAGENS = ["TypeScript", "Go", "Rust", "Python", "C++", "Java", "C#"]


def amostra(n=40, seed=0):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "repositorio": [f"d/r{i}" for i in range(n)],
        "linguagem": [LINGUAGENS[i % len(LINGUAGENS)] for i in range(n)],
        "estrelas": np.arange(1000, 1000 + 100 * n, 100),
        "contribuidores": rng.integers(1, 500, n),
        "criado_em": [f"{2010 + i % 15}-01-01T00:00:00+00:00" for i in range(n)],
        "deploys_por_semana": rng.uniform(0.1, 5, n),
        "lead_time_release_horas": rng.uniform(1, 1000, n),
        "cfr_ci": rng.uniform(0, 0.5, n),
        "recuperacao_horas": rng.uniform(0.1, 100, n),
    })
    tipos = pd.DataFrame({"repositorio": df["repositorio"],
                          "tipo_projeto": ["biblioteca/framework", "aplicação/serviço"] * (n // 2)})
    return df, tipos


def test_cliff_delta():
    assert cliff_delta(np.array([3, 4]), np.array([1, 2])) == 1.0
    assert cliff_delta(np.array([1, 2]), np.array([3, 4])) == -1.0
    # pares: 2>1, 2=2, 2<3 → (1 − 1) / 3
    assert cliff_delta(np.array([2]), np.array([1, 2, 3])) == 0.0
    assert np.isnan(cliff_delta(np.array([]), np.array([1])))


@pytest.mark.parametrize("delta, esperado", [
    (0.1, "desprezível"), (-0.2, "pequeno"), (0.4, "médio"), (-0.5, "grande"), (float("nan"), ""),
])
def test_magnitude_cliff(delta, esperado):
    assert magnitude_cliff(delta) == esperado


def test_magnitude_epsilon2():
    assert [magnitude_epsilon2(e) for e in (0.005, 0.05, 0.1, 0.3)] == ["desprezível", "pequeno", "médio", "grande"]


def test_grupos_fatores_quartis_linguagem_e_tipo():
    df, tipos = amostra()
    grupos = grupos_fatores(df, tipos, FIM)
    assert list(grupos.columns) == [f.nome for f in FATORES]
    assert set(grupos["linguagem"]) == {"TypeScript", "Go", "Rust", "Python", "C++", OUTRAS}
    assert grupos["estrelas"].value_counts().to_dict() == {"Q1": 10, "Q2": 10, "Q3": 10, "Q4": 10}
    assert grupos.loc[0, "estrelas"] == "Q1" and grupos.loc[39, "estrelas"] == "Q4"
    # criado em 2010 é o mais antigo: último quartil de idade
    assert grupos.loc[0, "idade"] == "Q4"
    assert grupos.loc[1, "tipo_projeto"] == "aplicação/serviço"


def test_testes_detecta_diferenca_e_aplica_holm():
    df, tipos = amostra()
    df["deploys_por_semana"] = df["estrelas"]  # cresce com as estrelas
    resultado = comparar_grupos(df, grupos_fatores(df, tipos, FIM))
    assert list(resultado.columns) == COLUNAS_TESTES
    assert len(resultado) == 20
    linha = resultado.set_index(["fator", "metrica"]).loc[("estrelas", "deploys_por_semana")]
    assert linha["teste"] == "kruskal-wallis" and linha["significativo"]
    assert linha["epsilon2"] == pytest.approx(linha["estatistica"] / (linha["n"] - 1))
    assert (resultado["p_holm"] >= resultado["p_valor"]).all()


def test_dois_grupos_usa_mann_whitney():
    df, tipos = amostra()
    resultado = comparar_grupos(df, grupos_fatores(df, tipos, FIM)).set_index(["fator", "metrica"])
    linha = resultado.loc[("tipo_projeto", "cfr_ci")]
    assert linha["teste"] == "mann-whitney" and np.isnan(linha["epsilon2"])


def test_cliff_q4_x_q1_e_grupo_melhor():
    df, tipos = amostra()
    df["lead_time_release_horas"] = df["estrelas"]  # mais estrelas, lead time maior (pior)
    df["deploys_por_semana"] = df["estrelas"]  # mais estrelas, mais deploys (melhor)
    cliff = tabela_cliff(df, grupos_fatores(df, tipos, FIM))
    assert list(cliff.columns) == COLUNAS_CLIFF
    estrelas = cliff[cliff["fator"] == "estrelas"].set_index("metrica")
    assert (estrelas["grupo_a"] == "Q4").all() and (estrelas["grupo_b"] == "Q1").all()
    assert estrelas.loc["lead_time_release_horas", "cliff_delta"] == 1.0
    assert estrelas.loc["lead_time_release_horas", "grupo_melhor"] == "Q1"
    assert estrelas.loc["deploys_por_semana", "grupo_melhor"] == "Q4"
    # linguagem: todos os pares entre 6 grupos
    assert len(cliff[(cliff["fator"] == "linguagem") & (cliff["metrica"] == "cfr_ci")]) == 15


def test_resumo_grupos_ignora_ausentes():
    df, tipos = amostra()
    df.loc[:9, "recuperacao_horas"] = np.nan
    resumo = resumo_grupos(df, grupos_fatores(df, tipos, FIM))
    q1 = resumo[(resumo["fator"] == "estrelas") & (resumo["metrica"] == "recuperacao_horas")]
    assert "Q1" not in set(q1["grupo"])


def test_graficos_so_dos_fatores_significativos(tmp_path):
    pytest.importorskip("matplotlib")
    df, tipos = amostra()
    df["deploys_por_semana"] = df["estrelas"]
    grupos = grupos_fatores(df, tipos, FIM)
    resultado = comparar_grupos(df, grupos)
    gravados = graficos_fatores(df, grupos, resultado, tmp_path)
    assert tmp_path / "rq06_estrelas.png" in gravados
    assert len(gravados) == resultado.loc[resultado["significativo"], "fator"].nunique()
