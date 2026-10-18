"""Estatística descritiva das RQ 01 a RQ 04 sobre o `metricas.csv`.

Todas as funções recebem o DataFrame de `metricas.csv` (uma linha por repositório) e devolvem
tabelas prontas para gravar; nenhuma faz I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Metrica:
    coluna: str
    rq: str
    descricao: str
    unidade: str


METRICAS = (
    Metrica("deploys_por_semana", "RQ01", "frequência de deploy", "releases/semana"),
    Metrica("lead_time_release_horas", "RQ02 (a)", "lead time por release (commit mais antigo)", "horas"),
    Metrica("lead_time_commit_horas", "RQ02 (b)", "lead time por commit", "horas"),
    Metrica("cfr_ci", "RQ03 (a)", "CFR de CI", "proporção"),
    Metrica("cfr_ci_sem_flaky", "RQ03 (a)", "CFR de CI sem falhas flaky no mesmo commit", "proporção"),
    Metrica("cfr_entrega", "RQ03 (b)", "CFR de entrega (release corretiva em até 7 dias)", "proporção"),
    Metrica("recuperacao_horas", "RQ04", "tempo de recuperação", "horas"),
)

COLUNAS_RESUMO = ["n", "ausentes", "minimo", "q1", "mediana", "q3", "iqr", "maximo", "media"]
COLUNAS_DESCRITIVA = ["rq", "metrica", "descricao", "unidade", *COLUNAS_RESUMO]


def resumo(valores: pd.Series) -> dict[str, float]:
    """n, ausentes, mínimo, quartis, IQR, máximo e média; NaN fica de fora dos cálculos."""
    validos = pd.to_numeric(valores, errors="coerce").dropna()
    q1, mediana, q3 = (validos.quantile(q) for q in (0.25, 0.5, 0.75)) if len(validos) else (float("nan"),) * 3
    return {
        "n": len(validos),
        "ausentes": len(valores) - len(validos),
        "minimo": validos.min(),
        "q1": q1,
        "mediana": mediana,
        "q3": q3,
        "iqr": q3 - q1,
        "maximo": validos.max(),
        "media": validos.mean(),
    }


def tabela_descritiva(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por métrica de `METRICAS`, com o `resumo` dos repositórios."""
    linhas = [
        {"rq": m.rq, "metrica": m.coluna, "descricao": m.descricao, "unidade": m.unidade, **resumo(df[m.coluna])}
        for m in METRICAS
    ]
    return pd.DataFrame(linhas, columns=COLUNAS_DESCRITIVA)


COLUNAS_CENSURA = [
    "rq", "metrica", "unidade", "observados", "censurados", "proporcao_censurados",
    "repositorios_com_censura", "repositorios_sem_valor",
]


def censura(df: pd.DataFrame) -> pd.DataFrame:
    """Contagem de censurados das métricas que dependem do que acontece após o fim da janela.

    RQ 04: episódios de falha sem sucesso posterior até o fim da janela.
    RQ 03 (b): releases dos últimos 7 dias, que ainda não puderam ser seguidas por uma corretiva.
    """
    casos = [
        ("RQ04", "recuperacao_horas", "episódios", "episodios_recuperados", "episodios_censurados"),
        ("RQ03 (b)", "cfr_entrega", "releases", "releases_avaliadas_cfr", "releases_censuradas_cfr"),
    ]
    linhas = []
    for rq, metrica, unidade, col_observados, col_censurados in casos:
        observados = int(df[col_observados].sum())
        censurados = int(df[col_censurados].sum())
        total = observados + censurados
        linhas.append({
            "rq": rq,
            "metrica": metrica,
            "unidade": unidade,
            "observados": observados,
            "censurados": censurados,
            "proporcao_censurados": censurados / total if total else float("nan"),
            "repositorios_com_censura": int((df[col_censurados] > 0).sum()),
            "repositorios_sem_valor": int(df[metrica].isna().sum()),
        })
    return pd.DataFrame(linhas, columns=COLUNAS_CENSURA)


COLUNAS_DIVERGENCIA_REPOS = [
    "repositorio", "lead_time_release_horas", "lead_time_commit_horas", "diferenca_horas", "razao",
    "releases_lead_time",
]
COLUNAS_DIVERGENCIA = [
    "repositorios", "mediana_a_horas", "mediana_b_horas", "commit_maior", "commit_menor", "iguais",
    "mediana_diferenca_horas", "mediana_razao", "q1_razao", "q3_razao", "spearman",
]


def divergencia_lead_time_repositorios(df: pd.DataFrame) -> pd.DataFrame:
    """Lead time (a) e (b) lado a lado: diferença (b − a) e razão (b ÷ a), por repositório."""
    pares = df.dropna(subset=["lead_time_release_horas", "lead_time_commit_horas"])
    a, b = pares["lead_time_release_horas"], pares["lead_time_commit_horas"]
    return pd.DataFrame({
        "repositorio": pares["repositorio"],
        "lead_time_release_horas": a,
        "lead_time_commit_horas": b,
        "diferenca_horas": b - a,
        "razao": (b / a).where(a > 0),
        "releases_lead_time": pares["releases_lead_time"],
    }, columns=COLUNAS_DIVERGENCIA_REPOS).reset_index(drop=True)


