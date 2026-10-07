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

O comando roda as etapas em sequência: a **coleta** grava os dados brutos em
`dados/brutos/` e a etapa de **métricas** calcula, a partir deles, `dados/metricas.csv`.
A etapa de análise ainda não está implementada (Sprint 03).

Se a execução for interrompida (rate limit, queda de rede, `Ctrl+C`), basta rodar o
mesmo comando de novo: as respostas da API ficam em cache em `cache/api.sqlite`.

A coleta de 100 repositórios leva algumas horas. Para rodá-la em segundo plano no macOS
ou Linux, gravando o log em arquivo e sem o computador dormir (macOS):

```bash
caffeinate -i nohup python -m pipeline --config config.yaml > coleta.log 2>&1 &
tail -f coleta.log
```

### Cliente HTTP (`coleta/cliente.py`)

Todo acesso à API passa por `ClienteGitHub`, implementado só com `requests`:

- **Cache e retomada:** cada página de resposta é gravada no SQLite assim que chega,
  com a URL (parâmetros ordenados) como chave. Erros definitivos (404, 409, 410, 451)
  também ficam em cache, para não serem repetidos. O corpo é gravado em JSON
  comprimido (zlib), o que reduz o cache cerca de 10 vezes. Para forçar uma nova
  coleta, apague `cache/api.sqlite`.
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

Os **candidatos** são todos os repositórios que podem ser sorteados para a amostra.
Eles vêm da busca do GitHub, feita por faixa de estrelas (`selecao.faixas_estrelas`),
sem forks nem repositórios arquivados (`selecao.filtros_busca`).

**O problema do teto de 1.000.** A busca do GitHub devolve no máximo 1.000 resultados
por consulta, sempre os de mais estrelas. A faixa "1.000 a 2.000 estrelas" tem cerca de
29 mil repositórios, então uma única consulta traria só os 1.000 maiores (de ~1.940 a
2.000 estrelas). Um repositório com 1.100 estrelas nunca entraria na lista.

**A solução: dividir a faixa em pedaços menores.** Quando uma consulta passa de 1.000
resultados, a faixa é dividida ao meio, e cada metade é consultada de novo. Isso se
repete até cada pedaço (chamado de *subintervalo*) ter no máximo 1.000 repositórios.
Exemplo:

```
1000..2000  → 29.000 resultados, passa de 1.000 → divide
├── 1000..1500 → 20.000, passa de 1.000 → divide
│   ├── 1000..1250 → ...
│   └── ...
└── 1501..2000 → ...
    └── ... até cada pedaço ter no máximo 1.000
```

Assim vêm **todos** os repositórios de cada faixa, e qualquer um deles pode ser sorteado.

A busca atual trouxe **60.043 candidatos** (todos os repositórios com 1.000 estrelas ou
mais, sem forks nem arquivados). Esses repositórios são apenas **listados**: de cada um
vêm só os dados que a própria busca devolve (nome, estrelas, linguagem, criação, branch
principal). Releases, commits e workflow runs só são coletados dos candidatos avaliados
no funil e da amostra.

**Por que listar todos.** O enunciado pede para fatiar a busca para obter mais
candidatos, mas não exige todos. Listar todos foi decisão do grupo: com só os 1.000
maiores de cada faixa, faixas inteiras de popularidade ficariam sem candidatos (por
exemplo, nenhum repositório entre 1.000 e 1.940 estrelas), o que distorceria a amostra
e a comparação por popularidade da RQ 06. Pegar uma parte de cada subintervalo também
resolveria; a lista completa foi escolhida por ser mais simples de justificar e porque
a busca é feita uma única vez.

**A busca é feita uma única vez** e fica salva em dois arquivos, que vão para o git:

| Arquivo | O que tem |
|---|---|
| `dados/candidatos.csv` | A lista de candidatos: uma linha por repositório, com nome, faixa, subintervalo, estrelas, linguagem, data de criação, branch principal, link e data da busca. |
| `dados/candidatos_faixas.csv` | Uma linha por subintervalo consultado: a faixa, a consulta usada, quantos repositórios existiam (`disponiveis`) e quantos vieram (`obtidos`). Se `obtidos` for igual a `disponiveis` em todas as linhas, nenhum repositório ficou de fora. |

Nas próximas execuções, o pipeline usa esses arquivos e **não busca de novo**. Por isso
a amostra não muda com o tempo (mesmo que os repositórios ganhem ou percam estrelas) e
todos usam a mesma lista, inclusive o grupo que for replicar o trabalho. As estrelas
registradas são as do dia da busca.

