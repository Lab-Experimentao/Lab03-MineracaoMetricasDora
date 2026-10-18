"""Etapa de análise: lê os CSVs de métricas e gera tabelas e gráficos das RQs.

RQ 01 a RQ 04 (estatística descritiva), em `dados/analise/`:
- `descritiva_rq01_rq04.csv`: mediana, IQR e demais estatísticas de cada métrica;
- `censura.csv`: episódios de recuperação e releases do CFR (b) censurados pelo fim da janela;
- `lead_time_divergencia.csv` e `lead_time_divergencia_repositorios.csv`: variante (a) x (b);
- `cfr_flaky.csv`: CFR de CI com e sem as falhas intermitentes.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from analise.descritiva import (
    censura,
    divergencia_lead_time,
    divergencia_lead_time_repositorios,
    impacto_flaky,
    tabela_descritiva,
)
from pipeline.config import Config

log = logging.getLogger(__name__)

ARQUIVO_METRICAS = "metricas.csv"
DIR_ANALISE = "analise"


def _gravar(tabela: pd.DataFrame, caminho: Path) -> None:
    tabela.to_csv(caminho, index=False, encoding="utf-8", float_format="%.4f")
    log.info("gravado %s (%d linhas)", caminho, len(tabela))


def executar(config: Config) -> None:
    origem = config.saida_dir / ARQUIVO_METRICAS
    if not origem.is_file():
        raise FileNotFoundError(f"{origem} não encontrado; rode antes a etapa de métricas")
    df = pd.read_csv(origem)
    destino = config.saida_dir / DIR_ANALISE
    destino.mkdir(parents=True, exist_ok=True)

    descritiva = tabela_descritiva(df)
    _gravar(descritiva, destino / "descritiva_rq01_rq04.csv")
    for linha in descritiva.itertuples():
        log.info("%s %s: mediana %.4g (IQR %.4g; n=%d, ausentes=%d)",
                 linha.rq, linha.metrica, linha.mediana, linha.iqr, linha.n, linha.ausentes)

    tabela_censura = censura(df)
    _gravar(tabela_censura, destino / "censura.csv")
    for linha in tabela_censura.itertuples():
        log.info("%s: censura em %d de %d %s (%.1f%%), em %d repositórios",
                 linha.rq, linha.censurados, linha.observados + linha.censurados, linha.unidade,
                 100 * linha.proporcao_censurados, linha.repositorios_com_censura)

    por_repositorio = divergencia_lead_time_repositorios(df)
    _gravar(por_repositorio, destino / "lead_time_divergencia_repositorios.csv")
    resumo_lead = divergencia_lead_time(por_repositorio)
    _gravar(resumo_lead, destino / "lead_time_divergencia.csv")
    lead = resumo_lead.iloc[0]
    log.info("lead time: (b) > (a) em %d de %d repositórios; razão b/a mediana %.2f; Spearman %.2f",
             lead.commit_maior, lead.repositorios, lead.mediana_razao, lead.spearman)

    flaky = impacto_flaky(df)
    _gravar(flaky, destino / "cfr_flaky.csv")
    for linha in flaky.itertuples():
        log.info("CFR de CI (%s): mediana %.2f%% (%+.2f p.p.), agregado %.2f%%, parcela flaky %.1f%%",
                 linha.cenario, 100 * linha.mediana, linha.diferenca_mediana_pp, 100 * linha.cfr_agregado,
                 100 * linha.parcela_flaky_agregada)
