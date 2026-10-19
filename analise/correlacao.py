"""RQ 05: velocidade x estabilidade, correlação de Spearman entre frequência de deploy e CFR.

`spearman` não faz I/O; `grafico_dispersao` grava a figura.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

FREQUENCIA = "deploys_por_semana"


@dataclass(frozen=True)
class VarianteCFR:
    nome: str
    coluna: str
    descricao: str


VARIANTES = (
    VarianteCFR("(a)", "cfr_ci", "CFR de CI"),
    VarianteCFR("(b)", "cfr_entrega", "CFR de entrega (release corretiva em até 7 dias)"),
)
COLUNAS_SPEARMAN = ["variante", "metrica_cfr", "descricao", "n", "sem_par", "cfr_zero", "rho", "p_valor"]


def pares(df: pd.DataFrame, coluna: str) -> pd.DataFrame:
    """Repositórios com frequência e CFR preenchidos."""
    return df[[FREQUENCIA, coluna]].apply(pd.to_numeric, errors="coerce").dropna()


def spearman(df: pd.DataFrame) -> pd.DataFrame:
    """ρ de Spearman, p-valor bilateral e n entre `deploys_por_semana` e cada variante do CFR.

    Só entram os repositórios com os dois valores; `sem_par` conta os que ficaram de fora e
    `cfr_zero` os que têm CFR igual a 0 (empatados no menor posto).
    """
    linhas = []
    for variante in VARIANTES:
        dados = pares(df, variante.coluna)
        if len(dados) >= 3:
            rho, p = spearmanr(dados[FREQUENCIA], dados[variante.coluna])
        else:
            rho = p = float("nan")
        linhas.append({
            "variante": variante.nome,
            "metrica_cfr": variante.coluna,
            "descricao": variante.descricao,
            "n": len(dados),
            "sem_par": len(df) - len(dados),
            "cfr_zero": int((dados[variante.coluna] == 0).sum()),
            "rho": float(rho),
            "p_valor": float(p),
        })
    return pd.DataFrame(linhas, columns=COLUNAS_SPEARMAN)


def grafico_dispersao(df: pd.DataFrame, resultado: pd.DataFrame, caminho: Path) -> None:
    """Dispersão em escala log (frequência x CFR), um painel por variante.

    CFR = 0 não existe em escala log: esses pontos ficam numa faixa abaixo do menor CFR positivo,
    com outro marcador.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, eixos = plt.subplots(1, len(VARIANTES), figsize=(11, 4.5), constrained_layout=True)
    for eixo, variante, linha in zip(eixos, VARIANTES, resultado.itertuples()):
        dados = pares(df, variante.coluna)
        positivos = dados[dados[variante.coluna] > 0]
        zeros = dados[dados[variante.coluna] == 0]
        eixo.scatter(positivos[FREQUENCIA], positivos[variante.coluna], s=14, alpha=0.6)
        if len(zeros):
            piso = positivos[variante.coluna].min() / 2 if len(positivos) else 1e-3
            eixo.scatter(zeros[FREQUENCIA], [piso] * len(zeros), s=14, alpha=0.6, marker="x", color="tab:red")
            eixo.annotate(f"CFR = 0 ({len(zeros)})", xy=(0.01, piso), xycoords=("axes fraction", "data"),
                          xytext=(0, 6), textcoords="offset points", fontsize=8, color="tab:red")
        eixo.set_xscale("log")
        eixo.set_yscale("log")
        eixo.set_xlabel("deploys por semana (log)")
        eixo.set_ylabel(f"{variante.coluna} (log)")
        p = "p < 0,001" if linha.p_valor < 0.001 else f"p = {linha.p_valor:.3f}".replace(".", ",")
        rho = f"{linha.rho:.2f}".replace(".", ",")
        eixo.set_title(f"{variante.nome} {variante.descricao}\nρ = {rho}, {p}, n = {linha.n}", fontsize=10)
        eixo.grid(True, which="major", alpha=0.3)
    fig.savefig(caminho, dpi=150)
    plt.close(fig)
