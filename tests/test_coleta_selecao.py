from dataclasses import replace
from pathlib import Path

import pytest

from coleta import selecao as sel
from coleta.cliente import ErroAPI
from coleta.metadados import contar_contribuidores, numero_ultima_pagina
from coleta.modelos import Candidato
from pipeline.config import carregar_config
from falsos import ClienteFalso, pagina

CONFIG = carregar_config(Path(__file__).resolve().parent.parent / "config.yaml")
REPO = "dono/repo"


def item_busca(nome, estrelas=1500):
    return {
        "full_name": nome, "stargazers_count": estrelas, "language": "Python",
        "created_at": "2015-01-01T00:00:00Z", "default_branch": "main",
        "html_url": f"https://github.com/{nome}",
    }


def candidato(nome=REPO):
    return Candidato.da_api(item_busca(nome), "1000..2000")


def runs_api(conclusoes):
    """Runs em outubro/2025 (primeiro mês da janela), um por conclusão."""
    return [
        {"id": i, "workflow_id": 1, "conclusion": c,
         "created_at": "2025-10-02T00:00:00Z", "updated_at": "2025-10-02T00:00:00Z"}
        for i, c in enumerate(conclusoes)
    ]


def rotas_repo(workflows=3, releases=6, conclusoes=None, nome=REPO):
    """Rotas de um repositório que passa em todos os filtros, salvo o que for alterado."""
    runs = runs_api(conclusoes if conclusoes is not None else ["success"] * 60 + ["failure"] * 5)
    datas = [f"2026-0{m}-01T00:00:00Z" for m in range(1, 10)][:releases]
    return {
        f"/repos/{nome}/actions/workflows": [{"total_count": workflows}],
        f"/repos/{nome}/releases": [[
            {"tag_name": f"v{i}", "draft": False, "prerelease": False, "published_at": d}
            for i, d in enumerate(datas)
        ]],
        f"/repos/{nome}/actions/runs": lambda p: [
            {"total_count": len(runs), "workflow_runs": runs} if p["created"].startswith("2025-10")
            else {"total_count": 0, "workflow_runs": []}
        ],
    }


def test_consulta_das_faixas():
    assert sel.consulta_faixa(1000, 2000, "fork:false") == "stars:1000..2000 fork:false"
    assert sel.consulta_faixa(50000, None) == "stars:>=50000"


class BuscaFalsa:
    """Imita a busca do GitHub: filtra por estrelas, ordena do maior para o menor e
    devolve no máximo 1.000 resultados, em páginas de 100."""

    def __init__(self, estrelas_por_repo):
        self.repos = estrelas_por_repo
        self.consultas = []

    def __call__(self, params):
        self.consultas.append(params["q"])
        faixa = params["q"].split()[0].removeprefix("stars:")
        if faixa.startswith(">="):
            minimo, maximo = int(faixa[2:]), float("inf")
        else:
            minimo, maximo = map(int, faixa.split(".."))
        achados = sorted(((n, e) for n, e in self.repos.items() if minimo <= e <= maximo),
                         key=lambda par: -par[1])
        visiveis = achados[:1000]
        paginas = [visiveis[i:i + 100] for i in range(0, len(visiveis), 100)] or [[]]
        return [{"total_count": len(achados), "items": [item_busca(n, e) for n, e in pagina]}
                for pagina in paginas]


def test_faixa_acima_do_teto_e_subdividida_ate_trazer_todos():
    repos = {f"dono/r{i}": 1000 + i % 1001 for i in range(2500)}  # 2.500 entre 1.000 e 2.000
    cliente = ClienteFalso({"/search/repositories": BuscaFalsa(repos)})

    candidatos, faixas = sel.buscar_candidatos(cliente, [(1000, 2000)], "fork:false")

    assert len(candidatos) == 2500  # nenhum cortado pelo teto
    assert min(c.estrelas for c in candidatos) == 1000
    assert all(f.faixa == "1000..2000" and f.obtidos == f.disponiveis <= 1000 for f in faixas)
    assert len(faixas) > 1
    assert sum(f.disponiveis for f in faixas) == 2500
    assert all(f.consulta.endswith("fork:false") for f in faixas)
    assert {c.subintervalo for c in candidatos} == {f.subintervalo for f in faixas}