- **Para refazer a busca**, apague `dados/candidatos.csv` e `dados/candidatos_faixas.csv`.
- Se as faixas ou os filtros do `config.yaml` mudarem sem apagar os arquivos, o log avisa.

### 2. Ordem de avaliação e amostra

A ordem de avaliação é aleatória e reproduzível: os candidatos são ordenados pelo
hash SHA-256 de `selecao.semente` + nome do repositório. Com a mesma lista e a mesma
semente, a ordem (e portanto a amostra) é sempre a mesma. Como a posição de cada
repositório depende só do próprio nome, se a busca for refeita e alguns candidatos
entrarem ou saírem, os demais mantêm a ordem relativa.

**Por que sortear.** O enunciado deixa a definição da amostra com o grupo. Milhares
de candidatos passam nos critérios de inclusão, e só queremos 100 (depois 300). Sem
uma ordem aleatória, a escolha cairia sempre nos primeiros da lista (que vem ordenada
por estrelas) e a amostra teria só os mais populares. Avaliar numa ordem aleatória e
parar nos primeiros N aprovados equivale a sortear N entre todos os que passam nos
critérios, sem precisar avaliar os 60 mil.

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
  página do cabeçalho `Link`). Em repositórios muito grandes a API se recusa a listar
  os contribuidores; nesse caso o campo fica vazio.
- **Releases:** todas, com `draft`, `prerelease`, `published_at`, `tag_name` e link.
- **Tags** (variante da RQ 07): pela GraphQL, 100 por consulta, já com as datas do commit
  apontado (no REST seria uma chamada por tag). A data usada para ordenar e situar a tag
  na janela é a data de autor do commit, coerente com a regra `commit.author.date`.
- **Commits entre releases:** para cada item publicado na janela, o compare com o item
  anterior (que pode estar fora da janela), em três cadeias: `release` (definição
  principal), `release_prerelease` e `tag` (variantes da RQ 07). Pares repetidos entre
  cadeias são consultados uma vez. É feito pela GraphQL (`ref.compare`), 5 compares por
  consulta e todos os commits paginados de 100 em 100, com SHA, `commit.author.date` e a
  mensagem completa. Tag apagada ou renomeada vira status `404` e é contada.
  A GraphQL para em 1.000 commits por compare; quando o total informado é maior, o par
  é refeito pelo compare do REST, paginado. Se o REST recusar o par (por exemplo, 404
  "No common ancestor", quando o projeto mantém linhas de versão com históricos
  separados), ele recebe esse status e fica fora do lead time, como os demais 404.
- **Workflow runs:** `event = push` no default branch, janela dividida em meses. Um mês
  com mais de 1.000 runs (teto da API com filtros) é dividido ao meio até caber; se nem
  um dia couber, ele fica marcado como truncado em `runs_intervalos.csv`.

Todas as datas são gravadas em UTC (a GraphQL devolve o fuso do autor do commit, que é
convertido).

### Desempenho

Medido em execuções de teste com 3 repositórios, sobre o cache da API:

| Ponto | Antes | Depois |
|---|---|---|
| Tags (`astral-sh/ruff`, 431 tags) | REST: ~440 chamadas, ~170 s | GraphQL: 5 chamadas, ~3 s |
| Commits entre releases (3 repositórios) | REST: 132 chamadas, ~230 s, ~150 MB (o REST traz o diff dos arquivos) | GraphQL: 35 chamadas, ~60 s, 16 MB, com os mesmos commits, datas e mensagens |
| Reexecução | — | 0 chamadas, ~2 s (tudo do cache) |
| Busca | Refeita a cada execução sem cache | Feita uma vez (~37 min para os 60.043 candidatos, em 90 consultas, por causa do limite de 30 buscas por minuto) e salva em `dados/candidatos.csv` |

O que mais pesa agora são os workflow runs: só existem no REST, cada página traz no
máximo 100 runs e leva ~3 s para o GitHub gerar. O tempo de uma coleta depende de
quantos repositórios muito ativos forem sorteados.

### Arquivos gerados em `dados/brutos/`

Regenerados a cada execução a partir do cache. Só os três arquivos do funil
(`faixas_busca.csv`, `funil.csv` e `funil_resumo.csv`, ~3 MB no total) vão para o git,
porque entram na Metodologia; os demais são grandes e não são versionados.

