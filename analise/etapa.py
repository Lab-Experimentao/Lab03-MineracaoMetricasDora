"""Etapa de análise: lê os CSVs de métricas e gera tabelas e gráficos das RQs.

RQ 01 a RQ 04 (estatística descritiva), em `dados/analise/`:
- `descritiva_rq01_rq04.csv`: mediana, IQR e demais estatísticas de cada métrica;
- `censura.csv`: episódios de recuperação e releases do CFR (b) censurados pelo fim da janela;
- `lead_time_divergencia.csv` e `lead_time_divergencia_repositorios.csv`: variante (a) x (b);
- `cfr_flaky.csv`: CFR de CI com e sem as falhas intermitentes.

Classificação DORA de referência (C1):
- `classificacao_distribuicao.csv`: repositórios por classe em cada dimensão e na geral;
- `classificacao_metricas_usadas.csv`: classe geral por número de dimensões e motivo de faltar a recuperação;
- `classificacao_sensibilidade.csv`: classe geral com outro arredondamento e com "sem falha" = Elite;
- `classificacao_limitante.csv`: dimensões abaixo da classe geral.

RQ 05 (velocidade x estabilidade):
- `rq05_spearman.csv`: ρ de Spearman entre frequência de deploy e CFR (a) e (b);
- `rq05_dispersao.png`: gráfico de dispersão em escala log.

RQ 06 (fatores associados ao desempenho), com o tipo de projeto de `dados/tipo_projeto.csv`:
- `rq06_testes.csv`: Kruskal-Wallis por fator e métrica, p-valor de Holm e ε²;
- `rq06_grupos.csv`: mediana e quartis de cada métrica por grupo;
- `rq06_cliff.csv`: Cliff's delta entre grupos;
- `rq06_<fator>.png`: boxplots dos fatores com algum teste significativo.

RQ 07 (sensibilidade às definições), a partir de `dados/metricas_combinacoes.csv`:
- `rq07_distribuicao.csv`: classe geral em cada combinação (C1, C2, C3);
- `rq07_concordancia.csv`: % que muda de classe e kappa de Cohen ponderado por par e dimensão;
- `rq07_transicoes.csv`: matriz de transição da classe geral por par.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from analise.classificacao import CLASSES, dimensao_limitante, distribuicao, perfil_metricas_usadas, sensibilidade
from analise.combinacoes import concordancia_pares, distribuicao as distribuicao_combinacoes, transicoes
from analise.correlacao import grafico_dispersao, spearman
from analise.fatores import comparar_grupos, graficos_fatores, grupos_fatores, resumo_grupos, tabela_cliff
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
ARQUIVO_TIPOS = "tipo_projeto.csv"
ARQUIVO_COMBINACOES = "metricas_combinacoes.csv"
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

    tabela_distribuicao = distribuicao(df)
    _gravar(tabela_distribuicao, destino / "classificacao_distribuicao.csv")
    geral = tabela_distribuicao[tabela_distribuicao["dimensao"] == "geral"].set_index("classe")["repositorios"]
    log.info("classificação geral (C1): %s", ", ".join(f"{c} {geral[c]}" for c in CLASSES))
    _gravar(perfil_metricas_usadas(df), destino / "classificacao_metricas_usadas.csv")
    tabela_sensibilidade = sensibilidade(df)
    _gravar(tabela_sensibilidade, destino / "classificacao_sensibilidade.csv")
    for linha in tabela_sensibilidade.itertuples():
        log.info("classificação geral (%s): %s; %d empates; %d mudam de classe", linha.cenario,
                 ", ".join(f"{c} {getattr(linha, c)}" for c in CLASSES), linha.empates, linha.mudam_de_classe)
    _gravar(dimensao_limitante(df), destino / "classificacao_limitante.csv")

    correlacao = spearman(df)
    _gravar(correlacao, destino / "rq05_spearman.csv")
    for linha in correlacao.itertuples():
        log.info("RQ05 %s frequência x %s: rho %.3f, p %.3g, n %d (%d com CFR = 0)",
                 linha.variante, linha.metrica_cfr, linha.rho, linha.p_valor, linha.n, linha.cfr_zero)
    grafico_dispersao(df, correlacao, destino / "rq05_dispersao.png")
    log.info("gravado %s", destino / "rq05_dispersao.png")

    arquivo_tipos = config.saida_dir / ARQUIVO_TIPOS
    if not arquivo_tipos.is_file():
        raise FileNotFoundError(f"{arquivo_tipos} não encontrado; rode antes a etapa tipo_projeto")
    grupos = grupos_fatores(df, pd.read_csv(arquivo_tipos), config.janela.fim_exclusivo_dt)
    resultado = comparar_grupos(df, grupos)
    _gravar(resultado, destino / "rq06_testes.csv")
    _gravar(resumo_grupos(df, grupos), destino / "rq06_grupos.csv")
    _gravar(tabela_cliff(df, grupos), destino / "rq06_cliff.csv")
    for linha in resultado[resultado["significativo"]].itertuples():
        log.info("RQ06 %s x %s: H %.2f, p (Holm) %.3g, ε² %.3f (%s)", linha.fator, linha.metrica,
                 linha.estatistica, linha.p_holm, linha.epsilon2, linha.efeito)
    log.info("RQ06: %d de %d testes significativos após Holm", resultado["significativo"].sum(), len(resultado))
    for caminho in graficos_fatores(df, grupos, resultado, destino):
        log.info("gravado %s", caminho)

    arquivo_combinacoes = config.saida_dir / ARQUIVO_COMBINACOES
    if not arquivo_combinacoes.is_file():
        raise FileNotFoundError(f"{arquivo_combinacoes} não encontrado; rode antes a etapa de métricas")
    por_combinacao = pd.read_csv(arquivo_combinacoes)
    tabela_combinacoes = distribuicao_combinacoes(por_combinacao)
    _gravar(tabela_combinacoes, destino / "rq07_distribuicao.csv")
    for linha in tabela_combinacoes.itertuples():
        log.info("RQ07 %s: %s", linha.combinacao, ", ".join(f"{c} {getattr(linha, c)}" for c in CLASSES))
    pares = concordancia_pares(por_combinacao)
    _gravar(pares, destino / "rq07_concordancia.csv")
    for linha in pares[pares["dimensao"] == "geral"].itertuples():
        log.info("RQ07 %s: %d de %d mudam de classe (%.1f%%), kappa linear %.3f (%s)", linha.par, linha.mudam,
                 linha.repositorios, 100 * linha.proporcao_mudam, linha.kappa_linear, linha.interpretacao)
    _gravar(transicoes(por_combinacao), destino / "rq07_transicoes.csv")
