from datetime import date

import pytest

from coleta import workflow_runs as wr
from pipeline.config import Janela
from falsos import ClienteFalso

SUCESSO = frozenset({"success"})
FALHA = frozenset({"failure", "timed_out", "startup_failure"})
CAMINHO = "/repos/dono/repo/actions/runs"


def run_api(id_, conclusao="success", dia="2025-10-05", workflow=1):
    return {
        "id": id_, "workflow_id": workflow, "name": "CI", "conclusion": conclusao,
        "status": "completed", "head_sha": f"sha{id_}",
        "created_at": f"{dia}T10:00:00Z", "run_started_at": f"{dia}T10:00:00Z",
        "updated_at": f"{dia}T10:05:00Z",
    }


@pytest.fixture
def janela():
    return Janela(date(2025, 10, 1), date(2026, 9, 30))


def test_meses_da_janela_cobre_12_meses_sem_buracos(janela):
    meses = wr.meses_da_janela(janela)
    assert len(meses) == 12
    assert meses[0] == (date(2025, 10, 1), date(2025, 10, 31))
    assert meses[4] == (date(2026, 2, 1), date(2026, 2, 28))
    assert meses[-1] == (date(2026, 9, 1), date(2026, 9, 30))
    for (_, fim), (inicio, _) in zip(meses, meses[1:]):
        assert (inicio - fim).days == 1


def test_meses_recortados_pela_janela():
    meses = wr.meses_da_janela(Janela(date(2025, 1, 15), date(2025, 3, 10)))
    assert meses == [
        (date(2025, 1, 15), date(2025, 1, 31)),
        (date(2025, 2, 1), date(2025, 2, 28)),
        (date(2025, 3, 1), date(2025, 3, 10)),
    ]


def test_dividir_intervalo():
    assert wr.dividir(date(2025, 1, 1), date(2025, 1, 31)) == (
        (date(2025, 1, 1), date(2025, 1, 16)),
        (date(2025, 1, 17), date(2025, 1, 31)),
    )
    assert wr.dividir(date(2025, 1, 1), date(2025, 1, 1)) is None


def test_coleta_mes_a_mes_com_filtros(janela):
    def rota(params):
        if params["created"] == "2025-10-01..2025-10-31":
            return [{"total_count": 2, "workflow_runs": [run_api(1), run_api(2, "cancelled")]}]
        return [{"total_count": 0, "workflow_runs": []}]

    cliente = ClienteFalso({CAMINHO: rota})
    runs, intervalos = wr.coletar_runs(cliente, "dono/repo", "main", "push", janela)

    assert [r.id for r in runs] == [1, 2]
    assert runs[1].conclusao == "cancelled"
    assert len(intervalos) == 12 and not any(i.truncado for i in intervalos)
    _, params = cliente.chamadas[0]
    assert params["branch"] == "main" and params["event"] == "push"


def test_mes_acima_do_teto_e_subdividido():
    janela = Janela(date(2025, 10, 1), date(2025, 10, 31))

    def rota(params):
        totais = {
            "2025-10-01..2025-10-31": 1500,  # mês inteiro passa do teto
            "2025-10-01..2025-10-16": 700,
            "2025-10-17..2025-10-31": 800,
        }
        total = totais[params["created"]]
        id_ = total  # um run representativo por intervalo
        return [{"total_count": total, "workflow_runs": [run_api(id_)]}]

    cliente = ClienteFalso({CAMINHO: rota})
    runs, intervalos = wr.coletar_runs(cliente, "dono/repo", "main", "push", janela)

    assert [(i.inicio.day, i.fim.day, i.total) for i in intervalos] == [(1, 16, 700), (17, 31, 800)]
    assert {r.id for r in runs} == {700, 800}


def test_dia_unico_acima_do_teto_fica_marcado_como_truncado():
    janela = Janela(date(2025, 10, 1), date(2025, 10, 1))
    cliente = ClienteFalso({CAMINHO: [{"total_count": 1200, "workflow_runs": [run_api(1)]}]})
    _, intervalos = wr.coletar_runs(cliente, "dono/repo", "main", "push", janela)
    assert intervalos[0].truncado


def test_contar_validos_ignora_cancelados_e_em_andamento(janela):
    cliente = ClienteFalso({CAMINHO: [{"total_count": 4, "workflow_runs": [
        run_api(1, "success"), run_api(2, "startup_failure"),
        run_api(3, "cancelled"), run_api(4, None),
    ]}]})
    runs, _ = wr.coletar_runs(cliente, "dono/repo", "main", "push", Janela(date(2025, 10, 1), date(2025, 10, 31)))
    assert wr.contar_validos(runs, SUCESSO, FALHA) == 2