def divergencia_lead_time(por_repositorio: pd.DataFrame) -> pd.DataFrame:
    """Resumo da divergência entre as variantes (a) e (b) do lead time (uma linha).

    (a) é a mediana, entre as releases, da idade do commit mais antigo de cada release; (b) é a
    mediana de todos os commits juntos. Em cada release, (a) é o teto de (b), mas (b) pondera as
    releases pelo número de commits: poucas releases grandes e demoradas puxam a mediana de (b)
    para cima, acima da mediana de (a), que dá o mesmo peso a cada release.
    """
    a = por_repositorio["lead_time_release_horas"]
    b = por_repositorio["lead_time_commit_horas"]
    razao = por_repositorio["razao"].dropna()
    linha = {
        "repositorios": len(por_repositorio),
        "mediana_a_horas": a.median(),
        "mediana_b_horas": b.median(),
        "commit_maior": int((b > a).sum()),
        "commit_menor": int((b < a).sum()),
        "iguais": int((b == a).sum()),
        "mediana_diferenca_horas": por_repositorio["diferenca_horas"].median(),
        "mediana_razao": razao.median(),
        "q1_razao": razao.quantile(0.25),
        "q3_razao": razao.quantile(0.75),
        "spearman": a.corr(b, method="spearman") if len(por_repositorio) > 1 else float("nan"),
    }
    return pd.DataFrame([linha], columns=COLUNAS_DIVERGENCIA)


@dataclass(frozen=True)
class CenarioFlaky:
    nome: str
    descricao: str


CENARIOS_FLAKY = (
    CenarioFlaky("sem_flaky", "sem as falhas seguidas de sucesso no mesmo commit (cfr_ci_sem_flaky)"),
    CenarioFlaky("atual", "definição principal (cfr_ci)"),
    CenarioFlaky("com_reexecucoes",
                 "limite superior: cada run reexecutado com sucesso conta mais uma falha (a tentativa "
                 "anterior, que a API não lista)"),
)
COLUNAS_FLAKY = [
    "cenario", "descricao", "falhas", "runs_validos", "cfr_agregado", "q1", "mediana", "q3", "iqr",
    "diferenca_mediana_pp", "parcela_flaky_agregada", "parcela_flaky_mediana",
]


def _contagens_flaky(df: pd.DataFrame) -> dict[str, tuple[pd.Series, pd.Series]]:
    """(falhas, runs válidos) por repositório em cada cenário."""
    falha, sucesso = df["runs_falha"], df["runs_sucesso"]
    flaky, reexec = df["falhas_flaky_mesmo_commit"], df["runs_flaky_reexecucao"]
    return {
        "sem_flaky": (falha - flaky, falha - flaky + sucesso),
        "atual": (falha, falha + sucesso),
        "com_reexecucoes": (falha + reexec, falha + sucesso + reexec),
    }


def impacto_flaky(df: pd.DataFrame) -> pd.DataFrame:
    """CFR de CI em três cenários de flakiness e quanto da taxa vem de falhas intermitentes.

    `parcela_flaky_*` = (CFR do cenário − CFR sem flaky) ÷ CFR do cenário: a fração da taxa
    explicada por flakiness. A agregada usa a soma dos runs de todos os repositórios; a mediana
    é entre os repositórios com CFR > 0 no cenário.
    """
    contagens = _contagens_flaky(df)
    falhas_base, validos_base = contagens["sem_flaky"]
    cfr_base = (falhas_base / validos_base).where(validos_base > 0)
    agregado_base = falhas_base.sum() / validos_base.sum()

    mediana_atual = None
    linhas = []
    for cenario in CENARIOS_FLAKY:
        falhas, validos = contagens[cenario.nome]
        cfr = (falhas / validos).where(validos > 0)
        estat = resumo(cfr)
        if cenario.nome == "atual":
            mediana_atual = estat["mediana"]
        agregado = falhas.sum() / validos.sum()
        parcela = ((cfr - cfr_base) / cfr).where(cfr > 0)
        linhas.append({
            "cenario": cenario.nome,
            "descricao": cenario.descricao,
            "falhas": int(falhas.sum()),
            "runs_validos": int(validos.sum()),
            "cfr_agregado": agregado,
            **{k: estat[k] for k in ("q1", "mediana", "q3", "iqr")},
            "diferenca_mediana_pp": None,
            "parcela_flaky_agregada": (agregado - agregado_base) / agregado if agregado else float("nan"),
            "parcela_flaky_mediana": parcela.median(),
        })
    for linha in linhas:
        linha["diferenca_mediana_pp"] = (linha["mediana"] - mediana_atual) * 100
    return pd.DataFrame(linhas, columns=COLUNAS_FLAKY)
