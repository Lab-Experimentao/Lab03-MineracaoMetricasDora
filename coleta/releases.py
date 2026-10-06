"""Coleta de releases, tags e commits entre releases consecutivas (compare).

Há três cadeias de "deploys", uma para cada definição usada na RQ 07:
releases (definição principal), releases + pré-releases e tags.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from coleta.cliente import ErroAPI
from coleta.modelos import CommitInfo, Release, Tag, ler_data
from pipeline.config import Janela

log = logging.getLogger(__name__)

CADEIA_RELEASE = "release"
CADEIA_RELEASE_PRERELEASE = "release_prerelease"
CADEIA_TAG = "tag"

COMPARE_OK = "ok"
COMPARE_PRIMEIRA = "primeira"  # primeira da história: não há base para comparar


def listar_releases(cliente, repo: str) -> list[Release]:
    return [Release.da_api(item) for item in cliente.paginar(f"/repos/{repo}/releases", {"per_page": 100})]


def releases_publicadas(releases: Iterable[Release], incluir_prerelease: bool) -> list[Release]:
    """Releases que contam como deploy: draft = false (seção 3); pré-releases só na variante."""
    return [
        r for r in releases
        if not r.draft and r.publicada_em is not None and (incluir_prerelease or not r.prerelease)
    ]


def contar_releases_janela(releases: Iterable[Release], janela: Janela) -> int:
    """Releases da definição principal publicadas dentro da janela (critério de inclusão)."""
    return sum(1 for r in releases_publicadas(releases, False) if janela.contem(r.publicada_em))


# No REST, /tags não traz data e cada tag custaria uma chamada a mais; pela GraphQL
# vêm 100 tags por consulta já com as datas do commit. Tags anotadas apontam para um
# objeto Tag, que por sua vez aponta para o commit.
CONSULTA_TAGS = """
query($dono: String!, $nome: String!, $cursor: String) {
  repository(owner: $dono, name: $nome) {
    refs(refPrefix: "refs/tags/", first: 100, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        target {
          ... on Commit { oid author { date } committer { date } }
          ... on Tag { target { ... on Commit { oid author { date } committer { date } } } }
        }
      }
    }
  }
}
"""


def _tag_do_no(no: dict) -> Tag:
    alvo = no.get("target") or {}
    commit = alvo if "oid" in alvo else (alvo.get("target") or {})
    return Tag(
        nome=no["name"],
        sha=commit.get("oid", ""),  # vazio se a tag não aponta para um commit
        data_autor=ler_data((commit.get("author") or {}).get("date")),
        data_committer=ler_data((commit.get("committer") or {}).get("date")),
    )


def listar_tags(cliente, repo: str) -> list[Tag]:
    """Tags com as datas do commit apontado, 100 por consulta GraphQL."""
    dono, nome = repo.split("/", 1)
    tags = []
    cursor = None
    while True:
        dados = cliente.graphql(CONSULTA_TAGS, {"dono": dono, "nome": nome, "cursor": cursor})
        refs = ((dados or {}).get("repository") or {}).get("refs") or {}
        tags.extend(_tag_do_no(no) for no in refs.get("nodes") or [])
        pagina = refs.get("pageInfo") or {}
        if not pagina.get("hasNextPage"):
            return tags
        cursor = pagina["endCursor"]


@dataclass(frozen=True)
class Par:
    """Item da cadeia publicado na janela e o item imediatamente anterior a ele."""

    cadeia: str
    tag: str
    publicada_em: datetime
    tag_anterior: str | None


def montar_pares(cadeia: str, itens: Iterable[tuple[str, datetime]], janela: Janela) -> list[Par]:
    """Ordena a cadeia por data e pareia cada item da janela com o anterior.

    O anterior pode estar fora da janela; o primeiro item da história fica sem anterior.
    """
    ordenados = sorted(itens, key=lambda item: (item[1], item[0]))
    pares = []
    for indice, (tag, data) in enumerate(ordenados):
        if janela.contem(data):
            anterior = ordenados[indice - 1][0] if indice > 0 else None
            pares.append(Par(cadeia, tag, data, anterior))
    return pares


def pares_do_repositorio(releases: list[Release], tags: list[Tag], janela: Janela) -> list[Par]:
    return [
        *montar_pares(
            CADEIA_RELEASE,
            ((r.tag, r.publicada_em) for r in releases_publicadas(releases, False)),
            janela,
        ),
        *montar_pares(
            CADEIA_RELEASE_PRERELEASE,
            ((r.tag, r.publicada_em) for r in releases_publicadas(releases, True)),
            janela,
        ),
        *montar_pares(
            CADEIA_TAG,
            ((t.nome, t.data_autor) for t in tags if t.data_autor is not None),
            janela,
        ),
    ]


@dataclass(frozen=True)
class ResultadoCompare:
    """`status` é ok ou o HTTP equivalente do erro (404: tag inexistente); `divergencia`
    (ahead/behind/diverged/identical) e `total_commits` (aheadBy) vêm do GitHub e
    permitem conferir se a paginação trouxe tudo."""

    tag_anterior: str
    tag: str
    status: str
    commits: tuple[CommitInfo, ...]
    divergencia: str | None = None
    total_commits: int | None = None


# Compares por consulta GraphQL. Cada compare traz até 100 commits com a mensagem
# completa; lotes maiores arriscam o tempo limite do servidor em compares grandes.
LOTE_COMPARES = 5


def consulta_compares(quantidade: int) -> str:
    """Consulta com um alias (p0, p1, ...) por compare, cada um com base, head e cursor."""
    variaveis = "".join(f", $b{i}: String!, $h{i}: String!, $c{i}: String" for i in range(quantidade))
    blocos = "".join(
        f"""
    p{i}: ref(qualifiedName: $b{i}) {{
      compare(headRef: $h{i}) {{
        status aheadBy
        commits(first: 100, after: $c{i}) {{
          pageInfo {{ hasNextPage endCursor }}
          nodes {{ oid authoredDate message }}
        }}
      }}
    }}"""
        for i in range(quantidade)
    )
    return f"query($dono: String!, $nome: String!{variaveis}) {{\n  repository(owner: $dono, name: $nome) {{{blocos}\n  }}\n}}"


@dataclass
class _CompareEmAndamento:
    base: str
    head: str
    cursor: str | None = None
    divergencia: str | None = None
    total: int | None = None
    commits: list[CommitInfo] = field(default_factory=list)


def _executar_lote(cliente, repo: str, lote: list[_CompareEmAndamento]) -> list[dict | None]:
    """Devolve o objeto `compare` de cada item (None se a ref não existe)."""
    dono, nome = repo.split("/", 1)
    variaveis: dict[str, str | None] = {"dono": dono, "nome": nome}
    for i, item in enumerate(lote):
        variaveis |= {f"b{i}": f"refs/tags/{item.base}", f"h{i}": f"refs/tags/{item.head}", f"c{i}": item.cursor}
    repositorio = (cliente.graphql(consulta_compares(len(lote)), variaveis) or {}).get("repository") or {}
    return [(repositorio.get(f"p{i}") or {}).get("compare") for i in range(len(lote))]


def coletar_compares(
    cliente, repo: str, pares: Iterable[Par], tags_existentes: set[str]
) -> dict[tuple[str, str], ResultadoCompare]:
    """Commits de cada par (anterior, tag) distinto, em lotes pela GraphQL.

    Pares repetidos entre cadeias são feitos uma vez. Tag ausente do repositório
    (apagada ou renomeada) vira status 404, como o compare do REST responderia.
    """
    resultados: dict[tuple[str, str], ResultadoCompare] = {}
    fila: list[_CompareEmAndamento] = []
    for par in pares:
        chave = (par.tag_anterior, par.tag)
        if par.tag_anterior is None or chave in resultados or any(c.base == chave[0] and c.head == chave[1] for c in fila):
            continue
        if par.tag_anterior not in tags_existentes or par.tag not in tags_existentes:
            log.info("%s: compare %s...%s sem a tag no repositório (404)", repo, *chave)
            resultados[chave] = ResultadoCompare(par.tag_anterior, par.tag, "404", ())
            continue
        fila.append(_CompareEmAndamento(par.tag_anterior, par.tag))

    while fila:
        lote, fila = fila[:LOTE_COMPARES], fila[LOTE_COMPARES:]
        try:
            fila += _avancar(cliente, repo, lote, resultados)
        except ErroAPI as erro:
            if erro.status is None or erro.status >= 500:
                raise
            # Um par com problema derruba o lote inteiro: refaz cada par sozinho para isolá-lo.
            for item in lote:
                _comparar_sozinho(cliente, repo, item, resultados)
    return resultados


def _avancar(
    cliente, repo: str, lote: list[_CompareEmAndamento], resultados: dict
) -> list[_CompareEmAndamento]:
    """Busca uma página de cada compare do lote; devolve os que ainda têm páginas."""
    pendentes = []
    for item, comparacao in zip(lote, _executar_lote(cliente, repo, lote)):
        if comparacao is None:
            resultados[(item.base, item.head)] = ResultadoCompare(item.base, item.head, "404", ())
            continue
        if item.cursor is None:
            item.divergencia = (comparacao.get("status") or "").lower() or None
            item.total = comparacao.get("aheadBy")
        pagina = comparacao["commits"]
        item.commits.extend(CommitInfo.da_graphql(no) for no in pagina["nodes"])
        if pagina["pageInfo"]["hasNextPage"]:
            item.cursor = pagina["pageInfo"]["endCursor"]
            pendentes.append(item)
            continue
        if item.total is not None and item.total != len(item.commits):
            log.warning("%s: compare %s...%s trouxe %d de %d commits",
                        repo, item.base, item.head, len(item.commits), item.total)
        resultados[(item.base, item.head)] = ResultadoCompare(
            item.base, item.head, COMPARE_OK, tuple(item.commits), item.divergencia, item.total
        )
    return pendentes


def _comparar_sozinho(cliente, repo: str, item: _CompareEmAndamento, resultados: dict) -> None:
    """Recomeça o compare do zero, sozinho; um erro definitivo vira o status do par."""
    item = _CompareEmAndamento(item.base, item.head)
    pendentes = [item]
    try:
        while pendentes:
            pendentes = _avancar(cliente, repo, pendentes, resultados)
    except ErroAPI as erro:
        if erro.status is None or erro.status >= 500:
            raise
        log.info("%s: compare %s...%s falhou com HTTP %s", repo, item.base, item.head, erro.status)
        resultados[(item.base, item.head)] = ResultadoCompare(item.base, item.head, str(erro.status), ())
