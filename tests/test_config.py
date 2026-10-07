from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from pipeline.__main__ import main
from pipeline.config import ErroConfig, Janela, carregar_config, obter_token

CONFIG_PROJETO = Path(__file__).resolve().parent.parent / "config.yaml"


@pytest.fixture
def dados_config():
    with CONFIG_PROJETO.open(encoding="utf-8") as arquivo:
        return yaml.safe_load(arquivo)


def _gravar(tmp_path, dados):
    caminho = tmp_path / "config.yaml"
    caminho.write_text(yaml.safe_dump(dados), encoding="utf-8")
    return caminho


def test_config_do_projeto_e_valido():
    config = carregar_config(CONFIG_PROJETO)
    assert config.criterios_inclusao.min_releases == 5
    assert config.criterios_inclusao.min_workflow_runs == 50
    assert config.workflow_runs.evento == "push"
    assert config.workflow_runs.conclusoes_falha == {"failure", "timed_out", "startup_failure"}
    assert config.janela.dias in (365, 366)
    assert config.selecao.semente == 42
    assert config.selecao.filtros_busca == "fork:false archived:false"


def test_caminhos_relativos_ao_config(tmp_path, dados_config):
    config = carregar_config(_gravar(tmp_path, dados_config))
    assert config.coleta.cache_dir == tmp_path.resolve() / "cache"
    assert config.saida_dir == tmp_path.resolve() / "dados"
    assert config.selecao.arquivo_candidatos == tmp_path.resolve() / "dados" / "candidatos.csv"


def test_janela_inclui_ultimo_dia_inteiro():
    janela = Janela(datetime(2025, 1, 1).date(), datetime(2025, 12, 31).date())
    assert janela.contem(datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc))
    assert janela.contem(datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc))
    assert not janela.contem(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc))
    assert not janela.contem(datetime(2024, 12, 31, 23, 59, tzinfo=timezone.utc))
    assert janela.semanas == pytest.approx(52.14, abs=0.01)


def test_janela_rejeita_data_sem_fuso():
    janela = Janela(datetime(2025, 1, 1).date(), datetime(2025, 12, 31).date())
    with pytest.raises(ValueError):
        janela.contem(datetime(2025, 6, 1))


def test_janela_invertida(tmp_path, dados_config):
    dados_config["janela"] = {"inicio": "2026-01-01", "fim": "2025-01-01"}
    with pytest.raises(ErroConfig, match="posterior"):
        carregar_config(_gravar(tmp_path, dados_config))


def test_secao_ausente(tmp_path, dados_config):
    del dados_config["criterios_inclusao"]
    with pytest.raises(ErroConfig, match="criterios_inclusao"):
        carregar_config(_gravar(tmp_path, dados_config))


def test_criterio_invalido(tmp_path, dados_config):
    dados_config["criterios_inclusao"]["min_releases"] = 0
    with pytest.raises(ErroConfig, match="min_releases"):
        carregar_config(_gravar(tmp_path, dados_config))


def test_conclusao_em_sucesso_e_falha(tmp_path, dados_config):
    dados_config["workflow_runs"]["conclusoes_falha"].append("success")
    with pytest.raises(ErroConfig, match="sucesso e falha"):
        carregar_config(_gravar(tmp_path, dados_config))


def test_arquivo_inexistente(tmp_path):
    with pytest.raises(ErroConfig, match="não encontrado"):
        carregar_config(tmp_path / "nao_existe.yaml")


def test_token_lido_do_ambiente(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "  abc123 \n")
    assert obter_token() == "abc123"


def test_token_ausente(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(ErroConfig, match="GITHUB_TOKEN"):
        obter_token()


def test_token_lido_do_arquivo_env(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    arquivo_env = tmp_path / ".env"
    arquivo_env.write_text("GITHUB_TOKEN=do_arquivo\n", encoding="utf-8")
    assert obter_token(arquivo_env) == "do_arquivo"


def test_ambiente_tem_prioridade_sobre_arquivo_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "do_shell")
    arquivo_env = tmp_path / ".env"
    arquivo_env.write_text("GITHUB_TOKEN=do_arquivo\n", encoding="utf-8")
    assert obter_token(arquivo_env) == "do_shell"


def test_arquivo_env_inexistente_e_ignorado(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "abc")
    assert obter_token(tmp_path / ".env") == "abc"


def test_main_le_token_do_env_ao_lado_do_config(tmp_path, dados_config, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    (tmp_path / ".env").write_text("GITHUB_TOKEN=do_arquivo\n", encoding="utf-8")
    tokens = []
    # Sem rede nos testes: a coleta só registra o token recebido.
    monkeypatch.setattr("coleta.etapa.executar", lambda config, token: tokens.append(token))
    assert main(["--config", str(_gravar(tmp_path, dados_config))]) == 0
    assert tokens == ["do_arquivo"]


def test_main_sem_token_falha_na_coleta(tmp_path, dados_config, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert main(["--config", str(_gravar(tmp_path, dados_config))]) == 2


def test_main_sem_coleta_nao_exige_token(tmp_path, dados_config, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    caminho = _gravar(tmp_path, dados_config)
    assert main(["--config", str(caminho), "--etapas", "metricas", "analise"]) == 0
    assert (tmp_path / "dados").is_dir()
