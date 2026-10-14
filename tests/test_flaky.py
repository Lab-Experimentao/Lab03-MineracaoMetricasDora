from datetime import datetime, timedelta, timezone

import pytest

from metricas.consolidacao import calcular_todos, runs_ci
from metricas.flaky import RunCI, falhas_seguidas_de_sucesso, separar_flaky

INICIO = datetime(2025, 3, 1, 9, tzinfo=timezone.utc)
SUCESSO = frozenset({"success"})
FALHA = frozenset({"failure", "timed_out", "startup_failure"})


def run(id_, conclusao, horas, sha="a", workflow=1, tentativa=1):
    return RunCI(id_, workflow, sha, tentativa, conclusao, INICIO + timedelta(hours=horas))


def test_falha_seguida_de_sucesso_no_mesmo_commit_e_flaky():
    runs = [run(1, "failure", 0), run(2, "success", 1)]
    assert falhas_seguidas_de_sucesso(runs) == {1}


@pytest.mark.parametrize("runs", [
    [run(1, "failure", 0, sha="a"), run(2, "success", 1, sha="b")],  # outro commit
    [run(1, "failure", 0, workflow=1), run(2, "success", 1, workflow=2)],  # outro workflow
    [run(1, "success", 0), run(2, "failure", 1)],  # sucesso antes da falha
    [run(1, "failure", 0), run(2, "cancelled", 1)],  # cancelado não é sucesso
    [run(1, "failure", 0, sha=""), run(2, "success", 1, sha="")],  # sem commit
])
def test_nao_e_flaky(runs):
    assert falhas_seguidas_de_sucesso(runs) == set()


def test_varias_falhas_antes_do_sucesso_e_timed_out_contam():
    runs = [run(1, "failure", 0), run(2, "timed_out", 1), run(3, "success", 2), run(4, "failure", 3)]
    assert falhas_seguidas_de_sucesso(runs) == {1, 2}


def test_separar_flaky_conta_reexecucoes_e_recalcula_o_cfr():
    runs = [
        run(1, "failure", 0), run(2, "success", 1),  # flaky no mesmo commit
        run(3, "success", 2, sha="b", tentativa=2),  # reexecutado que passou
        run(4, "failure", 3, sha="c", tentativa=3),  # reexecutado que falhou de novo
        run(5, "success", 4, sha="d"),
    ]
    resultado = separar_flaky(runs, SUCESSO, FALHA)
    assert (resultado.reexecutados, resultado.reexecutados_com_sucesso) == (2, 1)
    assert resultado.falhas_mesmo_commit == 1
    # Original: 2 falhas em 5 runs; sem a flaky: 1 falha em 4.
    assert resultado.cfr_sem_flaky.taxa == pytest.approx(1 / 4)
    assert (resultado.cfr_sem_flaky.falhas, resultado.cfr_sem_flaky.sucessos) == (1, 3)


def test_sem_runs():
    resultado = separar_flaky([], SUCESSO, FALHA)
    assert resultado.cfr_sem_flaky.taxa is None and resultado.reexecutados == 0


def linha(id_, conclusao, inicio, sha="a", tentativa="1"):
    return {"repositorio": "d/r", "id": str(id_), "workflow_id": "1", "conclusao": conclusao,
            "iniciado_em": inicio, "criado_em": inicio, "atualizado_em": inicio,
            "head_sha": sha, "tentativa": tentativa}


def test_runs_ci_le_o_csv_e_aceita_arquivo_sem_tentativa():
    antigo = linha(1, "failure", "2025-03-01T09:00:00+00:00")
    del antigo["tentativa"]
    [r] = runs_ci([antigo])["d/r"]
    assert (r.id, r.tentativa, r.head_sha, r.conclusao) == (1, 1, "a", "failure")


def test_colunas_no_metricas():
    linhas = [
        linha(1, "failure", "2025-03-01T09:00:00+00:00"),
        linha(2, "success", "2025-03-01T10:00:00+00:00", tentativa="2"),
        linha(3, "success", "2025-03-01T11:00:00+00:00", sha="b"),
    ]
    [m] = calcular_todos([{"repositorio": "d/r"}], [], [], linhas, 52.0, SUCESSO, FALHA,
                         fim_janela=INICIO + timedelta(days=30), dias_corretiva=7)
    assert m["cfr_ci"] == pytest.approx(1 / 3)
    assert m["cfr_ci_sem_flaky"] == 0.0
    assert (m["falhas_flaky_mesmo_commit"], m["runs_reexecutados"], m["runs_flaky_reexecucao"]) == (1, 1, 1)
