"""Ponto de entrada único: python -m pipeline --config config.yaml"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from pipeline.config import ErroConfig, carregar_config, obter_token

ETAPAS = ("coleta", "metricas", "analise")

log = logging.getLogger("pipeline")


def _argumentos(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline",
        description="Pipeline de mineração de métricas DORA em repositórios do GitHub.",
    )
    parser.add_argument("--config", required=True, help="caminho do config.yaml")
    parser.add_argument(
        "--etapas",
        nargs="+",
        choices=ETAPAS,
        default=list(ETAPAS),
        help="etapas a executar, na ordem do pipeline (padrão: todas)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log em nível DEBUG")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _argumentos(argv)
    # Evita acentos corrompidos em terminais Windows que não usam UTF-8 por padrão.
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        config = carregar_config(args.config)
        arquivo_env = Path(args.config).resolve().parent / ".env"
        token = obter_token(arquivo_env) if "coleta" in args.etapas else None
    except ErroConfig as erro:
        log.error("%s", erro)
        return 2

    log.info(
        "janela de observação: %s a %s (%d dias)",
        config.janela.inicio, config.janela.fim, config.janela.dias,
    )
    config.coleta.cache_dir.mkdir(parents=True, exist_ok=True)
    config.saida_dir.mkdir(parents=True, exist_ok=True)

    # Importações tardias: cada etapa só carrega suas dependências se for executada.
    for etapa in (e for e in ETAPAS if e in args.etapas):
        log.info("iniciando etapa: %s", etapa)
        if etapa == "coleta":
            from coleta.etapa import executar as executar_coleta
            executar_coleta(config, token)
        elif etapa == "metricas":
            from metricas.etapa import executar as executar_metricas
            try:
                executar_metricas(config)
            except FileNotFoundError as erro:
                log.error("%s", erro)
                return 2
        elif etapa == "analise":
            from analise.etapa import executar as executar_analise
            executar_analise(config)

    log.info("pipeline concluído")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.warning("interrompido; rode o mesmo comando para continuar de onde parou")
        sys.exit(130)
