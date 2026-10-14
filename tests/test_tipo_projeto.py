import base64
from contextlib import nullcontext
from pathlib import Path

import pandas as pd
import pytest
import yaml

from coleta.cliente import ErroAPI
from coleta.perfil import MAX_CARACTERES_README, coletar_perfil, decodificar_readme
from metricas.tipo_projeto import APLICACAO, BIBLIOTECA, CLI, OUTRO, VERSAO_ATUAL, VERSOES, classificar, pontuar
from pipeline.config import carregar_config
from tests.falsos import ClienteFalso
from tipo_projeto import etapa
from validacao.tipo_projeto import avaliar

CONFIG_PROJETO = Path(__file__).resolve().parent.parent / "config.yaml"


def readme_api(texto):
    return {"encoding": "base64", "content": base64.b64encode(texto.encode()).decode()}


# ---------------------------------------------------------------- coleta do perfil


def test_coleta_descricao_topicos_e_readme():
    cliente = ClienteFalso({
        "/repos/a/b": [{"description": "Uma biblioteca", "topics": ["python", "library"]}],
        "/repos/a/b/readme": [readme_api("# B\n" + "x" * 10_000)],
    })
    perfil = coletar_perfil(cliente, "a/b")
    assert (perfil.descricao, perfil.topicos) == ("Uma biblioteca", ("python", "library"))
    assert perfil.readme.startswith("# B") and len(perfil.readme) == MAX_CARACTERES_README


def test_repositorio_sem_readme_nem_descricao():
    perfil = coletar_perfil(ClienteFalso({"/repos/a/b": [{"description": None, "topics": []}]}), "a/b")
    assert (perfil.descricao, perfil.topicos, perfil.readme) == ("", (), "")


def test_erro_diferente_de_404_no_readme_propaga():
    cliente = ClienteFalso({"/repos/a/b": [{}], "/repos/a/b/readme": ErroAPI("erro", status=500)})
    with pytest.raises(ErroAPI):
        coletar_perfil(cliente, "a/b")


def test_readme_em_outra_codificacao_vira_vazio():
    assert decodificar_readme({"encoding": "none", "content": "abc"}) == ""
    assert decodificar_readme(None) == ""
    assert decodificar_readme({"encoding": "base64", "content": "@@@"}) == ""


# ---------------------------------------------------------------- heurística


@pytest.mark.parametrize("descricao, topicos, readme, esperado", [
    ("Asynchronous HTTP client library for the JVM", ["java", "netty"], "", BIBLIOTECA),
    ("A Python framework for building APIs", [], "pip install foo", BIBLIOTECA),
    ("Self-hosted password manager", ["php"], "docker run -p 80:80 teampass", APLICACAO),
    ("Yet another matrix client", ["matrix", "electron", "desktop-app"], "", APLICACAO),
    ("A command-line tool to lint your dependencies", ["rust", "cli"], "cargo install cargo-deny", CLI),
    ("GitHub Action for creating GitHub Releases", ["github-actions"], "uses: softprops/action-gh-release@v2", OUTRO),
    ("LaTeX template for USTC thesis", ["latex", "latex-template"], "", OUTRO),
])
def test_classificar(descricao, topicos, readme, esperado):
    assert classificar(descricao, topicos, readme).tipo == esperado


def test_pesos_descricao_topicos_e_readme():
    pontos = pontuar("A library", ["CLI"], "npm install foo")
    assert pontos[BIBLIOTECA] == 3 + 1  # descrição + README
    assert pontos[CLI] == 2  # tópico, sem diferenciar maiúsculas


def test_npm_global_conta_como_cli_e_nao_como_biblioteca():
    pontos = pontuar("", [], "npm install -g foo")
    assert pontos[CLI] == 1 and pontos[BIBLIOTECA] == 0


def test_sem_sinais_vale_o_tipo_mais_comum():
    resultado = classificar("", [], "")
    assert resultado.tipo == APLICACAO and not any(resultado.pontos.values())


# ---------------------------------------------------------------- validação


def test_metricas_por_tipo_e_medias():
    consenso = pd.Series([BIBLIOTECA, BIBLIOTECA, APLICACAO, CLI])
    previsto = pd.Series([BIBLIOTECA, APLICACAO, APLICACAO, CLI])
    tabela = avaliar(consenso, previsto).set_index("classe")
    assert tabela.loc[BIBLIOTECA, ["precisao", "recall"]].tolist() == [1.0, 0.5]
    assert tabela.loc[APLICACAO, ["precisao", "recall"]].tolist() == [0.5, 1.0]
    assert tabela.loc[OUTRO, ["suporte", "previstos", "f1"]].tolist() == [0, 0, 0.0]
    assert tabela.loc["acuracia", "f1"] == 0.75
    assert set(tabela.index) >= {"macro", "ponderada"}


