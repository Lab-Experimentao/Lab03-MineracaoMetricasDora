"""RQ 06: características dos repositórios associadas a melhor desempenho DORA.

Cada fator divide os repositórios em grupos (quartis, quando numérico). Para cada fator e
métrica: Kruskal-Wallis (Mann-Whitney com 2 grupos), p-valores corrigidos por Holm sobre todos
os testes, ε² e Cliff's delta entre grupos. Só `graficos_fatores` faz I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal, mannwhitneyu
from statsmodels.stats.multitest import multipletests

ALFA = 0.05
N_LINGUAGENS = 5
OUTRAS = "outras"
QUARTIS = ["Q1", "Q2", "Q3", "Q4"]


@dataclass(frozen=True)
class MetricaDora:
    coluna: str
    descricao: str
    maior_melhor: bool
    escala_log: bool


METRICAS = (
    MetricaDora("deploys_por_semana", "deploys por semana", True, True),
    MetricaDora("lead_time_release_horas", "lead time (a), horas", False, True),
    MetricaDora("cfr_ci", "CFR de CI", False, False),
    MetricaDora("recuperacao_horas", "tempo de recuperação, horas", False, True),
)


@dataclass(frozen=True)
class Fator:
    nome: str
    descricao: str
    quartis: bool


FATORES = (
    Fator("linguagem", f"linguagem principal ({N_LINGUAGENS} mais frequentes + {OUTRAS})", False),
    Fator("estrelas", "estrelas (quartis)", True),
    Fator("contribuidores", "contribuidores (quartis)", True),
    Fator("idade", "idade em anos no fim da janela (quartis)", True),
    Fator("tipo_projeto", "tipo de projeto (classificação automática)", False),
)


def _quartis(valores: pd.Series) -> pd.Series:
    return pd.qcut(valores, 4, labels=QUARTIS).astype(object)


def grupos_fatores(df: pd.DataFrame, tipos: pd.DataFrame, fim_janela: datetime) -> pd.DataFrame:
    """Grupo de cada repositório em cada fator (uma coluna por fator)."""
    linguagem = df["linguagem"].fillna(OUTRAS)
    principais = linguagem.value_counts().index[:N_LINGUAGENS]
    criado = pd.to_datetime(df["criado_em"], utc=True)
    idade = (pd.Timestamp(fim_janela) - criado).dt.days / 365.25
    tipo = df["repositorio"].map(tipos.set_index("repositorio")["tipo_projeto"])
    return pd.DataFrame({
        "linguagem": linguagem.where(linguagem.isin(principais), OUTRAS),
        "estrelas": _quartis(df["estrelas"]),
        "contribuidores": _quartis(df["contribuidores"]),
        "idade": _quartis(idade),
        "tipo_projeto": tipo,
    }, index=df.index)


def ordem_grupos(fator: Fator, grupos: pd.Series) -> list[str]:
    if fator.quartis:
        return [q for q in QUARTIS if q in set(grupos)]
    contagem = grupos.value_counts()
    return [g for g in contagem.index if g != OUTRAS] + ([OUTRAS] if OUTRAS in contagem.index else [])


def _amostras(df: pd.DataFrame, grupos: pd.Series, coluna: str, ordem: list[str]) -> dict[str, np.ndarray]:
    valores = pd.to_numeric(df[coluna], errors="coerce")
    amostras = {g: valores[(grupos == g) & valores.notna()].to_numpy() for g in ordem}
    return {g: v for g, v in amostras.items() if len(v)}


def cliff_delta(a: np.ndarray, b: np.ndarray) -> float:
    """P(a > b) − P(a < b), comparando todos os pares."""
    if not len(a) or not len(b):
        return float("nan")
    sinais = np.sign(np.subtract.outer(a, b))
    return float(sinais.sum() / sinais.size)


def magnitude_cliff(delta: float) -> str:
    """Limiares de Romano et al. (2006)."""
    d = abs(delta)
    if np.isnan(d):
        return ""
    if d < 0.147:
        return "desprezível"
    if d < 0.33:
        return "pequeno"
    if d < 0.474:
        return "médio"
    return "grande"


def magnitude_epsilon2(e2: float) -> str:
    """Limiares de Tomczak e Tomczak (2014) / Rea e Parker."""
    if np.isnan(e2):
        return ""
    if e2 < 0.01:
        return "desprezível"
    if e2 < 0.08:
        return "pequeno"
    if e2 < 0.26:
        return "médio"
    return "grande"


COLUNAS_TESTES = [
    "fator", "metrica", "teste", "grupos", "n", "estatistica", "p_valor", "p_holm", "significativo",
    "epsilon2", "efeito",
]


def comparar_grupos(df: pd.DataFrame, grupos: pd.DataFrame) -> pd.DataFrame:
    """Um teste por fator e métrica, com p-valor corrigido por Holm sobre todos eles.

    ε² = H ÷ (n − 1) (Tomczak e Tomczak, 2014). Com 2 grupos, o teste é Mann-Whitney e o ε²
    fica vazio: o efeito vai pelo Cliff's delta.
    """
    linhas = []
    for fator in FATORES:
        ordem = ordem_grupos(fator, grupos[fator.nome].dropna())
        for metrica in METRICAS:
            amostras = _amostras(df, grupos[fator.nome], metrica.coluna, ordem)
            n = sum(len(v) for v in amostras.values())
            linha = {"fator": fator.nome, "metrica": metrica.coluna, "grupos": len(amostras), "n": n,
                     "teste": "", "estatistica": float("nan"), "p_valor": float("nan"),
                     "epsilon2": float("nan")}
            if len(amostras) == 2:
                a, b = amostras.values()
                resultado = mannwhitneyu(a, b, alternative="two-sided")
                linha.update(teste="mann-whitney", estatistica=resultado.statistic, p_valor=resultado.pvalue)
            elif len(amostras) > 2:
                h, p = kruskal(*amostras.values())
                linha.update(teste="kruskal-wallis", estatistica=h, p_valor=p, epsilon2=h / (n - 1))
            linhas.append(linha)
    tabela = pd.DataFrame(linhas)
    validos = tabela["p_valor"].notna()
    tabela["p_holm"] = float("nan")
    if validos.any():
        tabela.loc[validos, "p_holm"] = multipletests(tabela.loc[validos, "p_valor"], method="holm")[1]
    tabela["significativo"] = tabela["p_holm"] < ALFA
    tabela["efeito"] = tabela["epsilon2"].map(magnitude_epsilon2)
    return tabela[COLUNAS_TESTES]


COLUNAS_GRUPOS = ["fator", "grupo", "metrica", "n", "q1", "mediana", "q3"]


def resumo_grupos(df: pd.DataFrame, grupos: pd.DataFrame) -> pd.DataFrame:
    """Mediana e quartis de cada métrica em cada grupo de cada fator."""
    linhas = []
    for fator in FATORES:
        ordem = ordem_grupos(fator, grupos[fator.nome].dropna())
        for metrica in METRICAS:
            for grupo, valores in _amostras(df, grupos[fator.nome], metrica.coluna, ordem).items():
                q1, mediana, q3 = np.quantile(valores, [0.25, 0.5, 0.75])
                linhas.append({"fator": fator.nome, "grupo": grupo, "metrica": metrica.coluna,
                               "n": len(valores), "q1": q1, "mediana": mediana, "q3": q3})
    return pd.DataFrame(linhas, columns=COLUNAS_GRUPOS)


COLUNAS_CLIFF = [
    "fator", "metrica", "grupo_a", "grupo_b", "n_a", "n_b", "cliff_delta", "magnitude", "grupo_melhor",
]


def pares_cliff(fator: Fator, ordem: list[str]) -> list[tuple[str, str]]:
    """Q4 x Q1 nos fatores em quartis; todos os pares nos demais."""
    if fator.quartis:
        return [(ordem[-1], ordem[0])] if len(ordem) > 1 else []
    return list(combinations(ordem, 2))


def tabela_cliff(df: pd.DataFrame, grupos: pd.DataFrame) -> pd.DataFrame:
    """Cliff's delta (grupo_a x grupo_b) e qual dos dois tem o melhor desempenho na métrica.

    `grupo_melhor` fica vazio quando o efeito é desprezível.
    """
    linhas = []
    for fator in FATORES:
        ordem = ordem_grupos(fator, grupos[fator.nome].dropna())
        for metrica in METRICAS:
            amostras = _amostras(df, grupos[fator.nome], metrica.coluna, ordem)
            for a, b in pares_cliff(fator, [g for g in ordem if g in amostras]):
                delta = cliff_delta(amostras[a], amostras[b])
                magnitude = magnitude_cliff(delta)
                a_melhor = delta > 0 if metrica.maior_melhor else delta < 0
                linhas.append({
                    "fator": fator.nome, "metrica": metrica.coluna, "grupo_a": a, "grupo_b": b,
                    "n_a": len(amostras[a]), "n_b": len(amostras[b]), "cliff_delta": delta,
                    "magnitude": magnitude,
                    "grupo_melhor": "" if magnitude in ("", "desprezível") else (a if a_melhor else b),
                })
    return pd.DataFrame(linhas, columns=COLUNAS_CLIFF)


def graficos_fatores(df: pd.DataFrame, grupos: pd.DataFrame, resultado: pd.DataFrame, destino: Path) -> list[Path]:
    """Um boxplot por fator com algum teste significativo (um painel por métrica)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    gravados = []
    significativos = resultado[resultado["significativo"]]
    for fator in FATORES:
        if fator.nome not in set(significativos["fator"]):
            continue
        ordem = ordem_grupos(fator, grupos[fator.nome].dropna())
        fig, eixos = plt.subplots(1, len(METRICAS), figsize=(4 * len(METRICAS), 4.2), constrained_layout=True)
        for eixo, metrica in zip(eixos, METRICAS):
            amostras = _amostras(df, grupos[fator.nome], metrica.coluna, ordem)
            eixo.boxplot(list(amostras.values()), showfliers=True, flierprops={"markersize": 3})
            eixo.set_xticks(range(1, len(amostras) + 1), list(amostras), rotation=30, ha="right", fontsize=8)
            if metrica.escala_log:
                eixo.set_yscale("log")
            teste = resultado[(resultado["fator"] == fator.nome) & (resultado["metrica"] == metrica.coluna)].iloc[0]
            p = "p < 0,001" if teste.p_holm < 0.001 else f"p = {teste.p_holm:.3f}".replace(".", ",")
            e2 = f"{teste.epsilon2:.3f}".replace(".", ",")
            eixo.set_title(f"{metrica.descricao}\n{p} (Holm), ε² = {e2}", fontsize=9,
                           fontweight="bold" if teste.significativo else "normal")
            eixo.grid(True, axis="y", alpha=0.3)
        fig.suptitle(fator.descricao, fontsize=11)
        caminho = destino / f"rq06_{fator.nome}.png"
        fig.savefig(caminho, dpi=150)
        plt.close(fig)
        gravados.append(caminho)
    return gravados
