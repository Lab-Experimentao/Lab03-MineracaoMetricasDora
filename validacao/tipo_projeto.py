"""Validação da classificação automática do tipo de projeto contra o consenso da amostra-ouro.

Precisão, recall e F1 por tipo, mais as médias macro e ponderada, com
`precision_recall_fscore_support` do scikit-learn.
"""

from __future__ import annotations

import pandas as pd
from sklearn.metrics import precision_recall_fscore_support

from metricas.tipo_projeto import TIPOS

COLUNAS_METRICAS = ["classe", "suporte", "previstos", "precisao", "recall", "f1"]
COLUNAS_ERROS = ["repositorio", "consenso", "heuristica", "descricao", "topicos", "pontos"]


def avaliar(consenso: pd.Series, previsto: pd.Series) -> pd.DataFrame:
    """Uma linha por tipo, mais `macro`, `ponderada` e `acuracia`; índices alinhados pelos repositórios."""
    precisao, recall, f1, suporte = precision_recall_fscore_support(
        consenso, previsto, labels=list(TIPOS), zero_division=0
    )
    linhas = [
        {"classe": tipo, "suporte": int(s), "previstos": int((previsto == tipo).sum()),
         "precisao": p, "recall": r, "f1": f}
        for tipo, p, r, f, s in zip(TIPOS, precisao, recall, f1, suporte)
    ]
    for media, nome in (("macro", "macro"), ("weighted", "ponderada")):
        p, r, f, _ = precision_recall_fscore_support(
            consenso, previsto, labels=list(TIPOS), average=media, zero_division=0
        )
        linhas.append({"classe": nome, "suporte": len(consenso), "previstos": len(previsto),
                       "precisao": p, "recall": r, "f1": f})
    acuracia = float((consenso == previsto).mean()) if len(consenso) else 0.0
    linhas.append({"classe": "acuracia", "suporte": len(consenso), "previstos": len(previsto),
                   "precisao": acuracia, "recall": acuracia, "f1": acuracia})
    return pd.DataFrame(linhas, columns=COLUNAS_METRICAS).round({"precisao": 4, "recall": 4, "f1": 4})
