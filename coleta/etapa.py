"""Etapa de coleta: seleciona a amostra, coleta cada repositório e grava os CSVs brutos.

Saída em `<saida.dir>/brutos/`. Reexecutar refaz tudo a partir do cache da API,
então uma coleta interrompida continua de onde parou.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from coleta import saida
from coleta.candidatos import gravar_candidatos, ler_candidatos
from coleta.cliente import ClienteGitHub
from coleta.repositorio import coletar_repositorio
from coleta.selecao import buscar_candidatos, embaralhar, resumir_funil, rotulo_faixa, selecionar
from pipeline.config import Config

log = logging.getLogger(__name__)


def executar(config: Config, token: str) -> None:
    destino = config.saida_dir / "brutos"
    arquivo = config.selecao.arquivo_candidatos
    with ClienteGitHub.de_config(config, token) as cliente:
        if arquivo.is_file():
            candidatos, faixas, buscado_em = ler_candidatos(arquivo)
            log.info("usando %d candidatos de %s (busca de %s; apague o arquivo para refazê-la)",
                     len(candidatos), arquivo, buscado_em)
            faixas_config = {rotulo_faixa(minimo, maximo) for minimo, maximo in config.selecao.faixas_estrelas}
            filtros = config.selecao.filtros_busca
            if faixas and (faixas_config != {f.faixa for f in faixas}
                           or not all(f.consulta.endswith(filtros) for f in faixas)):
                log.warning("as faixas ou os filtros do config mudaram desde a busca gravada em %s", arquivo)
        else:
            candidatos, faixas = buscar_candidatos(
                cliente, config.selecao.faixas_estrelas, config.selecao.filtros_busca
            )
            gravar_candidatos(arquivo, candidatos, faixas, datetime.now(timezone.utc).date())
            log.info("%d candidatos únicos, gravados em %s", len(candidatos), arquivo)
        avaliacoes = selecionar(cliente, embaralhar(candidatos, config.selecao.semente), config)

        amostra = [a.candidato for a in avaliacoes if a.incluido]
        coletas = []
        for indice, candidato in enumerate(amostra, start=1):
            log.info("[%d/%d] coletando %s", indice, len(amostra), candidato.nome)
            coletas.append(coletar_repositorio(cliente, candidato, config))
        log.info("chamadas à API: %d; respostas do cache: %d",
                 cliente.chamadas_api, cliente.acertos_cache)

    saida.gravar_csv(destino / "faixas_busca.csv", saida.linhas_faixas(faixas), saida.COLUNAS_FAIXAS)
    saida.gravar_csv(destino / "funil.csv", saida.linhas_funil(avaliacoes), saida.COLUNAS_FUNIL)
    etapas = resumir_funil(avaliacoes)
    saida.gravar_csv(destino / "funil_resumo.csv", saida.linhas_funil_resumo(etapas),
                     saida.COLUNAS_FUNIL_RESUMO)
    for etapa in etapas:
        log.info("funil: %-22s %5d", etapa.etapa, etapa.restantes)

    for nome, (gerar_linhas, colunas) in saida.ARQUIVOS_COLETA.items():
        total = saida.gravar_csv(destino / nome, gerar_linhas(coletas), colunas)
        log.info("gravado %s (%d linhas)", destino / nome, total)
