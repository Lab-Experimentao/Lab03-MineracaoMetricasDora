"""Cliente HTTP da API REST do GitHub com cache, rate limit, backoff e paginação."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

import requests

from coleta.cache import CacheRespostas
from pipeline.config import Config

log = logging.getLogger(__name__)

API_URL = "https://api.github.com"
VERSAO_API = "2022-11-28"

# Erros definitivos (ex.: compare de tag apagada) ficam em cache para não serem repetidos.
STATUS_ERRO_CACHEAVEL = frozenset({404, 409, 410, 451})

MARGEM_RESET_SEGUNDOS = 2.0
# Espera recomendada pelo GitHub no limite secundário sem Retry-After.
ESPERA_MINIMA_LIMITE_SECUNDARIO = 60.0
ESPERA_MAXIMA_BACKOFF = 300.0

_PADRAO_LINK = re.compile(r'<([^>]+)>\s*;\s*rel="([^"]+)"')


def ler_cabecalho_link(valor: str | None) -> dict[str, str]:
    """Converte o cabeçalho Link em {rel: url}."""
    if not valor:
        return {}
    return {rel: url for url, rel in _PADRAO_LINK.findall(valor)}


class ErroAPI(Exception):
    def __init__(self, mensagem: str, status: int | None = None, url: str | None = None) -> None:
        super().__init__(mensagem)
        self.status = status
        self.url = url


@dataclass(frozen=True)
class Resposta:
    status: int
    dados: Any
    links: dict[str, str]
    do_cache: bool


@dataclass
class _Cota:
    restantes: int
    reset_epoch: float


class ClienteGitHub:
    """`sessao`, `dormir` e `relogio` são injetáveis para os testes."""

    def __init__(
        self,
        token: str,
        cache: CacheRespostas,
        *,
        max_tentativas: int = 6,
        backoff_inicial: float = 1.0,
        timeout: float = 30.0,
        sessao: requests.Session | None = None,
        dormir: Callable[[float], None] = time.sleep,
        relogio: Callable[[], float] = time.time,
        url_base: str = API_URL,
    ) -> None:
        self.cache = cache
        self.max_tentativas = max_tentativas
        self.backoff_inicial = backoff_inicial
        self.timeout = timeout
        self.url_base = url_base.rstrip("/") + "/"
        self._dormir = dormir
        self._relogio = relogio
        self._sessao = sessao or requests.Session()
        self._sessao.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": VERSAO_API,
            "User-Agent": "lab03-mineracao-metricas-dora",
        })
        # Cada recurso da API ("core", "search") tem cota própria.
        self._cotas: dict[str, _Cota] = {}
        self.chamadas_api = 0
        self.acertos_cache = 0

    @classmethod
    def de_config(cls, config: Config, token: str) -> ClienteGitHub:
        coleta = config.coleta
        return cls(
            token,
            CacheRespostas(coleta.cache_dir / "api.sqlite"),
            max_tentativas=coleta.max_tentativas,
            backoff_inicial=coleta.backoff_inicial_segundos,
            timeout=coleta.timeout_segundos,
        )

    def fechar(self) -> None:
        self._sessao.close()
        self.cache.fechar()

    def __enter__(self) -> ClienteGitHub:
        return self

    def __exit__(self, *_: object) -> None:
        self.fechar()

    def montar_url(self, caminho: str, params: dict[str, Any] | None = None) -> str:
        url = urljoin(self.url_base, caminho.lstrip("/")) if not caminho.startswith("http") else caminho
        if params:
            separador = "&" if urlsplit(url).query else "?"
            url += separador + urlencode({k: v for k, v in params.items() if v is not None})
        return url

    def obter(
        self, caminho: str, params: dict[str, Any] | None = None, *, usar_cache: bool = True
    ) -> Resposta:
        """GET de uma página; lança ErroAPI se o status for de erro."""
        url = self.montar_url(caminho, params)
        if usar_cache:
            cacheada = self.cache.obter(url)
            if cacheada is not None:
                self.acertos_cache += 1
                log.debug("cache: %s", url)
                return self._verificar(
                    Resposta(cacheada.status, cacheada.dados, cacheada.links, do_cache=True), url
                )

        resposta = self._requisitar(url)
        links = ler_cabecalho_link(resposta.headers.get("Link"))
        dados = _corpo_json(resposta)
        if usar_cache and (resposta.status_code < 300 or resposta.status_code in STATUS_ERRO_CACHEAVEL):
            self.cache.gravar(url, resposta.status_code, dados, links)
        return self._verificar(Resposta(resposta.status_code, dados, links, do_cache=False), url)

    def paginas(
        self, caminho: str, params: dict[str, Any] | None = None, *, max_paginas: int | None = None
    ) -> Iterator[Resposta]:
        """Percorre as páginas seguindo o rel="next" do cabeçalho Link."""
        url: str | None = self.montar_url(caminho, params)
        lidas = 0
        while url is not None and (max_paginas is None or lidas < max_paginas):
            resposta = self.obter(url)
            lidas += 1
            yield resposta
            url = resposta.links.get("next")

    def paginar(
        self,
        caminho: str,
        params: dict[str, Any] | None = None,
        *,
        chave_itens: str | None = None,
        max_paginas: int | None = None,
    ) -> Iterator[Any]:
        """Itera os itens de todas as páginas.

        `chave_itens` indica a lista quando o corpo é um objeto ("items", "workflow_runs", "commits").
        """
        for pagina in self.paginas(caminho, params, max_paginas=max_paginas):
            if pagina.dados is None:
                continue
            itens = pagina.dados if chave_itens is None else pagina.dados.get(chave_itens, [])
            yield from itens

    def graphql(self, consulta: str, variaveis: dict[str, Any] | None = None) -> Any:
        """POST na API GraphQL; devolve o campo `data`.

        A URL é sempre a mesma, então a chave do cache é o hash da consulta com as
        variáveis. Respostas com `errors` não vão para o cache e viram ErroAPI.
        """
        corpo = {"query": consulta, "variables": variaveis or {}}
        resumo = hashlib.sha256(json.dumps(corpo, sort_keys=True).encode()).hexdigest()
        chave = self.montar_url("graphql", {"consulta": resumo})
        cacheada = self.cache.obter(chave)
        if cacheada is not None:
            self.acertos_cache += 1
            log.debug("cache: graphql %s", resumo[:12])
            return cacheada.dados

        url = self.montar_url("graphql")
        for _ in range(self.max_tentativas):
            resposta = self._requisitar(url, corpo)
            dados = _corpo_json(resposta)
            erros = dados.get("errors") if isinstance(dados, dict) else None
            if resposta.status_code < 400 and not erros:
                self.cache.gravar(chave, resposta.status_code, dados["data"], {})
                return dados["data"]
            tipos = {e.get("type") for e in erros or []}
            if "RATE_LIMITED" in tipos:
                # Cota esgotada com HTTP 200. Se os cabeçalhos já zeraram a cota, a próxima
                # requisição espera a renovação; senão, espera o mínimo do limite secundário.
                cota = self._cotas.get("graphql")
                if cota is None or cota.restantes > 0:
                    log.warning("cota GraphQL esgotada; aguardando %.0f s", ESPERA_MINIMA_LIMITE_SECUNDARIO)
                    self._dormir(ESPERA_MINIMA_LIMITE_SECUNDARIO)
                continue
            status = 404 if "NOT_FOUND" in tipos else resposta.status_code
            mensagens = "; ".join(e.get("message", "") for e in erros or []) or str(dados)
            raise ErroAPI(f"GraphQL HTTP {status}: {mensagens}", status=status, url=url)
        raise ErroAPI(f"cota GraphQL esgotada após {self.max_tentativas} tentativas", url=url)

    def rate_limit(self) -> dict[str, Any]:
        """Cota atual; não consome cota nem usa o cache."""
        return self.obter("/rate_limit", usar_cache=False).dados

    def _requisitar(self, url: str, corpo: dict[str, Any] | None = None) -> requests.Response:
        """GET em `url`, ou POST com `corpo` em JSON (GraphQL)."""
        recurso = _recurso_da_url(url)
        tentativa = 0
        while True:
            self._aguardar_cota(recurso)
            tentativa += 1
            try:
                self.chamadas_api += 1
                if corpo is None:
                    resposta = self._sessao.get(url, timeout=self.timeout)
                else:
                    resposta = self._sessao.post(url, json=corpo, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as erro:
                self._backoff_ou_desistir(tentativa, url, f"erro de rede: {erro}")
                continue

            self._registrar_cota(resposta, recurso)
            status = resposta.status_code

            if status in (403, 429) and resposta.headers.get("X-RateLimit-Remaining") == "0":
                # Cota esgotada: espera a renovação sem gastar tentativa.
                tentativa -= 1
                continue
            if status in (403, 429) and _e_limite_secundario(resposta):
                espera = _float(resposta.headers.get("Retry-After"))
                if espera is None:
                    espera = max(ESPERA_MINIMA_LIMITE_SECUNDARIO, self._espera_backoff(tentativa))
                self._desistir_se_esgotou(tentativa, url, "limite secundário de requisições", status)
                log.warning("limite secundário do GitHub; aguardando %.0f s", espera)
                self._dormir(espera)
                continue
            if status >= 500:
                self._backoff_ou_desistir(tentativa, url, f"HTTP {status}", status)
                continue
            return resposta

    def _aguardar_cota(self, recurso: str) -> None:
        cota = self._cotas.get(recurso)
        if cota is None or cota.restantes > 0:
            return
        # A margem evita um laço de 403 se o relógio local estiver adiantado.
        espera = max(cota.reset_epoch - self._relogio(), 0) + MARGEM_RESET_SEGUNDOS
        del self._cotas[recurso]
        log.warning(
            "cota '%s' da API esgotada; pausando %.1f min até a renovação", recurso, espera / 60
        )
        self._dormir(espera)

    def _registrar_cota(self, resposta: requests.Response, recurso_padrao: str) -> None:
        restantes = resposta.headers.get("X-RateLimit-Remaining")
        reset = resposta.headers.get("X-RateLimit-Reset")
        if restantes is None or reset is None:
            return
        recurso = resposta.headers.get("X-RateLimit-Resource", recurso_padrao)
        self._cotas[recurso] = _Cota(int(restantes), float(reset))

    def _espera_backoff(self, tentativa: int) -> float:
        return min(self.backoff_inicial * 2 ** (tentativa - 1), ESPERA_MAXIMA_BACKOFF)

    def _desistir_se_esgotou(self, tentativa: int, url: str, motivo: str, status: int | None) -> None:
        if tentativa >= self.max_tentativas:
            raise ErroAPI(f"{motivo} após {tentativa} tentativas: {url}", status=status, url=url)

    def _backoff_ou_desistir(
        self, tentativa: int, url: str, motivo: str, status: int | None = None
    ) -> None:
        self._desistir_se_esgotou(tentativa, url, motivo, status)
        espera = self._espera_backoff(tentativa)
        log.warning(
            "%s em %s; nova tentativa em %.0f s (%d/%d)",
            motivo, url, espera, tentativa + 1, self.max_tentativas,
        )
        self._dormir(espera)

    @staticmethod
    def _verificar(resposta: Resposta, url: str) -> Resposta:
        if resposta.status >= 400:
            mensagem = resposta.dados.get("message", "") if isinstance(resposta.dados, dict) else ""
            raise ErroAPI(f"HTTP {resposta.status} em {url}: {mensagem}", status=resposta.status, url=url)
        return resposta


def _recurso_da_url(url: str) -> str:
    caminho = urlsplit(url).path
    if caminho.startswith("/search/"):
        return "search"
    if caminho.startswith("/graphql"):
        return "graphql"
    return "core"


def _e_limite_secundario(resposta: requests.Response) -> bool:
    if "Retry-After" in resposta.headers or resposta.status_code == 429:
        return True
    corpo = _corpo_json(resposta)
    mensagem = corpo.get("message", "") if isinstance(corpo, dict) else ""
    return "rate limit" in mensagem.lower()


def _corpo_json(resposta: requests.Response) -> Any:
    if not resposta.content:
        return None
    try:
        return resposta.json()
    except ValueError:
        return {"message": resposta.text}


def _float(valor: str | None) -> float | None:
    try:
        return float(valor) if valor is not None else None
    except ValueError:
        return None