def test_faixa_dentro_do_teto_e_uma_consulta_so():
    repos = {f"dono/r{i}": 1500 + i for i in range(300)}
    busca = BuscaFalsa(repos)
    _, faixas = sel.buscar_candidatos(ClienteFalso({"/search/repositories": busca}), [(1000, 2000)])
    assert len(busca.consultas) == 1
    assert [(f.subintervalo, f.disponiveis, f.obtidos) for f in faixas] == [("1000..2000", 300, 300)]


def test_faixa_aberta_acima_do_teto_usa_o_maior_como_limite():
    repos = {f"dono/r{i}": 50000 + i * 10 for i in range(1500)}
    candidatos, faixas = sel.buscar_candidatos(
        ClienteFalso({"/search/repositories": BuscaFalsa(repos)}), [(50000, None)]
    )
    assert len(candidatos) == 1500
    assert all(f.faixa == ">=50000" for f in faixas)


def test_mais_de_mil_com_o_mesmo_numero_de_estrelas_fica_registrado():
    repos = {f"dono/r{i}": 1000 for i in range(1200)}
    candidatos, faixas = sel.buscar_candidatos(
        ClienteFalso({"/search/repositories": BuscaFalsa(repos)}), [(1000, 1000)]
    )
    assert len(candidatos) == 1000
    assert [(f.disponiveis, f.obtidos) for f in faixas] == [(1200, 1000)]


def test_faixas_vizinhas_nao_repetem_candidatos():
    repos = {"dono/borda": 2000, "dono/a": 1500, "dono/b": 3000}
    candidatos, _ = sel.buscar_candidatos(
        ClienteFalso({"/search/repositories": BuscaFalsa(repos)}), [(1000, 2000), (2000, 5000)]
    )
    assert sorted(c.nome for c in candidatos) == ["dono/a", "dono/b", "dono/borda"]
    assert next(c for c in candidatos if c.nome == "dono/borda").faixa == "1000..2000"


def test_embaralhar_e_reproduzivel_e_nao_depende_da_ordem_da_api():
    candidatos = [candidato(f"dono/r{i}") for i in range(20)]
    a = sel.embaralhar(candidatos, 42)
    b = sel.embaralhar(list(reversed(candidatos)), 42)
    assert a == b
    assert a != sorted(candidatos, key=lambda c: c.nome)
    assert sel.embaralhar(candidatos, 7) != a  # outra semente, outra ordem


def test_trocar_um_candidato_nao_reembaralha_os_demais():
    candidatos = [candidato(f"dono/r{i}") for i in range(50)]
    antes = sel.embaralhar(candidatos, 42)
    depois = sel.embaralhar(candidatos[1:] + [candidato("dono/novo")], 42)
    sem_trocados = lambda lista: [c.nome for c in lista if c.nome not in ("dono/r0", "dono/novo")]
    assert sem_trocados(antes) == sem_trocados(depois)


def test_descarta_sem_actions_antes_de_buscar_releases():
    cliente = ClienteFalso(rotas_repo(workflows=0))
    avaliacao = sel.avaliar(cliente, candidato(), CONFIG)
    assert avaliacao.motivo == sel.SEM_ACTIONS
    assert cliente.caminhos() == [f"/repos/{REPO}/actions/workflows"]


def test_descarta_com_poucas_releases():
    avaliacao = sel.avaliar(ClienteFalso(rotas_repo(releases=4)), candidato(), CONFIG)
    assert (avaliacao.motivo, avaliacao.n_releases_janela) == (sel.POUCAS_RELEASES, 4)


