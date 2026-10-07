import pytest

from metricas.consolidacao import calcular_todos, releases_commits, runs

SUCESSO = frozenset({"success"})
FALHA = frozenset({"failure", "timed_out", "startup_failure"})
REPO = "dono/repo"


def compare(tag, anterior, status="ok", publicada="2025-03-15T00:00:00+00:00", cadeia="release"):
    return {"repositorio": REPO, "cadeia": cadeia, "tag": tag, "publicada_em": publicada,
            "tag_anterior": anterior, "status": status}


def commit(tag, anterior, data):
    return {"repositorio": REPO, "tag_anterior": anterior, "tag": tag, "data_autor": data}


def run(id_, conclusao, inicio, fim, workflow="1", criado=""):
    return {"repositorio": REPO, "id": str(id_), "workflow_id": workflow, "conclusao": conclusao,
            "iniciado_em": inicio, "atualizado_em": fim, "criado_em": criado or inicio}


@pytest.fixture
def linhas_exemplo():
    """Exemplos do enunciado: v1.1 (commits de 02/03, 10/03 e 14/03) e o episódio de 1h20."""
    compares = [
        compare("v1.0", "", status="primeira", publicada="2025-03-01T00:00:00+00:00"),
        compare("v1.1", "v1.0"),
        compare("v1.2", "v1.1", status="404", publicada="2025-03-20T00:00:00+00:00"),
        compare("v1.1-rc", "v1.0", cadeia="release_prerelease"),  # variante: fora do cálculo
    ]
    commits = [
        commit("v1.1", "v1.0", "2025-03-02T00:00:00+00:00"),
        commit("v1.1", "v1.0", "2025-03-10T00:00:00+00:00"),
        commit("v1.1", "v1.0", "2025-03-14T00:00:00+00:00"),
    ]
    linhas_runs = [
        run(1, "success", "2025-03-01T09:00:00+00:00", "2025-03-01T09:05:00+00:00"),
        run(2, "failure", "2025-03-01T10:00:00+00:00", "2025-03-01T10:05:00+00:00"),
        run(3, "failure", "2025-03-01T10:30:00+00:00", "2025-03-01T10:35:00+00:00"),
        run(4, "success", "2025-03-01T11:15:00+00:00", "2025-03-01T11:20:00+00:00"),
        run(5, "cancelled", "2025-03-01T12:00:00+00:00", "2025-03-01T12:01:00+00:00"),
    ]
    return compares, commits, linhas_runs


def test_monta_releases_da_cadeia_principal(linhas_exemplo):
    compares, commits, _ = linhas_exemplo
    releases = releases_commits(compares, commits)[REPO]
    assert [r.tag for r in releases] == ["v1.0", "v1.1", "v1.2"]
    assert releases[0].tag_anterior is None
    assert len(releases[1].datas_commits) == 3
    assert releases[2].datas_commits is None  # compare com 404


def test_release_sem_commits_novos_fica_com_tupla_vazia():
    releases = releases_commits([compare("v1.1", "v1.0")], [])[REPO]
    assert releases[0].datas_commits == ()


def test_run_sem_run_started_at_usa_created_at():
    [r] = runs([run(1, "success", "", "2025-03-01T09:05:00+00:00", criado="2025-03-01T09:00:00+00:00")])[REPO]
    assert r.iniciado_em.hour == 9 and r.iniciado_em.minute == 0


def test_metricas_do_repositorio(linhas_exemplo):
    compares, commits, linhas_runs = linhas_exemplo
    [linha] = calcular_todos([{"repositorio": REPO, "estrelas": "1500"}], compares, commits,
                             linhas_runs, semanas_janela=52.0, sucesso=SUCESSO, falha=FALHA)

    assert linha["estrelas"] == "1500"  # metadados da coleta são mantidos
    assert linha["releases_janela"] == 3
    assert linha["deploys_por_semana"] == pytest.approx(3 / 52)
    assert linha["lead_time_release_horas"] == 13 * 24
    assert linha["lead_time_commit_horas"] == 5 * 24
    assert (linha["releases_primeira"], linha["releases_compare_erro"]) == (1, 1)
    assert linha["cfr_ci"] == pytest.approx(2 / 4)  # cancelled ignorado
    assert linha["runs_ignorados"] == 1
    assert linha["recuperacao_horas"] == pytest.approx(80 / 60)  # 1h20
    assert linha["episodios_censurados"] == 0
    assert linha["classe_frequencia"] == "Low"
    assert linha["classe_lead_time"] == "Medium"
    assert linha["classe_cfr"] == "Low"
    assert linha["classe_recuperacao"] == "High"
    assert linha["classe_geral"] == "Low"  # mediana de (1, 2, 1, 3) = 1,5 -> 1


def test_repositorio_sem_runs_nem_releases_nao_quebra():
    [linha] = calcular_todos([{"repositorio": REPO}], [], [], [], 52.0, SUCESSO, FALHA)
    assert linha["releases_janela"] == 0
    assert linha["cfr_ci"] is None and linha["recuperacao_horas"] is None
    assert linha["classe_cfr"] is None
