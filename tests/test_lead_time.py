from datetime import datetime, timezone

import pytest

from metricas.lead_time import (
    ReleaseCommits,
    calcular_lead_time,
    lead_time_release,
    lead_times_commits,
)


def dia(d, m=3, h=0):
    return datetime(2025, m, d, h, tzinfo=timezone.utc)


@pytest.fixture
def release_exemplo():
    """Exemplo do enunciado: v1.1 em 15/03 com commits de 02/03, 10/03 e 14/03."""
    return ReleaseCommits("v1.1", dia(15), "v1.0", (dia(2), dia(10), dia(14)))


@pytest.fixture
def primeira_release():
    return ReleaseCommits("v1.0", dia(1), None, (dia(1),))


@pytest.fixture
def release_sem_commits():
    return ReleaseCommits("v1.1.1", dia(16), "v1.1", ())


def test_exemplo_por_release(release_exemplo):
    assert lead_time_release(release_exemplo) == 13 * 24


def test_exemplo_por_commit(release_exemplo):
    assert sorted(lead_times_commits(release_exemplo)) == [1 * 24, 5 * 24, 13 * 24]


def test_exemplo_mediana_do_repositorio(release_exemplo):
    resultado = calcular_lead_time([release_exemplo])
    assert resultado.por_release_horas == 13 * 24
    assert resultado.por_commit_horas == 5 * 24
    assert resultado.releases_avaliadas == 1


def test_mediana_por_commit_junta_todas_as_releases(release_exemplo):
    outra = ReleaseCommits("v1.2", dia(20), "v1.1", (dia(19), dia(18)))
    resultado = calcular_lead_time([release_exemplo, outra])
    # (a): mediana de [13 dias, 2 dias]; (b): mediana de [13, 5, 1, 1, 2] dias.
    assert resultado.por_release_horas == pytest.approx(7.5 * 24)
    assert resultado.por_commit_horas == 2 * 24


def test_commit_antigo_esquecido_afeta_mais_a_variante_a():
    release = ReleaseCommits(
        "v2.0", dia(30), "v1.9", (dia(1), dia(29), dia(29), dia(29), dia(29))
    )
    resultado = calcular_lead_time([release])
    assert resultado.por_release_horas == 29 * 24
    assert resultado.por_commit_horas == 24


def test_primeira_release_e_ignorada(primeira_release, release_exemplo):
    assert lead_time_release(primeira_release) is None
    resultado = calcular_lead_time([primeira_release, release_exemplo])
    assert resultado.releases_primeiras == 1
    assert resultado.releases_avaliadas == 1
    assert resultado.por_release_horas == 13 * 24


def test_release_sem_commits_novos_e_ignorada(release_sem_commits, release_exemplo):
    assert lead_time_release(release_sem_commits) is None
    resultado = calcular_lead_time([release_exemplo, release_sem_commits])
    assert resultado.releases_sem_commits == 1
    assert resultado.por_commit_horas == 5 * 24


def test_compare_que_falhou_e_contado_a_parte(release_exemplo):
    falhou = ReleaseCommits("v1.2", dia(20), "v1.1", None)
    resultado = calcular_lead_time([release_exemplo, falhou])
    assert resultado.releases_compare_falhou == 1
    assert resultado.releases_avaliadas == 1


def test_commit_com_data_posterior_a_release_e_descartado():
    release = ReleaseCommits("v1.1", dia(15), "v1.0", (dia(10), dia(16)))
    resultado = calcular_lead_time([release])
    assert resultado.commits_data_futura == 1
    assert resultado.por_commit_horas == 5 * 24


def test_repositorio_com_uma_unica_release(primeira_release):
    resultado = calcular_lead_time([primeira_release])
    assert resultado.por_release_horas is None
    assert resultado.por_commit_horas is None
    assert resultado.releases_avaliadas == 0


def test_lead_time_fracionario_em_horas():
    release = ReleaseCommits("v1", dia(2, h=6), "v0", (dia(1, h=18),))
    assert lead_time_release(release) == 12
