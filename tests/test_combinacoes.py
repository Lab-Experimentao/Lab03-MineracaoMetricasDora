from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from analise.combinacoes import (
    COLUNAS_PARES,
    COLUNAS_TRANSICOES,
    concordancia_pares,
    distribuicao,
    kappa_linear,
    transicoes,
)
from metricas.combinacoes import COLUNAS, calcular_combinacoes

INICIO = datetime(2025, 10, 1, tzinfo=timezone.utc)
FIM = datetime(2026, 10, 1, tzinfo=timezone.utc)


def data(dias, horas=0):
    return (INICIO + timedelta(days=dias, hours=horas)).isoformat()


def compare(cadeia, tag, anterior, dias):
    return {"repositorio": "d/r", "cadeia": cadeia, "tag": tag, "publicada_em": data(dias),
            "tag_anterior": anterior, "status": "ok" if anterior else "primeira"}


def commit(tag, anterior, dias, horas, titulo="feat: x"):
    return {"repositorio": "d/r", "tag": tag, "tag_anterior": anterior, "data_autor": data(dias, horas),
            "titulo": titulo}


def entradas():
    # releases v1.0.0 (dia 10) e v1.1.0 (dia 20); com pré-releases, também v1.1.0-rc1 (dia 15) e o
    # patch v1.1.1 (dia 22); tags a cada 2 dias.
    compares = [
        compare("release", "v1.0.0", "", 10), compare("release", "v1.1.0", "v1.0.0", 20),
        compare("release_prerelease", "v1.0.0", "", 10),
        compare("release_prerelease", "v1.1.0-rc1", "v1.0.0", 15),
        compare("release_prerelease", "v1.1.0", "v1.1.0-rc1", 20),
        compare("release_prerelease", "v1.1.1", "v1.1.0", 22),
        *(compare("tag", f"t{i}", f"t{i - 1}" if i else "", 2 * i) for i in range(10)),
    ]
    commits = [
        commit("v1.1.0", "v1.0.0", 11, 0), commit("v1.1.0", "v1.0.0", 19, 0),
        commit("v1.1.0-rc1", "v1.0.0", 12, 0), commit("v1.1.0", "v1.1.0-rc1", 19, 0, "fix: y"),
        *(commit(f"t{i}", f"t{i - 1}", 2 * i - 1, 0) for i in range(1, 10)),
    ]
    metricas = [{"repositorio": "d/r", "cfr_ci": "0.2", "recuperacao_horas": "5"}]
    return metricas, compares, commits


def test_calcular_combinacoes_troca_cadeia_e_variantes():
    metricas, compares, commits = entradas()
    linhas = calcular_combinacoes(metricas, compares, commits, 52.0, fim_janela=FIM, dias_corretiva=7)
    assert [l["combinacao"] for l in linhas] == ["C1", "C2", "C3"]
    assert all(list(l) == COLUNAS for l in linhas)
    c1, c2, c3 = linhas
    assert [l["itens_janela"] for l in linhas] == [2, 4, 10]
    assert c1["deploys_por_semana"] == pytest.approx(2 / 52)
    # C1: lead time (a) da v1.1.0 = commit mais antigo (dia 11) até o dia 20
    assert c1["lead_time_horas"] == pytest.approx(9 * 24)
    # C3: lead time (b) = mediana de 9 commits de 1 dia
    assert c3["lead_time_horas"] == pytest.approx(24)
    assert c1["cfr"] == c3["cfr"] == 0.2
    # C2: CFR (b); o patch v1.1.1 (dia 22) sai em até 7 dias da v1.1.0-rc1 e da v1.1.0
    assert c2["cfr"] == pytest.approx(2 / 4)
    assert {l["recuperacao_horas"] for l in linhas} == {5.0}
    assert c1["classe_geral"] is not None


def test_calcular_combinacoes_sem_itens_na_cadeia():
    metricas, compares, commits = entradas()
    compares = [c for c in compares if c["cadeia"] != "tag"]
    c3 = calcular_combinacoes(metricas, compares, commits, 52.0, fim_janela=FIM, dias_corretiva=7)[2]
    assert c3["itens_janela"] == 0 and c3["classe_frequencia"] == "Low"
    assert c3["lead_time_horas"] is None and c3["classe_lead_time"] is None


def classes(**por_combinacao):
    """metricas_combinacoes.csv com a classe geral e as dimensões iguais à geral."""
    linhas = []
    for combinacao, valores in por_combinacao.items():
        for i, classe in enumerate(valores):
            linhas.append({"repositorio": f"d/r{i}", "combinacao": combinacao, "unidade_deploy": "release",
                           "lead_time_variante": "a", "cfr_variante": "a", **{
                               c: classe for c in ("classe_geral", "classe_frequencia", "classe_lead_time",
                                                   "classe_cfr")}})
    return pd.DataFrame(linhas)


def test_kappa_linear():
    a = pd.Series(["Elite", "High", "Medium", "Low"])
    assert kappa_linear(a, a) == 1.0
    # trocar Elite por High pesa menos que trocar Elite por Low
    perto = kappa_linear(a, pd.Series(["High", "High", "Medium", "Low"]))
    longe = kappa_linear(a, pd.Series(["Low", "High", "Medium", "Low"]))
    assert 0 < longe < perto < 1


def test_concordancia_pares():
    df = classes(C1=["Elite", "High", "Medium", "Low"], C2=["High", "High", "Medium", "Elite"],
                 C3=["Elite", "High", "Medium", None])
    pares = concordancia_pares(df)
    assert list(pares.columns) == COLUNAS_PARES
    assert len(pares) == 3 * 4
    geral = pares[pares["dimensao"] == "geral"].set_index("par")
    c1c2 = geral.loc["C1xC2"]
    assert (c1c2["mudam"], c1c2["sobem"], c1c2["descem"], c1c2["mudam_duas_ou_mais"]) == (2, 1, 1, 1)
    assert c1c2["proporcao_mudam"] == 0.5
    c1c3 = geral.loc["C1xC3"]
    assert (c1c3["repositorios"], c1c3["sem_classe"], c1c3["mudam"], c1c3["kappa_linear"]) == (3, 1, 0, 1.0)


def test_distribuicao_e_transicoes():
    df = classes(C1=["Elite", "High", "High"], C2=["High", "High", "Low"])
    dist = distribuicao(df).set_index("combinacao")
    assert (dist.loc["C1", "Elite"], dist.loc["C1", "High"], dist.loc["C2", "Low"]) == (1, 2, 1)
    trans = transicoes(df)
    assert list(trans.columns) == COLUNAS_TRANSICOES
    high = trans.set_index("classe_a").loc["High"]
    assert (high["para_High"], high["para_Low"], high["repositorios"]) == (1, 1, 2)
    assert trans["repositorios"].sum() == 3
