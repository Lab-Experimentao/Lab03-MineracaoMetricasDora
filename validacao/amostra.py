"""Sorteio da amostra-ouro (seção 6): repositórios da amostra final e releases de cada um.

O sorteio usa `DataFrame.sample(random_state=semente)`, como sugere a especificação. As
linhas são ordenadas antes, para que o resultado não dependa da ordem dos CSVs.
"""

from __future__ import annotations

from urllib.parse import quote

import pandas as pd

CADEIA_PRINCIPAL = "release"

COLUNAS_AMOSTRA = ["repositorio", "tag", "tag_anterior", "publicada_em", "url_release", "url_commits"]

# Limites do texto copiado para a planilha; o resto continua acessível pelos links.
MAX_CARACTERES_NOTAS = 1000
MAX_TITULOS_COMMITS = 20


def url_release(repo: str, tag: str) -> str:
    return f"https://github.com/{repo}/releases/tag/{quote(tag, safe='')}"


def url_commits(repo: str, anterior: str, tag: str) -> str:
    """Página de compare do GitHub com os commits da release; vazio se não há anterior."""
    if not anterior:
        return ""
    return f"https://github.com/{repo}/compare/{quote(anterior, safe='')}...{quote(tag, safe='')}"


def sortear_repositorios(metricas: pd.DataFrame, n: int, semente: int) -> list[str]:
    """`n` repositórios da amostra final, em ordem alfabética."""
    base = metricas[["repositorio"]].drop_duplicates().sort_values("repositorio", ignore_index=True)
    if n > len(base):
        raise ValueError(f"amostra-ouro de {n} repositórios, mas a amostra final tem {len(base)}")
    return sorted(base.sample(n=n, random_state=semente)["repositorio"])


def releases_elegiveis(compares: pd.DataFrame) -> pd.DataFrame:
    """Releases da definição principal publicadas na janela, uma linha por tag.

    Duas releases do GitHub com a mesma tag aparecem duas vezes na cadeia, e a segunda
    fica pareada consigo mesma; fica a linha cuja anterior é outra tag.
    """
    cadeia = compares[compares["cadeia"] == CADEIA_PRINCIPAL].copy()
    cadeia["_mesma_tag"] = cadeia["tag_anterior"] == cadeia["tag"]
    cadeia = cadeia.sort_values(["repositorio", "publicada_em", "tag", "_mesma_tag"], ignore_index=True)
    return cadeia.drop_duplicates(["repositorio", "tag"]).drop(columns="_mesma_tag").reset_index(drop=True)


def sortear_releases(
    compares: pd.DataFrame, releases: pd.DataFrame, repositorios: list[str], k: int, semente: int
) -> pd.DataFrame:
    """`k` releases de cada repositório, com o link da release e o dos commits incluídos."""
    elegiveis = releases_elegiveis(compares)
    links = (
        releases[releases["draft"] != "1"]
        .drop_duplicates(["repositorio", "tag", "publicada_em"])
        .set_index(["repositorio", "tag", "publicada_em"])["url"]
    )
    linhas = []
    for repo in repositorios:
        do_repo = elegiveis[elegiveis["repositorio"] == repo]
        if len(do_repo) < k:
            raise ValueError(f"{repo} tem {len(do_repo)} releases na janela; são necessárias {k}")
        sorteadas = do_repo.sample(n=k, random_state=semente).sort_values(["publicada_em", "tag"])
        for _, r in sorteadas.iterrows():
            linhas.append({
                "repositorio": repo,
                "tag": r["tag"],
                "tag_anterior": r["tag_anterior"],
                "publicada_em": r["publicada_em"],
                "url_release": links.get((repo, r["tag"], r["publicada_em"])) or url_release(repo, r["tag"]),
                "url_commits": url_commits(repo, r["tag_anterior"], r["tag"]),
            })
    return pd.DataFrame(linhas, columns=COLUNAS_AMOSTRA)


def resumir_notas(texto: str, limite: int = MAX_CARACTERES_NOTAS) -> str:
    texto = (texto or "").strip()
    if not texto:
        return "(release sem notas)"
    if len(texto) <= limite:
        return texto
    return texto[:limite].rstrip() + f"\n[... +{len(texto) - limite} caracteres; veja url_release]"


def resumir_titulos(titulos: list[str], limite: int = MAX_TITULOS_COMMITS) -> str:
    if not titulos:
        return "(nenhum commit novo em relação à anterior)"
    linhas = [f"- {t}" for t in titulos[:limite]]
    if len(titulos) > limite:
        linhas.append(f"[... +{len(titulos) - limite} commits; veja url_commits]")
    return "\n".join(linhas)


def _titulos_da_release(r, status: str, titulos: pd.Series) -> str:
    if not r.tag_anterior:
        return "(primeira release do repositório: sem anterior para comparar)"
    if status != "ok":
        return f"(lista de commits indisponível: o compare retornou {status or 'erro'}; veja url_commits)"
    return resumir_titulos(titulos.get((r.repositorio, r.tag_anterior, r.tag), []))


def com_textos(
    amostra: pd.DataFrame, compares: pd.DataFrame, releases: pd.DataFrame, commits: pd.DataFrame
) -> pd.DataFrame:
    """Acrescenta as release notes e os títulos dos commits, para ler sem abrir os links.

    São os dados brutos que o avaliador veria nas páginas; nenhuma saída da heurística.
    `commits` só precisa das colunas repositorio, tag_anterior, tag e titulo.
    """
    status = (
        compares[compares["cadeia"] == CADEIA_PRINCIPAL]
        .drop_duplicates(["repositorio", "tag_anterior", "tag"])
        .set_index(["repositorio", "tag_anterior", "tag"])["status"]
    )
    notas = (
        releases[releases["draft"] != "1"]
        .drop_duplicates(["repositorio", "tag", "publicada_em"])
        .set_index(["repositorio", "tag", "publicada_em"])["notas"]
    )
    titulos = commits.groupby(["repositorio", "tag_anterior", "tag"], sort=False)["titulo"].agg(list)
    resultado = amostra.copy()
    resultado["notas_release"] = [
        resumir_notas(notas.get((r.repositorio, r.tag, r.publicada_em), "")) for r in amostra.itertuples()
    ]
    resultado["titulos_commits"] = [
        _titulos_da_release(r, status.get((r.repositorio, r.tag_anterior, r.tag), ""), titulos)
        for r in amostra.itertuples()
    ]
    return resultado
