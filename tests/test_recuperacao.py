from datetime import datetime, timedelta, timezone

import pytest

from metricas.recuperacao import Run, episodios_falha, tempo_recuperacao


def hora(h, m=0, dia=1):
    return datetime(2025, 6, dia, h, m, tzinfo=timezone.utc)


def run(workflow, conclusao, inicio, duracao_min=5):
    return Run(workflow, conclusao, inicio, inicio + timedelta(minutes=duracao_min))


@pytest.fixture
def runs_exemplo():
    """Exemplo do enunciado: o sucesso das 11:15 termina às 11:20, episódio de 1h20."""
    return [
        run(1, "success", hora(9)),
        run(1, "failure", hora(10)),
        run(1, "failure", hora(10, 30)),
        run(1, "success", hora(11, 15)),
    ]


@pytest.fixture
def runs_nunca_recuperados():
    return [
        run(2, "success", hora(9)),
        run(2, "failure", hora(10)),
        run(2, "failure", hora(12)),
    ]


def test_exemplo_1h20(runs_exemplo):
    resultado = tempo_recuperacao(runs_exemplo)
    assert resultado.mediana_horas == pytest.approx(80 / 60)
    assert resultado.episodios_recuperados == 1
    assert resultado.proporcao_censurados == 0


def test_ordem_de_entrada_nao_importa(runs_exemplo):
    assert tempo_recuperacao(reversed(runs_exemplo)).mediana_horas == pytest.approx(80 / 60)


def test_falha_nunca_recuperada_e_censurada(runs_nunca_recuperados):
    (episodio,) = episodios_falha(runs_nunca_recuperados)
    assert episodio.censurado
    assert episodio.inicio == hora(10)
    resultado = tempo_recuperacao(runs_nunca_recuperados)
    assert resultado.mediana_horas is None
    assert resultado.episodios_censurados == 1
    assert resultado.proporcao_censurados == 1


def test_censurados_nao_entram_na_mediana(runs_exemplo, runs_nunca_recuperados):
    resultado = tempo_recuperacao(runs_exemplo + runs_nunca_recuperados)
    assert resultado.mediana_horas == pytest.approx(80 / 60)
    assert resultado.proporcao_censurados == 0.5


def test_episodios_sao_separados_por_workflow():
    runs = [
        run(1, "success", hora(9)),
        run(2, "success", hora(9)),
        run(1, "failure", hora(10)),
        run(2, "success", hora(10, 30)),  # sucesso de outro workflow não encerra o episódio
        run(1, "success", hora(12), duracao_min=0),
    ]
    (episodio,) = episodios_falha(runs)
    assert episodio.workflow_id == 1
    assert episodio.horas == 2


def test_mediana_entre_workflows():
    runs = [
        run(1, "success", hora(1)), run(1, "failure", hora(2)), run(1, "success", hora(3), 0),
        run(1, "failure", hora(4)), run(1, "success", hora(7), 0),
        run(2, "success", hora(1)), run(2, "failure", hora(2)), run(2, "success", hora(12), 0),
    ]
    resultado = tempo_recuperacao(runs)
    assert resultado.episodios_recuperados == 3
    assert resultado.mediana_horas == 3  # mediana de [1, 3, 10]


def test_cancelled_e_ignorado_e_nao_encerra_episodio():
    runs = [
        run(1, "success", hora(9)),
        run(1, "failure", hora(10)),
        run(1, "cancelled", hora(10, 30)),
        run(1, "skipped", hora(10, 45)),
        run(1, "success", hora(11), duracao_min=0),
    ]
    (episodio,) = episodios_falha(runs)
    assert episodio.horas == 1


def test_cancelled_nao_abre_episodio():
    runs = [run(1, "success", hora(9)), run(1, "cancelled", hora(10)), run(1, "success", hora(11))]
    assert episodios_falha(runs) == []


def test_falhas_antes_do_primeiro_sucesso_nao_abrem_episodio():
    runs = [
        run(1, "failure", hora(8)),
        run(1, "success", hora(9)),
        run(1, "failure", hora(10)),
        run(1, "success", hora(11), duracao_min=0),
    ]
    (episodio,) = episodios_falha(runs)
    assert episodio.inicio == hora(10)


def test_sem_falhas():
    resultado = tempo_recuperacao([run(1, "success", hora(9)), run(1, "success", hora(10))])
    assert resultado.mediana_horas is None
    assert resultado.proporcao_censurados is None