def test_inclui_quando_passa_em_tudo():
    avaliacao = sel.avaliar(ClienteFalso(rotas_repo()), candidato(), CONFIG)
    assert avaliacao.incluido
    assert (avaliacao.n_workflows, avaliacao.n_releases_janela, avaliacao.n_runs_validos) == (3, 6, 65)


def test_conta_startup_failure_e_ignora_cancelados():
    # 45 sucessos + 5 startup_failure = 50 válidos; os cancelados não contam.
    rotas = rotas_repo(conclusoes=["success"] * 45 + ["startup_failure"] * 5 + ["cancelled"] * 20)
    avaliacao = sel.avaliar(ClienteFalso(rotas), candidato(), CONFIG)
    assert avaliacao.incluido and avaliacao.n_runs_validos == 50


def test_descarta_com_poucos_runs_validos():
    rotas = rotas_repo(conclusoes=["success"] * 10 + ["cancelled"] * 100 + [None] * 5)
    avaliacao = sel.avaliar(ClienteFalso(rotas), candidato(), CONFIG)
    assert (avaliacao.motivo, avaliacao.n_runs_validos) == (sel.POUCOS_RUNS, 10)


def test_erro_definitivo_da_api_descarta_o_candidato():
    avaliacao = sel.avaliar(ClienteFalso({}), candidato(), CONFIG)
    assert avaliacao.motivo == sel.ERRO_API


def test_erro_temporario_interrompe_a_coleta():
    cliente = ClienteFalso({f"/repos/{REPO}/actions/workflows": ErroAPI("falhou", status=None)})
    with pytest.raises(ErroAPI):
        sel.avaliar(cliente, candidato(), CONFIG)


def test_selecionar_para_quando_a_amostra_enche_e_resume_o_funil():
    config = replace(CONFIG, selecao=replace(CONFIG.selecao, tamanho_amostra=2))
    nomes = ["a/sem-actions", "b/ok", "c/poucas", "d/ok", "e/ok"]
    rotas = {}
    rotas.update(rotas_repo(workflows=0, nome="a/sem-actions"))
    rotas.update(rotas_repo(nome="b/ok"))
    rotas.update(rotas_repo(releases=1, nome="c/poucas"))
    rotas.update(rotas_repo(nome="d/ok"))

    avaliacoes = sel.selecionar(ClienteFalso(rotas), [candidato(n) for n in nomes], config)

    assert [a.motivo for a in avaliacoes] == [
        sel.SEM_ACTIONS, sel.INCLUIDO, sel.POUCAS_RELEASES, sel.INCLUIDO, sel.NAO_AVALIADO,
    ]
    resumo = {e.etapa: e.restantes for e in sel.resumir_funil(avaliacoes)}
    assert resumo == {
        "candidatos": 5, "avaliados": 4, "acessiveis_pela_api": 4, "usam_actions": 3,
        "com_min_releases": 2, "com_min_runs_validos": 2, "amostra_final": 2,
    }


def test_ultima_pagina_do_link():
    links = {"next": "https://api.github.com/x?page=2", "last": "https://api.github.com/x?per_page=1&page=347"}
    assert numero_ultima_pagina(links) == 347
    assert numero_ultima_pagina({}) is None


@pytest.mark.parametrize("resposta, esperado", [
    (pagina([{"login": "a"}], {"last": "https://api.github.com/x?anon=true&page=12&per_page=1"}), 12),
    (pagina([{"login": "a"}]), 1),  # um único contribuidor: sem Link
    (pagina(None), 0),  # repositório vazio: 204 sem corpo
])
def test_contar_contribuidores(resposta, esperado):
    cliente = ClienteFalso({f"/repos/{REPO}/contributors": [resposta]})
    assert contar_contribuidores(cliente, REPO) == esperado
    assert cliente.chamadas[0][1] == {"per_page": 1, "anon": "true"}


def test_contribuidores_indisponiveis_viram_none():
    cliente = ClienteFalso({f"/repos/{REPO}/contributors": ErroAPI("too large", status=403)})
    assert contar_contribuidores(cliente, REPO) is None
