import pytest

from metricas.cfr import Resultado, cfr_ci, classificar_conclusao


@pytest.fixture
def runs_com_ignorados():
    """2 falhas e 6 sucessos válidos, mais runs que não entram no cálculo."""
    return [
        "success", "failure", "success", "cancelled", "success", "timed_out",
        "skipped", "success", None, "success", "neutral", "success",
        "action_required", "stale",
    ]


@pytest.mark.parametrize("conclusao", ["success"])
def test_sucesso(conclusao):
    assert classificar_conclusao(conclusao) is Resultado.SUCESSO


@pytest.mark.parametrize("conclusao", ["failure", "timed_out", "startup_failure"])
def test_falha(conclusao):
    assert classificar_conclusao(conclusao) is Resultado.FALHA


@pytest.mark.parametrize(
    "conclusao", ["cancelled", "skipped", "neutral", "action_required", "stale", None, ""]
)
def test_ignorados(conclusao):
    assert classificar_conclusao(conclusao) is None


def test_cancelled_e_skipped_nao_entram_no_calculo(runs_com_ignorados):
    resultado = cfr_ci(runs_com_ignorados)
    assert (resultado.falhas, resultado.sucessos, resultado.ignorados) == (2, 6, 6)
    assert resultado.taxa == pytest.approx(2 / 8)


def test_sem_runs_validos():
    resultado = cfr_ci(["cancelled", "skipped"])
    assert resultado.taxa is None
    assert resultado.ignorados == 2


def test_so_falhas():
    assert cfr_ci(["failure", "startup_failure"]).taxa == 1.0


def test_conclusoes_configuraveis():
    resultado = cfr_ci(["success", "failure", "timed_out"], falha=frozenset({"failure"}))
    assert (resultado.falhas, resultado.sucessos, resultado.ignorados) == (1, 1, 1)
