"""Classificação automática do tipo de projeto (fator da RQ 06) a partir do perfil do repositório.

Cada tipo tem padrões procurados na descrição (peso 3), nos tópicos (peso 2) e no começo do
README (peso 1). O tipo com mais pontos vence; sem nenhum sinal, vale o tipo mais comum na
amostra-ouro. Cada versão dos padrões fica em `VERSOES` e é validada contra o consenso dos
60 repositórios rotulados (validacao/tipo_projeto.py).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

BIBLIOTECA = "biblioteca/framework"
APLICACAO = "aplicação/serviço"
CLI = "ferramenta CLI"
OUTRO = "outro"
TIPOS = (BIBLIOTECA, APLICACAO, CLI, OUTRO)

# Ordem de desempate (e tipo sem nenhum sinal): do mais comum ao menos comum na amostra-ouro.
PRIORIDADE = (APLICACAO, BIBLIOTECA, CLI, OUTRO)

PESO_DESCRICAO, PESO_TOPICOS, PESO_README = 3, 2, 1


def _re(*padroes: str) -> re.Pattern[str]:
    return re.compile("|".join(padroes), re.IGNORECASE)


@dataclass(frozen=True)
class Sinais:
    descricao: re.Pattern[str]
    topicos: frozenset[str]
    readme: re.Pattern[str]


SINAIS_V1: dict[str, Sinais] = {
    BIBLIOTECA: Sinais(
        descricao=_re(r"\blibrar(y|ies)\b", r"\bframework\b", r"\bsdk\b", r"\bbindings?\b", r"\btoolkit\b",
                      r"\bplugin\b", r"\bwrapper\b", r"\bparser\b", r"\bclient (library )?for\b",
                      r"\bimplementation of\b", r"\butilit(y|ies)\b", r"\btemplate engine\b"),
        topicos=frozenset({"library", "framework", "sdk", "bindings", "api-client", "package",
                           "npm-package", "python-library", "java-library", "rust-library", "toolkit"}),
        readme=_re(r"\b(pip install|npm (install|i)|yarn add|pnpm add|go get|cargo add|composer require|"
                   r"gem install|dotnet add package|install-package)\b(?! -g| --global)",
                   r"<dependency>", r"\bimplementation[ (]['\"]", r"\[dependencies\]"),
    ),
    APLICACAO: Sinais(
        descricao=_re(r"\bapps?\b", r"\bapplication\b", r"\bplatform\b", r"\bself-?hosted\b", r"\bserver\b",
                      r"\bdashboard\b", r"\bemulator\b", r"\bdesktop\b", r"\bweb ?ui\b", r"\bmanager\b",
                      r"\beditor\b", r"\bplayer\b", r"\bgame\b", r"\bmessenger\b", r"\bdatabase\b", r"\bcms\b"),
        topicos=frozenset({"app", "application", "desktop-app", "desktop", "self-hosted", "selfhosted",
                           "web-app", "webapp", "android", "ios", "electron", "tauri", "server", "platform",
                           "dashboard", "emulator", "game", "cms", "pwa", "mobile-app"}),
        readme=_re(r"\bdocker (run|compose|-compose)\b", r"\bdocker-compose\b", r"\bscreenshots?\b",
                   r"\bdownload the (latest )?(release|app|installer)\b", r"\bself-?host"),
    ),
    CLI: Sinais(
        descricao=_re(r"\bcli\b", r"\bcommand[- ]line\b", r"\bterminal\b", r"\btui\b"),
        topicos=frozenset({"cli", "command-line", "command-line-tool", "cli-tool", "cli-app", "terminal",
                           "tui", "shell"}),
        readme=_re(r"\b(brew|cargo|go|pipx|uv tool) install\b", r"\bnpm (install|i) (-g|--global)\b",
                   r"\bnpx \w"),
    ),
    OUTRO: Sinais(
        descricao=_re(r"\bgithub action\b", r"\bawesome\b", r"\bcurated list\b", r"\btemplate\b",
                      r"\bdotfiles\b", r"\bmod(s|ding)?\b"),
        topicos=frozenset({"github-action", "github-actions", "awesome", "awesome-list", "template",
                           "latex-template", "dotfiles", "modding", "mod"}),
        readme=_re(r"\buses: [\w.-]+/[\w.-]+@"),
    ),
}


# v2: corrige os tipos de erro da v1 (detalhes no README):
# - biblioteca: "HTTP/API client", "client for/in <linguagem>", ORM, badges e links de pacote
#   publicado (npm, PyPI, crates.io, Maven Central, NuGet...); "plugin" sai, por ser ambíguo;
# - aplicação: "database" e "desktop" soltos saem (bibliotecas também os usam); entram
#   "desktop app", "web interface" e "MCP server";
# - CLI: linters, formatadores, profilers e análise estática; "subcommand"; instalação por
#   Homebrew, Chocolatey, Scoop ou winget; "single/static binary";
# - outro: GitHub Action no README e plugins/extensões de aplicativos (Obsidian, VS Code, navegador).
_LINGUAGENS = (r"(java|jvm|python|erlang|elixir|scala|ruby|php|rust|go|golang|node(\.js)?|javascript|"
               r"typescript|\.net|c#|dart|swift|kotlin|haskell|lua|vue(\.js)?|react)")
SINAIS_V2: dict[str, Sinais] = {
    BIBLIOTECA: Sinais(
        descricao=_re(r"\blibrar(y|ies)\b", r"\bframework\b", r"\bsdk\b", r"\bbindings?\b", r"\btoolkit\b",
                      r"\bwrapper\b", r"\bparser\b", r"\b(http|api|rest|graphql|grpc) client\b",
                      r"\bclient (library )?(for|in)\b", rf"\b(for|in) (the )?{_LINGUAGENS}(?=[\s.,!]|$)",
                      r"\bimplementation of\b", r"\butilit(y|ies)\b", r"\btemplate engine\b",
                      r"\bobject[- ](relational|database) mapper\b", r"\borm\b", r"\bmodeling tool\b"),
        topicos=frozenset({"library", "framework", "sdk", "bindings", "api-client", "package", "npm-package",
                           "python-library", "java-library", "rust-library", "toolkit", "http-client",
                           "httpclient", "orm", "api-wrapper", "component-library", "ui-components"}),
        readme=_re(r"\b(pip install|npm (install|i)|yarn add|pnpm add|go get|cargo add|composer require|"
                   r"gem install|dotnet add package|install-package)\b(?! -g| --global)",
                   r"<dependency>", r"\bimplementation[ (]['\"]", r"\[dependencies\]",
                   r"badge\.fury\.io|img\.shields\.io/(npm|pypi|crates|nuget|maven-central|gem|hexpm|packagist)",
                   r"npmjs\.(com|org)/package|pypi\.org/project|crates\.io/crates|search\.maven\.org",
                   r"nuget\.org/packages|hex\.pm/packages|packagist\.org/packages"),
    ),
    APLICACAO: Sinais(
        descricao=_re(r"\bapps?\b", r"\bapplication\b", r"\bplatform\b", r"\bself-?hosted\b", r"\bserver\b",
                      r"\bdashboard\b", r"\bemulator\b", r"\bdesktop (app|application|client|pet)\b",
                      r"\bweb ?(ui|interface)\b", r"\bmanager\b", r"\beditor\b", r"\bplayer\b", r"\bgame\b",
                      r"\bmessenger\b", r"\bcms\b", r"\bmcp\b"),
        topicos=frozenset({"app", "application", "desktop-app", "self-hosted", "selfhosted", "web-app",
                           "webapp", "android", "ios", "electron", "tauri", "server", "platform", "dashboard",
                           "emulator", "game", "cms", "pwa", "mobile-app", "mcp-server", "headless-cms"}),
        readme=_re(r"\bdocker (run|compose|-compose)\b", r"\bdocker-compose\b", r"\bscreenshots?\b",
                   r"\bdownload the (latest )?(release|app|installer)\b", r"\bself-?host", r"\bmcp server\b"),
    ),
    CLI: Sinais(
        descricao=_re(r"\bcli\b", r"\bcommand[- ]line\b", r"\bterminal\b", r"\btui\b", r"\blint(er|ing)\b",
                      r"\bformatter\b", r"\bprofiler\b", r"\bstatic analy(sis|zer)\b",
                      r"\bcode quality analy", r"\bnormaliz(e|es|ing)\b"),
        topicos=frozenset({"cli", "command-line", "command-line-tool", "cli-tool", "cli-app", "terminal", "tui",
                           "shell", "linter", "formatter", "profiler", "static-analysis", "code-quality",
                           "cargo-subcommand"}),
        readme=_re(r"\b(brew|cargo|go|pipx|uv tool) install\b", r"\bnpm (install|i) (-g|--global)\b",
                   r"\b(chocolatey|scoop|winget|homebrew)\b", r"\b(single|static) binary\b"),
    ),
    OUTRO: Sinais(
        descricao=_re(r"\bgithub action\b", r"\bawesome\b", r"\bcurated list\b", r"\btemplate\b",
                      r"\bdotfiles\b", r"\bmod(s|ding)?\b",
                      r"\b(obsidian|vs ?code|chrome|firefox|browser) (plugin|extension)\b"),
        topicos=frozenset({"github-action", "github-actions", "awesome", "awesome-list", "template",
                           "latex-template", "dotfiles", "modding", "mod", "obsidian-plugin", "vscode-extension",
                           "browser-extension", "chrome-extension"}),
        readme=_re(r"\buses: [\w.-]+/[\w.-]+@", r"\baction for github actions\b"),
    ),
}

# Versões avaliadas na amostra-ouro; a de VERSAO_ATUAL é a usada na classificação.
VERSOES: dict[str, dict[str, Sinais]] = {"v1": SINAIS_V1, "v2": SINAIS_V2}
VERSAO_ATUAL = "v2"


@dataclass(frozen=True)
class Classificacao:
    tipo: str
    pontos: dict[str, int]


def pontuar(descricao: str, topicos: Iterable[str], readme: str, versao: str = VERSAO_ATUAL) -> dict[str, int]:
    topicos = {t.lower() for t in topicos}
    pontos = {}
    for tipo, sinais in VERSOES[versao].items():
        pontos[tipo] = (
            PESO_DESCRICAO * sum(1 for _ in sinais.descricao.finditer(descricao or ""))
            + PESO_TOPICOS * len(sinais.topicos & topicos)
            + PESO_README * bool(sinais.readme.search(readme or ""))
        )
    return pontos


def classificar(descricao: str, topicos: Iterable[str], readme: str, versao: str = VERSAO_ATUAL) -> Classificacao:
    pontos = pontuar(descricao, topicos, readme, versao)
    melhor = max(PRIORIDADE, key=lambda tipo: (pontos[tipo], -PRIORIDADE.index(tipo)))
    return Classificacao(melhor, pontos)
