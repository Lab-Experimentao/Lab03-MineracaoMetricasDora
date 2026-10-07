from datetime import date, datetime, timezone

import pytest

from coleta import releases as rel
from coleta.cliente import ErroAPI
from coleta.modelos import Release, Tag
from pipeline.config import Janela
from falsos import ClienteFalso, pagina

JANELA = Janela(date(2025, 10, 1), date(2026, 9, 30))


def quando(ano, mes, dia):
    return datetime(ano, mes, dia, tzinfo=timezone.utc)


def release(tag, data, draft=False, prerelease=False):
    return Release(tag, data, draft, prerelease, f"https://github.com/dono/repo/releases/tag/{tag}")


def test_release_da_api_draft_sem_data():
    r = Release.da_api({"tag_name": "v1", "draft": True, "prerelease": False, "published_at": None})
    assert r.draft and r.publicada_em is None


def test_releases_publicadas_exclui_draft_e_opcionalmente_prerelease():
    releases = [
        release("v1", quando(2025, 11, 1)),
        release("v2-rc", quando(2025, 11, 2), prerelease=True),
        release("v3", None, draft=True),
    ]
    assert [r.tag for r in rel.releases_publicadas(releases, False)] == ["v1"]
    assert [r.tag for r in rel.releases_publicadas(releases, True)] == ["v1", "v2-rc"]


def test_contar_releases_janela_usa_so_a_definicao_principal():
    releases = [
        release("v0", quando(2025, 9, 30)),  # antes da janela
        release("v1", quando(2025, 10, 1)),
        release("v2", quando(2026, 9, 30)),
        release("v3-rc", quando(2026, 1, 1), prerelease=True),
        release("v4", quando(2026, 10, 1)),  # depois da janela
    ]
    assert rel.contar_releases_janela(releases, JANELA) == 2


def test_par_usa_anterior_fora_da_janela_e_ignora_itens_fora_dela():
    itens = [("v2", quando(2025, 12, 1)), ("v1", quando(2025, 6, 1)), ("v3", quando(2026, 2, 1))]
    pares = rel.montar_pares(rel.CADEIA_RELEASE, itens, JANELA)
    assert [(p.tag, p.tag_anterior) for p in pares] == [("v2", "v1"), ("v3", "v2")]


def test_primeira_release_da_historia_fica_sem_anterior():
    pares = rel.montar_pares(rel.CADEIA_RELEASE, [("v1", quando(2025, 11, 1))], JANELA)
    assert pares[0].tag_anterior is None


def test_tres_cadeias_do_repositorio():
    releases = [
        release("v1", quando(2025, 11, 1)),
        release("v2-rc", quando(2025, 11, 5), prerelease=True),
        release("v2", quando(2025, 11, 10)),
    ]
    tags = [
        Tag("v1", "a", quando(2025, 10, 30), None),
        Tag("v2", "b", quando(2025, 11, 9), None),
        Tag("sem-data", "c", None, None),
    ]
    pares = {(p.cadeia, p.tag): p.tag_anterior for p in rel.pares_do_repositorio(releases, tags, JANELA)}
    assert pares == {
        ("release", "v1"): None,
        ("release", "v2"): "v1",
        ("release_prerelease", "v1"): None,
        ("release_prerelease", "v2-rc"): "v1",
        ("release_prerelease", "v2"): "v2-rc",
        ("tag", "v1"): None,
        ("tag", "v2"): "v1",
    }


def commit_gql(oid, autor, committer=None):
    return {"oid": oid, "author": {"date": autor}, "committer": {"date": committer or autor}}


def test_listar_tags_pagina_e_resolve_tags_leves_e_anotadas():
    paginas = {
        None: {
            "nodes": [
                {"name": "v1", "target": commit_gql("abc", "2025-10-02T00:00:00Z", "2025-10-03T00:00:00Z")},
                {"name": "v2", "target": {"target": commit_gql("def", "2025-11-01T00:00:00Z")}},  # anotada
            ],
            "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
        },
        "c1": {
            "nodes": [{"name": "arvore", "target": {}}],  # tag que não aponta para commit
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        },
    }
    cliente = ClienteFalso({"graphql": lambda v: {"repository": {"refs": paginas[v["cursor"]]}}})

    tags = rel.listar_tags(cliente, "dono/repo")

    assert tags == [
        Tag("v1", "abc", quando(2025, 10, 2), quando(2025, 10, 3)),
        Tag("v2", "def", quando(2025, 11, 1), quando(2025, 11, 1)),
        Tag("arvore", "", None, None),
    ]
    assert [v for _, v in cliente.chamadas] == [
        {"dono": "dono", "nome": "repo", "cursor": None},
        {"dono": "dono", "nome": "repo", "cursor": "c1"},
    ]