# ---------------------------------------------------------------- etapa


@pytest.fixture
def config(tmp_path):
    with CONFIG_PROJETO.open(encoding="utf-8") as arquivo:
        dados = yaml.safe_load(arquivo)
    caminho = tmp_path / "config.yaml"
    caminho.write_text(yaml.safe_dump(dados), encoding="utf-8")
    config = carregar_config(caminho)
    (config.saida_dir / "validacao").mkdir(parents=True)
    pd.DataFrame({"repositorio": ["a/lib", "b/app", "c/cli"]}).to_csv(config.saida_dir / "metricas.csv", index=False)
    pd.DataFrame({
        "repositorio": ["a/lib", "b/app"], "tipo_projeto": [BIBLIOTECA, CLI],
        "tipo_projeto_regra": ["unanime", "maioria"],
    }).to_csv(config.saida_dir / "validacao" / "consenso_repositorios.csv", index=False)
    return config


ROTAS = {
    "/repos/a/lib": [{"description": "A tiny library", "topics": []}],
    "/repos/b/app": [{"description": "Desktop app for notes", "topics": ["electron"]}],
    "/repos/c/cli": [{"description": "Command-line tool", "topics": ["cli"]}],
}


def test_etapa_coleta_classifica_e_valida(config, monkeypatch):
    cliente = ClienteFalso(ROTAS)
    monkeypatch.setattr(etapa.ClienteGitHub, "de_config", lambda config, token: nullcontext(cliente))
    tokens = []
    etapa.executar(config, lambda: tokens.append("tok") or "tok")
    assert tokens == ["tok"]

    tipos = pd.read_csv(config.saida_dir / etapa.ARQUIVO_TIPOS, keep_default_na=False).set_index("repositorio")
    assert tipos.loc["a/lib", ["tipo_heuristica", "tipo_projeto", "origem"]].tolist() == [BIBLIOTECA, BIBLIOTECA, "consenso"]
    # Na amostra-ouro vale o consenso, mesmo quando a heurística discorda.
    assert tipos.loc["b/app", ["tipo_heuristica", "tipo_projeto"]].tolist() == [APLICACAO, CLI]
    assert tipos.loc["c/cli", ["tipo_projeto", "origem"]].tolist() == [CLI, "heuristica"]

    validacao = pd.read_csv(config.saida_dir / etapa.ARQUIVO_VALIDACAO)
    assert set(validacao["versao"]) == set(VERSOES)
    atual = validacao[validacao["versao"] == VERSAO_ATUAL].set_index("classe")
    assert atual.loc["acuracia", "f1"] == 0.5
    erros = pd.read_csv(config.saida_dir / etapa.ARQUIVO_ERROS)
    assert erros.loc[erros["versao"] == VERSAO_ATUAL, "repositorio"].tolist() == ["b/app"]


def test_etapa_reaproveita_perfis_sem_token(config, monkeypatch):
    cliente = ClienteFalso(ROTAS)
    monkeypatch.setattr(etapa.ClienteGitHub, "de_config", lambda config, token: nullcontext(cliente))
    etapa.executar(config, lambda: "tok")
    chamadas = len(cliente.chamadas)

    def sem_token():
        raise AssertionError("não deveria pedir o token")

    etapa.executar(config, sem_token)
    assert len(cliente.chamadas) == chamadas


def test_etapa_sem_consenso_so_classifica(config, monkeypatch):
    (config.saida_dir / "validacao" / "consenso_repositorios.csv").unlink()
    monkeypatch.setattr(etapa.ClienteGitHub, "de_config", lambda config, token: nullcontext(ClienteFalso(ROTAS)))
    etapa.executar(config, lambda: "tok")
    assert (config.saida_dir / etapa.ARQUIVO_TIPOS).is_file()
    assert not (config.saida_dir / etapa.ARQUIVO_VALIDACAO).exists()


def test_versoes_anteriores_continuam_avaliaveis():
    # A v1 não reconhecia "HTTP client in <linguagem>" e caía no tipo padrão.
    assert classificar("simple HTTP client in Erlang", [], "", versao="v1").tipo == APLICACAO
    assert classificar("simple HTTP client in Erlang", [], "", versao="v2").tipo == BIBLIOTECA
