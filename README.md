# Lab03 - Mineração de Métricas DORA

Pipeline que coleta dados públicos de repositórios open-source no GitHub (releases,
commits e workflow runs do GitHub Actions) e calcula aproximações das métricas DORA.

## Requisitos

- Python 3.11
- Um token pessoal do GitHub em um arquivo .env

## Instalação

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows (PowerShell): .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Execução

O token é lido da variável de ambiente `GITHUB_TOKEN` e nunca deve ser commitado
(`.env`, `cache/` e arquivos de token estão no `.gitignore`). A forma mais simples é
criar um arquivo `.env` ao lado do `config.yaml`, que o pipeline carrega sozinho:

```bash
cp .env.example .env   # e edite o valor de GITHUB_TOKEN
python -m pipeline --config config.yaml
```

Também é possível exportar a variável no shell; ela tem prioridade sobre o `.env`:

```bash
# Linux/macOS
export GITHUB_TOKEN=ghp_...
# Windows (PowerShell)
$env:GITHUB_TOKEN = "ghp_..."
```

Opções:

| Opção | Descrição |
|---|---|
| `--config CAMINHO` | Arquivo de configuração (obrigatório). |
| `--etapas ...` | Executa só algumas etapas, entre `coleta`, `metricas` e `analise` (padrão: todas). Só a `coleta` exige o token. |
| `-v`, `--verbose` | Log detalhado. |

Se a execução for interrompida (rate limit, queda de rede, `Ctrl+C`), basta rodar o
mesmo comando de novo: as respostas da API ficam em cache em `cache/`.

## Configuração (`config.yaml`)

| Seção | Conteúdo |
|---|---|
| `janela` | Início e fim da janela de observação de 12 meses (UTC, datas inclusivas). |
| `selecao` | Faixas de estrelas da busca de candidatos e tamanho da amostra final. |
| `criterios_inclusao` | Mínimo de releases (5) e de workflow runs válidos (50) na janela. |
| `workflow_runs` | Evento considerado (`push`) e quais `conclusion` contam como sucesso/falha; as demais são ignoradas. |
| `metricas` | Parâmetros das métricas (ex.: janela de 7 dias da release corretiva). |
| `coleta` | Pasta de cache, tentativas e backoff para erros temporários. |
| `validacao_manual` | Semente e tamanhos da amostra-ouro. |
| `saida` | Pasta dos CSVs gerados. |

Caminhos relativos são resolvidos a partir da pasta do `config.yaml`.

## Estrutura

```
pipeline/   ponto de entrada (python -m pipeline) e leitura do config/token
coleta/     acesso à API do GitHub, cache, rate limit e funil de seleção
metricas/   funções puras de cálculo das métricas DORA
analise/    análise estatística das RQs
tests/      testes com pytest
```

## Testes

```bash
pytest --cov=metricas --cov-report=term-missing
```

O workflow [`.github/workflows/testes.yml`](.github/workflows/testes.yml) roda os testes no
GitHub Actions a cada push e pull request, e falha se a cobertura do módulo `metricas`
ficar abaixo de 80% (`--cov-fail-under=80`).