def test_datas_com_fuso_sao_convertidas_para_utc():
    from coleta.modelos import ler_data
    assert ler_data("2026-10-01T13:40:09-04:00") == datetime(2026, 10, 1, 17, 40, 9, tzinfo=timezone.utc)
    assert ler_data("2026-10-01T13:40:09Z").utcoffset().total_seconds() == 0


def test_repositorio_sem_tags():
    cliente = ClienteFalso({"graphql": {"repository": {"refs": {"nodes": [], "pageInfo": {"hasNextPage": False}}}}})
    assert rel.listar_tags(cliente, "dono/repo") == []


class ServidorCompare:
    """Simula `ref.compare` da GraphQL: `compares` mapeia (base, head) -> nº de commits,
    "erro" (o par derruba a consulta com o HTTP dado) ou ausência (ref inexistente)."""

    def __init__(self, compares, erros=None):
        self.compares = compares
        self.erros = erros or {}
        self.consultas = []

    def __call__(self, v):
        self.consultas.append(v)
        repositorio = {}
        i = 0
        while f"b{i}" in v:
            base, head = v[f"b{i}"].removeprefix("refs/tags/"), v[f"h{i}"].removeprefix("refs/tags/")
            if (base, head) in self.erros:
                return ErroAPI("falhou", status=self.erros[(base, head)])
            total = self.compares.get((base, head))
            if total is None:
                repositorio[f"p{i}"] = None
            else:
                inicio = int(v[f"c{i}"] or 0)
                fim = min(inicio + 100, total)
                repositorio[f"p{i}"] = {"compare": {
                    "status": "AHEAD" if total else "BEHIND", "aheadBy": total,
                    "commits": {
                        "pageInfo": {"hasNextPage": fim < total, "endCursor": str(fim)},
                        "nodes": [{"oid": f"{head}-{n}", "authoredDate": "2025-10-01T00:00:00Z",
                                   "message": f"fix: item {n}\n\ncorpo"} for n in range(inicio, fim)],
                    },
                }}
            i += 1
        return {"repository": repositorio}


def par(tag, anterior, cadeia=rel.CADEIA_RELEASE):
    return rel.Par(cadeia, tag, quando(2025, 11, 1), anterior)


def test_consulta_tem_um_alias_por_compare():
    consulta = rel.consulta_compares(2)
    assert "p0: ref(qualifiedName: $b0)" in consulta and "p1: ref(qualifiedName: $b1)" in consulta
    assert "message" in consulta and "messageHeadline" not in consulta


def test_compare_pagina_alem_de_250_e_guarda_mensagem_completa():
    servidor = ServidorCompare({("v1", "v2"): 256})
    cliente = ClienteFalso({"graphql": servidor})

    [resultado] = rel.coletar_compares(cliente, "dono/repo", [par("v2", "v1")], {"v1", "v2"}).values()

    assert (resultado.status, resultado.divergencia, resultado.total_commits) == ("ok", "ahead", 256)
    assert len(resultado.commits) == 256 and len(servidor.consultas) == 3
    assert resultado.commits[0].mensagem == "fix: item 0\n\ncorpo"
    assert resultado.commits[0].titulo == "fix: item 0"
    assert servidor.consultas[0]["b0"] == "refs/tags/v1" and servidor.consultas[0]["h0"] == "refs/tags/v2"


def test_compares_vao_em_lotes():
    pares = [par(f"v{i}", f"v{i - 1}") for i in range(1, 8)]
    servidor = ServidorCompare({(f"v{i - 1}", f"v{i}"): 3 for i in range(1, 8)})
    resultados = rel.coletar_compares(ClienteFalso({"graphql": servidor}), "dono/repo", pares,
                                      {f"v{i}" for i in range(8)})
    assert len(resultados) == 7
    assert len(servidor.consultas) == 2  # lotes de 5 + 2


def test_par_repetido_entre_cadeias_e_primeira_release():
    pares = [par("v1", None), par("v2", "v1"), par("v2", "v1", rel.CADEIA_TAG)]
    servidor = ServidorCompare({("v1", "v2"): 1})
    resultados = rel.coletar_compares(ClienteFalso({"graphql": servidor}), "dono/repo", pares, {"v1", "v2"})
    assert list(resultados) == [("v1", "v2")]
    assert len(servidor.consultas) == 1 and "b1" not in servidor.consultas[0]


