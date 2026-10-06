"""Leitura e validação do config.yaml e do token do GitHub."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

log = logging.getLogger(__name__)

VARIAVEL_TOKEN = "GITHUB_TOKEN"

class ErroConfig(ValueError):
    """Configuração ausente ou inválida."""

@dataclass(frozen=True)
class Janela:
    """Janela de observação em UTC; `inicio` e `fim` são inclusivos."""

    inicio: date
    fim: date

    @property
    def inicio_dt(self) -> datetime:
        return datetime.combine(self.inicio, time.min, tzinfo=timezone.utc)

    @property
    def fim_exclusivo_dt(self) -> datetime:
        return datetime.combine(self.fim + timedelta(days=1), time.min, tzinfo=timezone.utc)

    @property
    def dias(self) -> int:
        return (self.fim - self.inicio).days + 1

    @property
    def semanas(self) -> float:
        return self.dias / 7

    def contem(self, instante: datetime) -> bool:
        """Indica se um instante (com fuso) está dentro da janela."""
        if instante.tzinfo is None:
            raise ValueError("instante sem fuso horário; use datas em UTC")
        return self.inicio_dt <= instante < self.fim_exclusivo_dt


@dataclass(frozen=True)
class Selecao:
    faixas_estrelas: tuple[tuple[int, int | None], ...]
    filtros_busca: str
    arquivo_candidatos: Path
    semente: int
    tamanho_amostra: int


@dataclass(frozen=True)
class CriteriosInclusao:
    min_releases: int
    min_workflow_runs: int


@dataclass(frozen=True)
class WorkflowRuns:
    evento: str
    conclusoes_sucesso: frozenset[str]
    conclusoes_falha: frozenset[str]


@dataclass(frozen=True)
class Metricas:
    janela_release_corretiva_dias: int


@dataclass(frozen=True)
class Coleta:
    cache_dir: Path
    max_tentativas: int
    backoff_inicial_segundos: float
    timeout_segundos: float


@dataclass(frozen=True)
class ValidacaoManual:
    semente: int
    n_repositorios: int
    releases_por_repositorio: int


@dataclass(frozen=True)
class Config:
    janela: Janela
    selecao: Selecao
    criterios_inclusao: CriteriosInclusao
    workflow_runs: WorkflowRuns
    metricas: Metricas
    coleta: Coleta
    validacao_manual: ValidacaoManual
    saida_dir: Path


def _secao(dados: dict[str, Any], nome: str) -> dict[str, Any]:
    valor = dados.get(nome)
    if not isinstance(valor, dict):
        raise ErroConfig(f"seção '{nome}' ausente ou inválida no config")
    return valor


def _campo(secao: dict[str, Any], nome_secao: str, nome: str) -> Any:
    if nome not in secao or secao[nome] is None:
        raise ErroConfig(f"campo '{nome_secao}.{nome}' ausente no config")
    return secao[nome]


def _inteiro_positivo(secao: dict[str, Any], nome_secao: str, nome: str) -> int:
    valor = _campo(secao, nome_secao, nome)
    if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
        raise ErroConfig(f"'{nome_secao}.{nome}' deve ser um inteiro positivo")
    return valor


def _numero_positivo(secao: dict[str, Any], nome_secao: str, nome: str) -> float:
    valor = _campo(secao, nome_secao, nome)
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or valor <= 0:
        raise ErroConfig(f"'{nome_secao}.{nome}' deve ser um número positivo")
    return float(valor)


def _data(secao: dict[str, Any], nome_secao: str, nome: str) -> date:
    valor = _campo(secao, nome_secao, nome)
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor))
    except ValueError as erro:
        raise ErroConfig(f"'{nome_secao}.{nome}' deve estar no formato AAAA-MM-DD") from erro


def _janela(dados: dict[str, Any]) -> Janela:
    secao = _secao(dados, "janela")
    janela = Janela(_data(secao, "janela", "inicio"), _data(secao, "janela", "fim"))
    if janela.fim <= janela.inicio:
        raise ErroConfig("'janela.fim' deve ser posterior a 'janela.inicio'")
    if not 365 <= janela.dias <= 366:
        log.warning("a janela tem %d dias; a especificação pede 12 meses", janela.dias)
    return janela


def _faixas_estrelas(secao: dict[str, Any]) -> tuple[tuple[int, int | None], ...]:
    faixas = _campo(secao, "selecao", "faixas_estrelas")
    if not isinstance(faixas, list) or not faixas:
        raise ErroConfig("'selecao.faixas_estrelas' deve ser uma lista não vazia")
    resultado = []
    for faixa in faixas:
        if not isinstance(faixa, list) or len(faixa) != 2:
            raise ErroConfig(f"faixa de estrelas inválida: {faixa!r}; use [min, max]")
        minimo, maximo = faixa
        if not isinstance(minimo, int) or minimo < 0:
            raise ErroConfig(f"limite inferior inválido na faixa {faixa!r}")
        if maximo is not None and (not isinstance(maximo, int) or maximo < minimo):
            raise ErroConfig(f"limite superior inválido na faixa {faixa!r}")
        resultado.append((minimo, maximo))
    return tuple(resultado)


def _conclusoes(secao: dict[str, Any], nome: str) -> frozenset[str]:
    valor = _campo(secao, "workflow_runs", nome)
    if not isinstance(valor, list) or not valor:
        raise ErroConfig(f"'workflow_runs.{nome}' deve ser uma lista não vazia")
    return frozenset(str(v) for v in valor)


def carregar_config(caminho: str | Path) -> Config:
    """Lê o YAML em `caminho` e devolve a configuração validada.

    Caminhos relativos (cache, saída) são resolvidos a partir da pasta do config.
    """
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ErroConfig(f"arquivo de configuração não encontrado: {caminho}")
    with caminho.open(encoding="utf-8") as arquivo:
        dados = yaml.safe_load(arquivo)
    if not isinstance(dados, dict):
        raise ErroConfig(f"config vazio ou malformado: {caminho}")

    base = caminho.resolve().parent

    selecao = _secao(dados, "selecao")
    criterios = _secao(dados, "criterios_inclusao")
    runs = _secao(dados, "workflow_runs")
    metricas = _secao(dados, "metricas")
    coleta = _secao(dados, "coleta")
    validacao = _secao(dados, "validacao_manual")
    saida = _secao(dados, "saida")

    sucesso = _conclusoes(runs, "conclusoes_sucesso")
    falha = _conclusoes(runs, "conclusoes_falha")
    if sucesso & falha:
        raise ErroConfig(f"conclusões em sucesso e falha ao mesmo tempo: {sorted(sucesso & falha)}")

    return Config(
        janela=_janela(dados),
        selecao=Selecao(
            faixas_estrelas=_faixas_estrelas(selecao),
            filtros_busca=str(selecao.get("filtros_busca") or "").strip(),
            arquivo_candidatos=base / str(_campo(selecao, "selecao", "arquivo_candidatos")),
            semente=int(_campo(selecao, "selecao", "semente")),
            tamanho_amostra=_inteiro_positivo(selecao, "selecao", "tamanho_amostra"),
        ),
        criterios_inclusao=CriteriosInclusao(
            min_releases=_inteiro_positivo(criterios, "criterios_inclusao", "min_releases"),
            min_workflow_runs=_inteiro_positivo(criterios, "criterios_inclusao", "min_workflow_runs"),
        ),
        workflow_runs=WorkflowRuns(
            evento=str(_campo(runs, "workflow_runs", "evento")),
            conclusoes_sucesso=sucesso,
            conclusoes_falha=falha,
        ),
        metricas=Metricas(
            janela_release_corretiva_dias=_inteiro_positivo(
                metricas, "metricas", "janela_release_corretiva_dias"
            ),
        ),
        coleta=Coleta(
            cache_dir=base / str(_campo(coleta, "coleta", "cache_dir")),
            max_tentativas=_inteiro_positivo(coleta, "coleta", "max_tentativas"),
            backoff_inicial_segundos=_numero_positivo(coleta, "coleta", "backoff_inicial_segundos"),
            timeout_segundos=_numero_positivo(coleta, "coleta", "timeout_segundos"),
        ),
        validacao_manual=ValidacaoManual(
            semente=int(_campo(validacao, "validacao_manual", "semente")),
            n_repositorios=_inteiro_positivo(validacao, "validacao_manual", "n_repositorios"),
            releases_por_repositorio=_inteiro_positivo(
                validacao, "validacao_manual", "releases_por_repositorio"
            ),
        ),
        saida_dir=base / str(_campo(saida, "saida", "dir")),
    )


def obter_token(arquivo_env: str | Path | None = None) -> str:
    """Lê o token do GitHub da variável de ambiente GITHUB_TOKEN.

    Se `arquivo_env` existir, suas variáveis são carregadas antes, sem
    sobrescrever as que já estão definidas no ambiente.
    """
    if arquivo_env is not None and Path(arquivo_env).is_file():
        load_dotenv(arquivo_env, override=False)
    token = os.environ.get(VARIAVEL_TOKEN, "").strip()
    if not token:
        raise ErroConfig(
            f"variável de ambiente {VARIAVEL_TOKEN} não definida; defina-a no arquivo .env "
            "ou exporte-a no shell (crie um token em https://github.com/settings/tokens)"
        )
    return token
