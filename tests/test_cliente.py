import json

import pytest
import requests
from requests.structures import CaseInsensitiveDict

from coleta.cache import CacheRespostas, url_canonica
from coleta.cliente import ClienteGitHub, ErroAPI, ler_cabecalho_link

API = "https://api.github.com"


def resposta(status=200, corpo=None, headers=None):
    r = requests.Response()
    r.status_code = status
    r._content = b"" if corpo is None else json.dumps(corpo).encode()
    r.headers = CaseInsensitiveDict(headers or {})
    return r


class SessaoFalsa:
    """Devolve as respostas em ordem e registra as URLs pedidas."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.urls = []
        self.corpos = []
        self.headers = {}

    def get(self, url, timeout):
        self.urls.append(url)
        item = self.respostas.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def post(self, url, json, timeout):
        self.urls.append(url)
        self.corpos.append(json)
        item = self.respostas.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        pass


class Relogio:
    def __init__(self, agora=1_000_000.0):
        self.agora = agora
        self.esperas = []

    def __call__(self):
        return self.agora

    def dormir(self, segundos):
        self.esperas.append(segundos)
        self.agora += segundos


@pytest.fixture
def relogio():
    return Relogio()


@pytest.fixture
def cache(tmp_path):
    c = CacheRespostas(tmp_path / "api.sqlite")
    yield c
    c.fechar()


def criar_cliente(cache, relogio, respostas, **kwargs):
    sessao = SessaoFalsa(respostas)
    cliente = ClienteGitHub(
        "tok", cache, sessao=sessao, dormir=relogio.dormir, relogio=relogio, **kwargs
    )
    return cliente, sessao


def test_ler_cabecalho_link():
    valor = (
        f'<{API}/repos/o/r/releases?page=2>; rel="next", '
        f'<{API}/repos/o/r/releases?page=5>; rel="last"'
    )
    assert ler_cabecalho_link(valor) == {
        "next": f"{API}/repos/o/r/releases?page=2",
        "last": f"{API}/repos/o/r/releases?page=5",
    }
    assert ler_cabecalho_link(None) == {}
    assert ler_cabecalho_link("") == {}


def test_url_canonica_ordena_parametros():
    assert url_canonica(f"{API}/x?b=2&a=1") == url_canonica(f"{API}/x?a=1&b=2")


def test_cabecalhos_de_autenticacao(cache, relogio):
    cliente, sessao = criar_cliente(cache, relogio, [])
    assert sessao.headers["Authorization"] == "Bearer tok"
    assert sessao.headers["Accept"] == "application/vnd.github+json"


def test_segunda_chamada_vem_do_cache(cache, relogio):
    cliente, sessao = criar_cliente(cache, relogio, [resposta(corpo={"id": 1})])
    primeira = cliente.obter("/repos/o/r", {"x": 1})
    segunda = cliente.obter("/repos/o/r", {"x": 1})
    assert primeira.dados == segunda.dados == {"id": 1}
    assert not primeira.do_cache and segunda.do_cache
    assert len(sessao.urls) == 1
    assert (cliente.chamadas_api, cliente.acertos_cache) == (1, 1)


def test_retomada_entre_execucoes(tmp_path, relogio):
    caminho = tmp_path / "api.sqlite"
    cache1 = CacheRespostas(caminho)
    cliente1, _ = criar_cliente(cache1, relogio, [resposta(corpo=[1, 2])])
    cliente1.obter("/repos/o/r/releases")
    cliente1.fechar()

    # Sem respostas roteirizadas: qualquer chamada à API falharia.
    cache2 = CacheRespostas(caminho)
    cliente2, sessao2 = criar_cliente(cache2, relogio, [])
    assert cliente2.obter("/repos/o/r/releases").dados == [1, 2]
    assert sessao2.urls == []
    cliente2.fechar()


def test_404_fica_em_cache_e_nao_e_repetido(cache, relogio):
    cliente, sessao = criar_cliente(
        cache, relogio, [resposta(404, {"message": "Not Found"})]
    )
    for _ in range(2):
        with pytest.raises(ErroAPI) as erro:
            cliente.obter("/repos/o/r/compare/v1...v2")
        assert erro.value.status == 404
    assert len(sessao.urls) == 1


def test_erro_401_nao_vai_para_o_cache(cache, relogio):
    cliente, _ = criar_cliente(cache, relogio, [resposta(401, {"message": "Bad credentials"})])
    with pytest.raises(ErroAPI, match="Bad credentials"):
        cliente.obter("/user")
    assert len(cache) == 0


def test_usar_cache_falso_sempre_consulta_a_api(cache, relogio):
    cliente, sessao = criar_cliente(
        cache, relogio, [resposta(corpo={"a": 1}), resposta(corpo={"a": 2})]
    )
    assert cliente.rate_limit() == {"a": 1}
    assert cliente.rate_limit() == {"a": 2}
    assert len(sessao.urls) == 2
    assert len(cache) == 0


def test_resposta_sem_corpo(cache, relogio):
    cliente, _ = criar_cliente(cache, relogio, [resposta(204)])
    assert cliente.obter("/repos/o/r/contributors").dados is None
    assert cliente.obter("/repos/o/r/contributors").do_cache


def test_paginacao_segue_link_next(cache, relogio):
    pag2 = f"{API}/repos/o/r/releases?per_page=2&page=2"
    pag3 = f"{API}/repos/o/r/releases?per_page=2&page=3"
    cliente, sessao = criar_cliente(cache, relogio, [
        resposta(corpo=[1, 2], headers={"Link": f'<{pag2}>; rel="next", <{pag3}>; rel="last"'}),
        resposta(corpo=[3, 4], headers={"Link": f'<{pag3}>; rel="next"'}),
        resposta(corpo=[5]),
    ])
    assert list(cliente.paginar("/repos/o/r/releases", {"per_page": 2})) == [1, 2, 3, 4, 5]
    assert sessao.urls[1:] == [pag2, pag3]

    # Na reexecução, páginas e links vêm do cache.
    assert list(cliente.paginar("/repos/o/r/releases", {"per_page": 2})) == [1, 2, 3, 4, 5]
    assert len(sessao.urls) == 3


def test_paginacao_com_chave_de_itens(cache, relogio):
    cliente, _ = criar_cliente(cache, relogio, [
        resposta(corpo={"total_count": 2, "workflow_runs": [{"id": 1}, {"id": 2}]})
    ])
    runs = list(cliente.paginar("/repos/o/r/actions/runs", chave_itens="workflow_runs"))
    assert [r["id"] for r in runs] == [1, 2]


def test_paginacao_max_paginas(cache, relogio):
    proxima = f"{API}/x?page=2"
    cliente, sessao = criar_cliente(cache, relogio, [
        resposta(corpo=[1], headers={"Link": f'<{proxima}>; rel="next"'}),
    ])
    assert list(cliente.paginar("/x", max_paginas=1)) == [1]
    assert len(sessao.urls) == 1


def test_link_last_disponivel_para_contar_paginas(cache, relogio):
    ultima = f"{API}/repos/o/r/contributors?per_page=1&anon=true&page=137"
    cliente, _ = criar_cliente(cache, relogio, [
        resposta(corpo=[{}], headers={"Link": f'<{ultima}>; rel="last"'}),
    ])
    r = cliente.obter("/repos/o/r/contributors", {"per_page": 1, "anon": "true"})
    assert r.links["last"] == ultima


def test_5xx_repetido_com_backoff_exponencial(cache, relogio):
    cliente, sessao = criar_cliente(cache, relogio, [
        resposta(502), resposta(503), resposta(500), resposta(corpo={"ok": True}),
    ])
    assert cliente.obter("/x").dados == {"ok": True}
    assert relogio.esperas == [1, 2, 4]
    assert len(sessao.urls) == 4


def test_5xx_desiste_apos_max_tentativas(cache, relogio):
    cliente, sessao = criar_cliente(
        cache, relogio, [resposta(500)] * 3, max_tentativas=3
    )
    with pytest.raises(ErroAPI) as erro:
        cliente.obter("/x")
    assert erro.value.status == 500
    assert relogio.esperas == [1, 2]
    assert len(cache) == 0


def test_erro_de_rede_tambem_tem_backoff(cache, relogio):
    cliente, _ = criar_cliente(cache, relogio, [
        requests.ConnectionError("caiu"), requests.Timeout("lento"), resposta(corpo=[]),
    ])
    assert cliente.obter("/x").dados == []
    assert relogio.esperas == [1, 2]


def cota(restantes, reset, recurso="core"):
    return {
        "X-RateLimit-Remaining": str(restantes),
        "X-RateLimit-Reset": str(int(reset)),
        "X-RateLimit-Resource": recurso,
    }


def test_pausa_quando_cota_acaba(cache, relogio):
    reset = relogio.agora + 600
    cliente, _ = criar_cliente(cache, relogio, [
        resposta(corpo=1, headers=cota(1, reset)),
        resposta(corpo=2, headers=cota(0, reset)),
        resposta(corpo=3, headers=cota(4999, reset + 3600)),
    ])
    cliente.obter("/a")
    cliente.obter("/b")
    assert relogio.esperas == []
    cliente.obter("/c")
    assert relogio.esperas == [pytest.approx(602)]  # reset + margem


def test_403_por_cota_esgotada_espera_e_repete(cache, relogio):
    reset = relogio.agora + 120
    cliente, sessao = criar_cliente(cache, relogio, [
        resposta(403, {"message": "API rate limit exceeded"}, cota(0, reset)),
        resposta(corpo={"ok": True}, headers=cota(4999, reset + 3600)),
    ], max_tentativas=1)
    # Esperar a cota não gasta tentativa.
    assert cliente.obter("/x").dados == {"ok": True}
    assert relogio.esperas == [pytest.approx(122)]
    assert len(sessao.urls) == 2


def test_cotas_separadas_por_recurso(cache, relogio):
    reset = relogio.agora + 30
    cliente, _ = criar_cliente(cache, relogio, [
        resposta(corpo={"items": []}, headers=cota(0, reset, "search")),
        resposta(corpo=[], headers=cota(4000, reset + 3600)),
        resposta(corpo={"items": []}, headers=cota(29, reset + 60, "search")),
    ])
    cliente.obter("/search/repositories", {"q": "stars:>1000"})
    cliente.obter("/repos/o/r/releases")
    assert relogio.esperas == []
    cliente.obter("/search/repositories", {"q": "stars:1000..2000"})
    assert relogio.esperas == [pytest.approx(32)]


def test_reset_no_passado_ainda_espera_a_margem(cache, relogio):
    cliente, _ = criar_cliente(cache, relogio, [
        resposta(corpo=1, headers=cota(0, relogio.agora - 50)),
        resposta(corpo=2),
    ])
    cliente.obter("/a")
    cliente.obter("/b")
    assert relogio.esperas == [pytest.approx(2)]


def test_limite_secundario_respeita_retry_after(cache, relogio):
    cliente, _ = criar_cliente(cache, relogio, [
        resposta(403, {"message": "secondary rate limit"}, {"Retry-After": "45"}),
        resposta(corpo={"ok": True}),
    ])
    assert cliente.obter("/x").dados == {"ok": True}
    assert relogio.esperas == [45]


def test_limite_secundario_sem_retry_after_espera_um_minuto(cache, relogio):
    cliente, _ = criar_cliente(cache, relogio, [
        resposta(403, {"message": "You have exceeded a secondary rate limit"}),
        resposta(corpo={"ok": True}),
    ])
    cliente.obter("/x")
    assert relogio.esperas == [60]


def test_403_que_nao_e_rate_limit_falha_direto(cache, relogio):
    cliente, sessao = criar_cliente(cache, relogio, [
        resposta(403, {"message": "Resource not accessible by integration"}),
    ])
    with pytest.raises(ErroAPI) as erro:
        cliente.obter("/x")
    assert erro.value.status == 403
    assert relogio.esperas == []
    assert len(sessao.urls) == 1


def test_de_config_cria_cache_na_pasta_configurada(tmp_path):
    from pathlib import Path

    from pipeline.config import carregar_config

    projeto = Path(__file__).resolve().parent.parent / "config.yaml"
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text(projeto.read_text(encoding="utf-8"), encoding="utf-8")
    config = carregar_config(config_yaml)

    with ClienteGitHub.de_config(config, "tok") as cliente:
        assert cliente.max_tentativas == config.coleta.max_tentativas
        assert cliente.backoff_inicial == config.coleta.backoff_inicial_segundos
    assert (tmp_path / "cache" / "api.sqlite").is_file()


def test_graphql_faz_post_e_guarda_no_cache(cache, relogio):
    cliente, sessao = criar_cliente(cache, relogio, [resposta(corpo={"data": {"x": 1}})])
    assert cliente.graphql("query { x }", {"a": 1}) == {"x": 1}
    assert cliente.graphql("query { x }", {"a": 1}) == {"x": 1}
    assert sessao.urls == [f"{API}/graphql"]
    assert sessao.corpos == [{"query": "query { x }", "variables": {"a": 1}}]
    assert cliente.acertos_cache == 1


def test_graphql_variaveis_diferentes_nao_compartilham_cache(cache, relogio):
    cliente, sessao = criar_cliente(cache, relogio, [
        resposta(corpo={"data": {"pagina": 1}}), resposta(corpo={"data": {"pagina": 2}}),
    ])
    assert cliente.graphql("q", {"cursor": None}) == {"pagina": 1}
    assert cliente.graphql("q", {"cursor": "abc"}) == {"pagina": 2}
    assert len(sessao.urls) == 2


def test_graphql_not_found_vira_404_e_nao_vai_para_o_cache(cache, relogio):
    erro = {"data": {"repository": None}, "errors": [{"type": "NOT_FOUND", "message": "não existe"}]}
    cliente, _ = criar_cliente(cache, relogio, [resposta(corpo=erro)])
    with pytest.raises(ErroAPI) as info:
        cliente.graphql("q")
    assert info.value.status == 404
    assert len(cache) == 0


def test_graphql_rate_limited_espera_a_renovacao_e_repete(cache, relogio):
    reset = relogio.agora + 600
    esgotada = resposta(
        corpo={"errors": [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}]},
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset),
                 "X-RateLimit-Resource": "graphql"},
    )
    cliente, sessao = criar_cliente(cache, relogio, [esgotada, resposta(corpo={"data": {"ok": True}})])
    assert cliente.graphql("q") == {"ok": True}
    assert len(sessao.urls) == 2
    assert relogio.esperas and relogio.esperas[0] >= 600


def test_graphql_5xx_repete_com_backoff(cache, relogio):
    cliente, sessao = criar_cliente(cache, relogio, [
        resposta(status=502), resposta(corpo={"data": {"ok": True}}),
    ])
    assert cliente.graphql("q") == {"ok": True}
    assert relogio.esperas == [1.0]


def test_cache_comprime_o_corpo_e_le_entradas_antigas_em_texto(cache):
    corpo = {"workflow_runs": [{"id": i, "name": "CI"} for i in range(200)]}
    cache.gravar(f"{API}/repos/o/r/actions/runs", 200, corpo, {})
    bruto = cache._conexao.execute("SELECT corpo FROM respostas").fetchone()[0]
    assert isinstance(bruto, bytes) and len(bruto) < len(json.dumps(corpo)) / 5
    assert cache.obter(f"{API}/repos/o/r/actions/runs").dados == corpo

    # Entrada gravada por uma versão anterior do cache, com o JSON como texto.
    cache._conexao.execute(
        "INSERT INTO respostas VALUES (?, 200, ?, '{}', '2026-01-01')",
        (url_canonica(f"{API}/antigo"), json.dumps({"x": 1})),
    )
    assert cache.obter(f"{API}/antigo").dados == {"x": 1}
