# Lab03 - Mineração de Métricas DORA

Pipeline que coleta dados públicos de repositórios open-source no GitHub (releases,
commits e workflow runs do GitHub Actions) e calcula aproximações das métricas DORA.

## Requisitos

- Python 3.12
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
mesmo comando de novo: as respostas da API ficam em cache em `cache/api.sqlite`.

### Cliente HTTP (`coleta/cliente.py`)

Todo acesso à API passa por `ClienteGitHub`, implementado só com `requests`:

- **Cache e retomada:** cada página de resposta é gravada no SQLite assim que chega,
  com a URL (parâmetros ordenados) como chave. Erros definitivos (404, 409, 410, 451)
  também ficam em cache, para não serem repetidos. Para forçar uma nova coleta,
  apague `cache/api.sqlite`.
- **Rate limit:** lê `X-RateLimit-Remaining`/`X-RateLimit-Reset` de cada resposta e,
  quando a cota de um recurso (`core`, `search`...) chega a zero, pausa até a
  renovação. Respostas 403/429 de limite secundário respeitam `Retry-After` (ou
  esperam 60 s).
- **Erros temporários:** respostas 5xx e falhas de rede são repetidas com backoff
  exponencial (1 s, 2 s, 4 s, ...), até `coleta.max_tentativas`.
- **Paginação:** `paginar()` segue o cabeçalho `Link` (`rel="next"`) até a última página.
- **GraphQL:** `graphql(consulta, variaveis)` faz o POST em `/graphql` com o mesmo
  controle de cota e backoff; a chave do cache é o hash da consulta com as variáveis.
  É usado em dois pontos:
  - tags: 100 por consulta já com a data do commit (no REST seria uma chamada por tag);
  - commits entre releases (`ref.compare`): 5 compares por consulta, paginados de 100
    em 100, só com SHA, `authoredDate` (= `commit.author.date`) e mensagem. O compare
    do REST traz também o diff dos arquivos (~1 MB por chamada), que nenhuma RQ usa.
    Os dois devolvem os mesmos commits e datas; uma tag inexistente vira status `404`.

```python
from coleta.cliente import ClienteGitHub

with ClienteGitHub.de_config(config, token) as cliente:
    releases = list(cliente.paginar(f"/repos/{dono}/{repo}/releases", {"per_page": 100}))
    runs = cliente.paginar(f"/repos/{dono}/{repo}/actions/runs",
                           {"branch": "main", "event": "push", "per_page": 100},
                           chave_itens="workflow_runs")
```

## Configuração (`config.yaml`)

| Seção | Conteúdo |
|---|---|
| `janela` | Início e fim da janela de observação de 12 meses (UTC, datas inclusivas). |
| `selecao` | Faixas de estrelas e filtros da busca, arquivo onde a lista de candidatos fica salva (`arquivo_candidatos`), semente da ordem de avaliação e tamanho da amostra final. |
| `criterios_inclusao` | Mínimo de releases (5) e de workflow runs válidos (50) na janela. |
| `workflow_runs` | Evento considerado (`push`) e quais `conclusion` contam como sucesso/falha; as demais são ignoradas. |
| `metricas` | Parâmetros das métricas (ex.: janela de 7 dias da release corretiva). |
| `coleta` | Pasta de cache, tentativas e backoff para erros temporários. |
| `validacao_manual` | Semente e tamanhos da amostra-ouro. |
| `saida` | Pasta dos CSVs gerados. |

Caminhos relativos são resolvidos a partir da pasta do `config.yaml`.

## Coleta e funil de seleção

### 1. Lista de candidatos (salva e reaproveitada)

Os candidatos são os repositórios devolvidos pela busca do GitHub
(`/search/repositories`). Como cada consulta devolve no máximo 1.000 resultados,
a busca é feita uma vez por faixa de estrelas (`selecao.faixas_estrelas`), com os
filtros `selecao.filtros_busca` (`fork:false archived:false`), em ordem decrescente
de estrelas. Repositórios repetidos entre faixas vizinhas são unificados.

A busca é feita **uma única vez** e o resultado fica salvo em dois arquivos versionados
no repositório:

| Arquivo | Conteúdo |
|---|---|
| `dados/candidatos.csv` | Um candidato por linha: nome, faixa, estrelas, linguagem, data de criação, default branch, link e a data da busca (`buscado_em`). |
| `dados/candidatos_faixas.csv` | Uma linha por faixa: a consulta usada, quantos repositórios a busca encontrou (`disponiveis`) e quantos vieram (`obtidos`, no máximo 1.000). |

Busca atual, feita em 06/10/2026:

| Faixa de estrelas | Disponíveis | Obtidos |
|---|---|---|
| 1.000 a 2.000 | 29.078 | 1.000 |
| 2.000 a 5.000 | 19.115 | 1.000 |
| 5.000 a 10.000 | 6.557 | 1.000 |
| 10.000 a 50.000 | 4.822 | 1.000 |
| 50.000 ou mais | 491 | 491 |
| **Total** | **60.063** | **4.491 candidatos** |

Nas execuções seguintes o pipeline lê `dados/candidatos.csv` e **não refaz a busca**.
Assim a amostra não muda quando os repositórios ganham ou perdem estrelas, todos os
integrantes e o grupo replicador usam a mesma lista, e a Metodologia pode citar a data
da busca. Estrelas e linguagem nos CSVs são as do dia da busca.

