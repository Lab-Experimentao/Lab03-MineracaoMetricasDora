"""Validação da heurística de release corretiva contra o consenso da amostra-ouro (seção 6, item 5).

Cada versão registrada em `metricas.corretiva.VERSOES` é avaliada nas releases rotuladas,
com precisão, recall e F1 (`precision_recall_fscore_support`, classe positiva = corretiva).
Os erros (falsos positivos e falsos negativos) de cada versão são listados com o motivo da
decisão da heurística, para orientar o refinamento.
"""

from __future__ import annotations

import pandas as pd
from sklearn.metrics import precision_recall_fscore_support

from metricas.corretiva import VERSOES, ReleaseAvaliada, eh_titulo_de_correcao, eh_versao_de_patch, muda_so_patch

F1_MINIMO = 0.70

COLUNAS_VERSOES = [
    "versao", "descricao", "releases", "corretivas_consenso", "corretivas_heuristica",
    "verdadeiros_positivos", "falsos_positivos", "falsos_negativos", "precisao", "recall", "f1",
]
COLUNAS_ERROS = [
    "versao", "tipo_erro", "repositorio", "tag", "tag_anterior", "muda_so_patch", "versao_de_patch",
    "commits", "commits_correcao", "titulos_correcao",
]


def releases_rotuladas(consenso: pd.DataFrame, commits: pd.DataFrame) -> list[ReleaseAvaliada]:
    """Releases do consenso com os títulos dos commits do compare com a anterior.

    `commits` precisa das colunas repositorio, tag_anterior, tag e titulo.
    """
    titulos = commits.groupby(["repositorio", "tag_anterior", "tag"], sort=False)["titulo"].agg(tuple)
    return [
        ReleaseAvaliada(
            tag=r.tag,
            publicada_em=pd.Timestamp(r.publicada_em).to_pydatetime(),
            tag_anterior=r.tag_anterior or None,
            titulos_commits=titulos.get((r.repositorio, r.tag_anterior, r.tag), ()),
        )
        for r in consenso.itertuples()
    ]


def _erro(versao: str, tipo: str, repositorio: str, release: ReleaseAvaliada) -> dict:
    correcao = [t for t in release.titulos_commits if eh_titulo_de_correcao(t)]
    return {
        "versao": versao, "tipo_erro": tipo, "repositorio": repositorio, "tag": release.tag,
        "tag_anterior": release.tag_anterior or "", "muda_so_patch": muda_so_patch(release.tag, release.tag_anterior),
        "versao_de_patch": eh_versao_de_patch(release.tag),
        "commits": len(release.titulos_commits), "commits_correcao": len(correcao),
        "titulos_correcao": " | ".join(correcao[:5]),
    }


def avaliar_versoes(consenso: pd.DataFrame, commits: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Métricas de cada versão da heurística e a lista dos erros de cada uma."""
    releases = releases_rotuladas(consenso, commits)
    esperado = [rotulo == "sim" for rotulo in consenso["corretiva"]]
    resumo, erros = [], []
    for versao in VERSOES:
        previsto = [versao.funcao(r) for r in releases]
        precisao, recall, f1, _ = precision_recall_fscore_support(
            esperado, previsto, average="binary", pos_label=True, zero_division=0
        )
        vp = sum(e and p for e, p in zip(esperado, previsto))
        resumo.append({
            "versao": versao.nome, "descricao": versao.descricao, "releases": len(releases),
            "corretivas_consenso": sum(esperado), "corretivas_heuristica": sum(previsto),
            "verdadeiros_positivos": vp, "falsos_positivos": sum(previsto) - vp,
            "falsos_negativos": sum(esperado) - vp,
            "precisao": round(precisao, 4), "recall": round(recall, 4), "f1": round(f1, 4),
        })
        for repo, release, e, p in zip(consenso["repositorio"], releases, esperado, previsto):
            if e != p:
                erros.append(_erro(versao.nome, "falso positivo" if p else "falso negativo", repo, release))
    return pd.DataFrame(resumo, columns=COLUNAS_VERSOES), pd.DataFrame(erros, columns=COLUNAS_ERROS)
