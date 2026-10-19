"""RQ 07: quanto a classificação DORA muda entre combinações de definições operacionais.

Lê o `metricas_combinacoes.csv` (uma linha por repositório e combinação). Para cada par de
combinações: % de repositórios que mudam de classe e kappa de Cohen ponderado (linear), na classe
geral e em cada dimensão que muda entre as combinações. Nenhuma função faz I/O.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score

from analise.classificacao import CLASSES, SEM_DADOS
from validacao.concordancia import interpretar

ORDEM = list(reversed(CLASSES))  # Low, Medium, High, Elite: a ordem que o kappa ponderado usa
NOTA = {classe: i for i, classe in enumerate(ORDEM)}
DIMENSOES = (
    ("geral", "classe_geral"),
    ("frequencia", "classe_frequencia"),
    ("lead_time", "classe_lead_time"),
    ("cfr", "classe_cfr"),
)


def combinacoes(df: pd.DataFrame) -> list[str]:
    return list(dict.fromkeys(df["combinacao"]))


def _classes(df: pd.DataFrame, coluna: str) -> pd.DataFrame:
    """Classe de cada repositório (linhas) em cada combinação (colunas)."""
    return df.pivot(index="repositorio", columns="combinacao", values=coluna)[combinacoes(df)]


COLUNAS_DISTRIBUICAO = ["combinacao", "unidade_deploy", "lead_time_variante", "cfr_variante", *CLASSES, "sem_dados"]


def distribuicao(df: pd.DataFrame) -> pd.DataFrame:
    """Repositórios por classe geral em cada combinação."""
    linhas = []
    for nome, grupo in df.groupby("combinacao", sort=False):
        contagem = grupo["classe_geral"].fillna(SEM_DADOS).value_counts()
        primeira = grupo.iloc[0]
        linhas.append({
            "combinacao": nome,
            "unidade_deploy": primeira["unidade_deploy"],
            "lead_time_variante": primeira["lead_time_variante"],
            "cfr_variante": primeira["cfr_variante"],
            **{classe: int(contagem.get(classe, 0)) for classe in CLASSES},
            "sem_dados": int(contagem.get(SEM_DADOS, 0)),
        })
    return pd.DataFrame(linhas, columns=COLUNAS_DISTRIBUICAO)


def kappa_linear(a: pd.Series, b: pd.Series) -> float:
    """Kappa de Cohen com pesos lineares sobre as classes ordenadas de Low a Elite."""
    if len(a) == 0:
        return float("nan")
    if (a == b).all():
        return 1.0
    return float(cohen_kappa_score(a, b, labels=ORDEM, weights="linear"))


COLUNAS_PARES = [
    "par", "combinacao_a", "combinacao_b", "dimensao", "repositorios", "sem_classe", "mudam",
    "proporcao_mudam", "sobem", "descem", "mudam_duas_ou_mais", "kappa_linear", "interpretacao",
]


def concordancia_pares(df: pd.DataFrame) -> pd.DataFrame:
    """Mudança de classe e kappa ponderado para cada par de combinações e cada dimensão.

    Só entram os repositórios com classe nas duas combinações (`sem_classe` conta os demais).
    `sobem`/`descem`: classe melhor/pior em `combinacao_b` do que em `combinacao_a`.
    """
    linhas = []
    for dimensao, coluna in DIMENSOES:
        classes = _classes(df, coluna)
        for a, b in combinations(classes.columns, 2):
            pares = classes[[a, b]].dropna()
            diferenca = pares[b].map(NOTA) - pares[a].map(NOTA)
            kappa = kappa_linear(pares[a], pares[b])
            linhas.append({
                "par": f"{a}x{b}",
                "combinacao_a": a,
                "combinacao_b": b,
                "dimensao": dimensao,
                "repositorios": len(pares),
                "sem_classe": len(classes) - len(pares),
                "mudam": int((diferenca != 0).sum()),
                "proporcao_mudam": float((diferenca != 0).mean()) if len(pares) else float("nan"),
                "sobem": int((diferenca > 0).sum()),
                "descem": int((diferenca < 0).sum()),
                "mudam_duas_ou_mais": int((diferenca.abs() >= 2).sum()),
                "kappa_linear": kappa,
                "interpretacao": interpretar(kappa),
            })
    return pd.DataFrame(linhas, columns=COLUNAS_PARES)


COLUNAS_TRANSICOES = ["par", "classe_a", *(f"para_{c}" for c in CLASSES), "repositorios"]


def transicoes(df: pd.DataFrame) -> pd.DataFrame:
    """Matriz de transição da classe geral (linhas: classe em A; colunas: classe em B) por par."""
    classes = _classes(df, "classe_geral")
    blocos = []
    for a, b in combinations(classes.columns, 2):
        pares = classes[[a, b]].dropna()
        tabela = (
            pd.crosstab(pd.Categorical(pares[a], CLASSES), pd.Categorical(pares[b], CLASSES), dropna=False)
            .reindex(index=CLASSES, columns=CLASSES, fill_value=0)
        )
        tabela.columns = [f"para_{c}" for c in CLASSES]
        tabela["repositorios"] = tabela.sum(axis=1)
        tabela.insert(0, "classe_a", CLASSES)
        tabela.insert(0, "par", f"{a}x{b}")
        blocos.append(tabela.reset_index(drop=True))
    if not blocos:
        return pd.DataFrame(columns=COLUNAS_TRANSICOES)
    return pd.concat(blocos, ignore_index=True)[COLUNAS_TRANSICOES].astype({c: np.int64 for c in COLUNAS_TRANSICOES[2:]})