def test_tag_apagada_vira_404_sem_consultar():
    servidor = ServidorCompare({})
    [resultado] = rel.coletar_compares(
        ClienteFalso({"graphql": servidor}), "dono/repo", [par("v2", "v1")], {"v2"}
    ).values()
    assert (resultado.status, resultado.commits) == ("404", ())
    assert servidor.consultas == []


def test_ref_nula_na_resposta_vira_404():
    servidor = ServidorCompare({("v1", "v2"): 2})  # (v2, v3) ausente: ref nula
    resultados = rel.coletar_compares(
        ClienteFalso({"graphql": servidor}), "dono/repo", [par("v2", "v1"), par("v3", "v2")], {"v1", "v2", "v3"}
    )
    assert resultados[("v1", "v2")].status == "ok"
    assert resultados[("v2", "v3")].status == "404"


def test_par_com_erro_e_isolado_sem_perder_o_lote():
    servidor = ServidorCompare({("v1", "v2"): 2, ("v3", "v4"): 1}, erros={("v2", "v3"): 422})
    pares = [par("v2", "v1"), par("v3", "v2"), par("v4", "v3")]
    resultados = rel.coletar_compares(ClienteFalso({"graphql": servidor}), "dono/repo", pares,
                                      {"v1", "v2", "v3", "v4"})
    assert {k: r.status for k, r in resultados.items()} == {
        ("v1", "v2"): "ok", ("v2", "v3"): "422", ("v3", "v4"): "ok",
    }


def test_erro_temporario_propaga():
    servidor = ServidorCompare({}, erros={("v1", "v2"): 502})
    with pytest.raises(ErroAPI):
        rel.coletar_compares(ClienteFalso({"graphql": servidor}), "dono/repo", [par("v2", "v1")], {"v1", "v2"})


class ServidorCompareComTeto(ServidorCompare):
    """Como a GraphQL real: o compare para em 1.000 commits, embora aheadBy diga o total."""

    def __call__(self, v):
        resposta = super().__call__(v)
        for alias, ref in resposta["repository"].items():
            commits = ref["compare"]["commits"]
            if int(commits["pageInfo"]["endCursor"]) >= 1000:
                commits["pageInfo"]["hasNextPage"] = False
        return resposta


def commits_rest(total, head="v2"):
    paginas = []
    for inicio in range(0, total, 100):
        itens = [{"sha": f"{head}-{n}", "commit": {"message": f"fix {n}\n\ncorpo",
                                                   "author": {"date": "2025-10-01T00:00:00Z"}}}
                 for n in range(inicio, min(inicio + 100, total))]
        paginas.append(pagina({"total_commits": total, "commits": itens},
                              {"next": "x"} if inicio + 100 < total else {}))
    return paginas


def test_compare_acima_de_mil_commits_e_completado_pelo_rest():
    cliente = ClienteFalso({
        "graphql": ServidorCompareComTeto({("v1", "v2"): 1500}),
        "/repos/dono/repo/compare/v1...v2": commits_rest(1500),
    })
    [resultado] = rel.coletar_compares(cliente, "dono/repo", [par("v2", "v1")], {"v1", "v2"}).values()
    assert len(resultado.commits) == 1500 == resultado.total_commits
    assert resultado.commits[0].mensagem == "fix 0\n\ncorpo"
    assert "/repos/dono/repo/compare/v1...v2" in cliente.caminhos()


def test_compare_ate_mil_commits_nao_usa_o_rest():
    cliente = ClienteFalso({"graphql": ServidorCompareComTeto({("v1", "v2"): 1000})})
    [resultado] = rel.coletar_compares(cliente, "dono/repo", [par("v2", "v1")], {"v1", "v2"}).values()
    assert len(resultado.commits) == 1000
    assert all(c == "graphql" for c in cliente.caminhos())


def test_sem_ancestral_comum_vira_404_como_no_rest():
    # Caso real (cloudflare/terraform-provider-cloudflare, v4 x v5): a GraphQL lista 1.000
    # commits, mas o REST responde 404 "No common ancestor".
    cliente = ClienteFalso({"graphql": ServidorCompareComTeto({("v1", "v2"): 1500})})  # REST dá 404
    [resultado] = rel.coletar_compares(cliente, "dono/repo", [par("v2", "v1")], {"v1", "v2"}).values()
    assert (resultado.status, resultado.commits) == ("404", ())
