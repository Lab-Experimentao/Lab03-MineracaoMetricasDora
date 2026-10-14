import pandas as pd
import pytest

from metricas.corretiva import VERSOES
from validacao.heuristica import COLUNAS_ERROS, COLUNAS_VERSOES, avaliar_versoes, releases_rotuladas


@pytest.fixture
def consenso():
    """Quatro releases rotuladas: duas corretivas pelo consenso."""
    return pd.DataFrame([
        {"repositorio": "a/a", "tag": "v1.0.1", "tag_anterior": "v1.0.0",
         "publicada_em": "2026-01-10T00:00:00+00:00", "corretiva": "sim"},
        {"repositorio": "a/a", "tag": "v1.1.0", "tag_anterior": "v1.0.1",
         "publicada_em": "2026-02-10T00:00:00+00:00", "corretiva": "não"},
        {"repositorio": "b/b", "tag": "v2.0.0", "tag_anterior": "",
         "publicada_em": "2026-01-01T00:00:00+00:00", "corretiva": "não"},
        {"repositorio": "b/b", "tag": "v2.1.0", "tag_anterior": "v2.0.0",
         "publicada_em": "2026-03-01T00:00:00+00:00", "corretiva": "sim"},
    ])


@pytest.fixture
def commits():
    return pd.DataFrame([
        {"repositorio": "a/a", "tag_anterior": "v1.0.0", "tag": "v1.0.1", "titulo": "corrige crash"},
        {"repositorio": "a/a", "tag_anterior": "v1.0.1", "tag": "v1.1.0", "titulo": "fix: typo na doc"},
        {"repositorio": "a/a", "tag_anterior": "v1.0.1", "tag": "v1.1.0", "titulo": "feat: novo recurso"},
        {"repositorio": "b/b", "tag_anterior": "v2.0.0", "tag": "v2.1.0", "titulo": "Bump deps"},
    ])


def test_releases_rotuladas_juntam_titulos(consenso, commits):
    releases = releases_rotuladas(consenso, commits)
    assert releases[1].titulos_commits == ("fix: typo na doc", "feat: novo recurso")
    assert releases[2].tag_anterior is None and releases[2].titulos_commits == ()


def test_metricas_da_v1(consenso, commits):
    resumo, erros = avaliar_versoes(consenso, commits)
    assert list(resumo.columns) == COLUNAS_VERSOES and list(erros.columns) == COLUNAS_ERROS
    assert list(resumo["versao"]) == [v.nome for v in VERSOES]
    v1 = resumo.iloc[0]
    # v1 marca v1.0.1 (patch) e v1.1.0 (commit com fix): 1 acerto, 1 falso positivo, 1 falso negativo.
    assert (v1.verdadeiros_positivos, v1.falsos_positivos, v1.falsos_negativos) == (1, 1, 1)
    assert (v1.precisao, v1.recall, v1.f1) == (0.5, 0.5, 0.5)

    erros_v1 = erros[erros["versao"] == "v1"].set_index("tag")
    assert erros_v1.loc["v1.1.0", "tipo_erro"] == "falso positivo"
    assert erros_v1.loc["v1.1.0", "titulos_correcao"] == "fix: typo na doc"
    assert erros_v1.loc["v2.1.0", "tipo_erro"] == "falso negativo"