- **Para refazer a busca**, apague `dados/candidatos.csv` e `dados/candidatos_faixas.csv`.
- Se `selecao.faixas_estrelas` ou `selecao.filtros_busca` mudarem e os arquivos não forem
  apagados, o log avisa que eles são de uma busca com outros parâmetros.

### 2. Ordem de avaliação e amostra

A ordem de avaliação é aleatória e reproduzível: os candidatos são ordenados pelo
hash SHA-256 de `selecao.semente` + nome do repositório. Com a mesma lista e a mesma
semente, a ordem (e portanto a amostra) é sempre a mesma. Como a posição de cada
repositório depende só do próprio nome, se a busca for refeita e alguns candidatos
entrarem ou saírem, os demais mantêm a ordem relativa.

Os candidatos são avaliados nessa ordem até a amostra atingir `selecao.tamanho_amostra`
(100 na S01, ≥ 300 na S02). Aumentar o tamanho não troca quem já entrou: a avaliação
continua do ponto seguinte da mesma ordem. Os candidatos que sobram entram no funil
como `nao_avaliado`. Para outra amostra, mude a semente (decisão do grupo, registrada
na Metodologia).

### 3. Funil de seleção

Cada candidato passa pelos filtros do mais barato ao mais caro e para no primeiro
em que reprovar; o motivo fica em `funil.csv`:

| Etapa | Critério | Motivo do descarte |
|---|---|---|
| Acesso | O repositório responde na API (não foi apagado ou bloqueado). | `erro_api` |
| Usa Actions | `/actions/workflows` com `total_count > 0`. | `sem_actions` |
| Releases | ≥ 5 releases publicadas na janela (`draft = false`, sem pré-releases). | `poucas_releases` |
| Workflow runs | ≥ 50 runs válidos na janela: `event = push` no default branch, `conclusion` de sucesso ou falha. A contagem é exata, feita sobre os runs coletados (o `total_count` com filtro `status` da API subconta). | `poucos_runs` |

### 4. Coleta de cada repositório da amostra

- **Metadados:** estrelas, linguagem, data de criação e default branch vêm da busca; o
  nº de contribuidores vem de `/contributors?per_page=1&anon=true` (número da última
  página do cabeçalho `Link`).
- **Releases:** todas, com `draft`, `prerelease`, `published_at`, `tag_name` e link.
- **Tags** (variante da RQ 07): pela GraphQL, 100 por consulta, já com as datas do commit
  apontado (no REST seria uma chamada por tag).
- **Commits entre releases:** para cada item publicado na janela, o compare com o item
  anterior (que pode estar fora da janela), em três cadeias: `release` (definição
  principal), `release_prerelease` e `tag` (variantes da RQ 07). Pares repetidos entre
  cadeias são consultados uma vez. É feito pela GraphQL (`ref.compare`), 5 compares por
  consulta e todos os commits paginados de 100 em 100, com SHA, `commit.author.date` e a
  mensagem completa. Tag apagada ou renomeada vira status `404` e é contada.
- **Workflow runs:** `event = push` no default branch, janela dividida em meses. Um mês
  com mais de 1.000 runs (teto da API com filtros) é dividido ao meio até caber; se nem
  um dia couber, ele fica marcado como truncado em `runs_intervalos.csv`.

### Desempenho

Medido em execuções de teste com 3 repositórios, sobre o cache da API:

| Ponto | Antes | Depois |
|---|---|---|
| Tags (`astral-sh/ruff`, 431 tags) | REST: ~440 chamadas, ~170 s | GraphQL: 5 chamadas, ~3 s |
| Commits entre releases (3 repositórios) | REST: 132 chamadas, ~230 s, ~150 MB (o REST traz o diff dos arquivos) | GraphQL: 35 chamadas, ~60 s, 16 MB, com os mesmos commits, datas e mensagens |
| Reexecução | — | 0 chamadas, ~2 s (tudo do cache) |
| Busca | ~2,5 min a cada execução sem cache | Feita uma vez e salva em `dados/candidatos.csv` |

O que mais pesa agora são os workflow runs: só existem no REST, cada página traz no
máximo 100 runs e leva ~3 s para o GitHub gerar. O tempo de uma coleta depende de
quantos repositórios muito ativos forem sorteados.

### Arquivos gerados em `dados/brutos/`

Regenerados a cada execução a partir do cache (não versionados):

| Arquivo | Conteúdo |
|---|---|
| `faixas_busca.csv` | Por faixa: consulta, total disponível na busca e quantos foram obtidos. |
| `funil.csv` | Um candidato por linha, com a situação (`incluido` ou o motivo do descarte). |
| `funil_resumo.csv` | Quantos repositórios restaram após cada etapa do funil. |
| `repositorios.csv` | Metadados da amostra: estrelas, linguagem, criação, contribuidores, default branch. |
| `releases.csv` | Todas as releases, com `draft`, `prerelease`, `publicada_em` e link. |
| `tags.csv` | Tags com as datas de autor e de committer do commit apontado. |
| `compares.csv` | Item de cada cadeia publicado na janela, o anterior, o status do compare (`ok`, `primeira` ou o HTTP do erro, ex.: `404`), a divergência (`ahead`, `behind`...) e o total de commits informado pelo GitHub, para conferir a paginação. |
| `commits.csv` | Commits de cada compare: SHA, `commit.author.date`, título e mensagem completa (usada na heurística de release corretiva). |
| `runs.csv` | Workflow runs com workflow, `conclusion`, `run_started_at` e `updated_at`. |
| `runs_intervalos.csv` | Consultas de runs feitas, com o `total_count` e se o intervalo ficou truncado. |

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