| Arquivo | Conteúdo |
|---|---|
| `faixas_busca.csv` | Uma linha por subintervalo da busca: faixa, consulta, total disponível e quantos foram obtidos. |
| `funil.csv` | Um candidato por linha, com a situação (`incluido` ou o motivo do descarte). |
| `funil_resumo.csv` | Quantos repositórios restaram após cada etapa do funil. |
| `repositorios.csv` | Metadados da amostra: estrelas, linguagem, criação, contribuidores, default branch. |
| `releases.csv` | Todas as releases, com `draft`, `prerelease`, `publicada_em` e link. |
| `tags.csv` | Tags com as datas de autor e de committer do commit apontado. |
| `compares.csv` | Item de cada cadeia publicado na janela, o anterior, o status do compare (`ok`, `primeira` ou o HTTP do erro, ex.: `404`), a divergência (`ahead`, `behind`...) e o total de commits informado pelo GitHub, para conferir a paginação. |
| `commits.csv` | Commits de cada compare: SHA, `commit.author.date`, título e mensagem completa (usada na heurística de release corretiva). |
| `runs.csv` | Workflow runs com workflow, `conclusion`, `run_started_at` e `updated_at`. |
| `runs_intervalos.csv` | Consultas de runs feitas, com o `total_count` e se o intervalo ficou truncado. |

## Métricas (`dados/metricas.csv`)

A etapa de métricas lê `dados/brutos/` e grava `dados/metricas.csv`, versionado no git,
com uma linha por repositório da amostra: os metadados de `repositorios.csv` mais as
métricas abaixo, na definição principal (release como deploy, lead time (a), CFR (a)).
As funções de cálculo ficam em `metricas/` e têm testes com os exemplos do enunciado.

| Coluna | Unidade | Como é calculada |
|---|---|---|
| `releases_janela` | releases | Releases publicadas na janela (`draft = false`, sem pré-releases). |
| `deploys_por_semana` | releases/semana | `releases_janela` ÷ semanas da janela (≈ 52,1). |
| `lead_time_release_horas` | horas | (a) Mediana, entre as releases, de publicação − commit mais antigo incluído. |
| `lead_time_commit_horas` | horas | (b) Mediana de publicação − data de cada commit, de todas as releases. |
| `releases_lead_time` | releases | Releases usadas no lead time. |
| `releases_primeira` | releases | Primeira release da história (sem anterior): fora do lead time. |
| `releases_sem_commits` | releases | Releases sem commits novos em relação à anterior. |
| `releases_compare_erro` | releases | Releases ignoradas no lead time porque o compare falhou (ex.: 404). |
| `commits_data_futura` | commits | Commits com data de autor posterior à release, ignorados (rebase, cherry-pick). |
| `cfr_ci` | proporção (0–1) | (a) Runs com falha ÷ (falhas + sucessos); `cancelled`, `skipped` etc. não entram. |
| `runs_falha`, `runs_sucesso`, `runs_ignorados` | runs | Contagens usadas no CFR. |
| `recuperacao_horas` | horas | Mediana dos episódios de falha de todos os workflows: da primeira falha após um sucesso (`run_started_at`) ao próximo sucesso do mesmo workflow (`updated_at`). |
| `episodios_recuperados`, `episodios_censurados` | episódios | Episódios encerrados e não encerrados até o fim da janela. |
| `proporcao_censurados` | proporção (0–1) | Censurados ÷ total de episódios. |
| `classe_frequencia`, `classe_lead_time`, `classe_cfr`, `classe_recuperacao` | Elite/High/Medium/Low | Cortes da tabela de referência do enunciado. |
| `classe_geral` | Elite/High/Medium/Low | Mediana das notas (Elite = 4 … Low = 1), arredondada para baixo. |

Decisões adotadas onde o enunciado não define:

- Falhas antes do primeiro sucesso de um workflow não abrem episódio de recuperação,
  pois o início real da falha é desconhecido.
- Um repositório sem nenhuma falha de CI não tem tempo de recuperação; nesse caso a
  classe geral é a mediana das métricas disponíveis (três em vez de quatro).
- Runs sem `run_started_at` usam o `created_at` como início.

O log da etapa mostra quantas releases foram ignoradas por erro no compare e a
distribuição da classificação geral. Para recalcular só as métricas, sem acessar a API:

```bash
python -m pipeline --config config.yaml --etapas metricas
```

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
