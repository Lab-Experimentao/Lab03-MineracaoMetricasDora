# Dicionário de dados

Colunas de todos os CSVs gerados pelo pipeline (`python -m pipeline --config config.yaml`).

Convenções válidas para todos os arquivos:

- **Codificação:** UTF-8, separador vírgula, cabeçalho na primeira linha.
- **Datas:** ISO 8601 em UTC (ex.: `2026-03-15T14:02:11+00:00`). A GraphQL devolve o fuso do
  autor do commit, que é convertido para UTC na coleta.
- **Booleanos:** `1` (verdadeiro) ou `0` (falso).
- **Valor ausente:** célula vazia (ex.: métrica sem dados suficientes, campo que a API não devolveu).
- **Janela de observação:** `janela.inicio` a `janela.fim` do `config.yaml` (2025-10-01 a
  2026-09-30, ambas inclusivas). Semanas da janela = dias ÷ 7 ≈ 52,1.
- **`repositorio`:** nome completo `dono/nome` (`full_name` da API). É a chave que liga os arquivos.

Tipos: `texto`, `inteiro`, `real`, `data-hora`, `data`, `booleano`.

## Arquivo principal

### `dados/metricas.csv`

Uma linha por repositório da amostra final. É o dataset usado nas análises. Traz as colunas de
`repositorios.csv` (ver abaixo) seguidas das métricas na definição principal (C1): release
como deploy, lead time (a) e CFR (a).

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio`, `url`, `estrelas`, `linguagem`, `criado_em`, `contribuidores`, `branch_padrao`, `faixa` | — | — | Iguais a `brutos/repositorios.csv`. |
| `releases_janela` | inteiro | releases | Releases publicadas na janela com `draft = false` e `prerelease = false` (linhas da cadeia `release` em `compares.csv`). |
| `deploys_por_semana` | real | releases/semana | RQ 01: `releases_janela` ÷ semanas da janela (≈ 52,1). |
| `lead_time_release_horas` | real | horas | RQ 02 (a): para cada release, `published_at` − `commit.author.date` do commit mais antigo do compare com a release anterior; mediana entre as releases. |
| `lead_time_commit_horas` | real | horas | RQ 02 (b): `published_at` da release − `commit.author.date` de cada commit; mediana de todos os commits de todas as releases. |
| `releases_lead_time` | inteiro | releases | Releases que entraram no lead time (com anterior, compare ok e ao menos um commit). |
| `releases_primeira` | inteiro | releases | Releases sem release anterior na história do repositório; ficam fora do lead time. |
| `releases_sem_commits` | inteiro | releases | Releases cujo compare com a anterior não trouxe commits válidos; ficam fora do lead time. |
| `releases_compare_erro` | inteiro | releases | Releases ignoradas no lead time porque o compare falhou (ex.: 404 por tag apagada ou sem ancestral comum). |
| `commits_data_futura` | inteiro | commits | Commits com `commit.author.date` posterior a `published_at` da release (rebase, cherry-pick); ignorados. |
| `cfr_ci` | real | proporção (0–1) | RQ 03 (a): `runs_falha` ÷ (`runs_falha` + `runs_sucesso`). Vazio se não há runs válidos. |
| `runs_falha` | inteiro | runs | Runs com `conclusion` em `failure`, `timed_out` ou `startup_failure`. |
| `runs_sucesso` | inteiro | runs | Runs com `conclusion = success`. |
| `runs_ignorados` | inteiro | runs | Demais runs (`cancelled`, `skipped`, `neutral`, `action_required`, `stale`, vazio); não entram em nenhum cálculo. |
| `recuperacao_horas` | real | horas | RQ 04: mediana dos episódios recuperados de todos os workflows. Episódio: da primeira falha após um sucesso (`run_started_at`, ou `created_at` se ausente) ao próximo sucesso do mesmo `workflow_id` (`updated_at`). Vazio se não há episódio recuperado. |
| `episodios_recuperados` | inteiro | episódios | Episódios de falha encerrados por um sucesso dentro da janela. |
| `episodios_censurados` | inteiro | episódios | Episódios sem sucesso posterior até o fim da janela (censura). |
| `proporcao_censurados` | real | proporção (0–1) | `episodios_censurados` ÷ (`episodios_recuperados` + `episodios_censurados`). Vazio se não há episódios. |
| `classe_frequencia` | texto | Elite/High/Medium/Low | Corte de `deploys_por_semana`: ≥ 7 Elite; ≥ 1 High; ≥ 1/mês Medium; abaixo disso Low. |
| `classe_lead_time` | texto | Elite/High/Medium/Low | Corte de `lead_time_release_horas`: < 1 dia Elite; < 1 semana High; < 30 dias Medium; ≥ 30 dias Low. |
| `classe_cfr` | texto | Elite/High/Medium/Low | Corte de `cfr_ci`: ≤ 15% Elite; ≤ 30% High; ≤ 45% Medium; > 45% Low. |
| `classe_recuperacao` | texto | Elite/High/Medium/Low | Corte de `recuperacao_horas`: < 1 h Elite; < 1 dia High; < 1 semana Medium; ≥ 1 semana Low. |
| `classe_geral` | texto | Elite/High/Medium/Low | Notas Elite = 4 … Low = 1 das classes disponíveis; mediana arredondada para baixo. Sem tempo de recuperação, usa as três restantes. |

## Dados brutos da coleta (`dados/brutos/`)

Regenerados a partir do cache da API a cada execução da etapa de coleta.

### `repositorios.csv`

Uma linha por repositório da amostra final.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | `full_name` da busca (`GET /search/repositories`). |
| `url` | texto | — | `html_url` da busca. |
| `estrelas` | inteiro | estrelas | `stargazers_count` no dia da busca (`buscado_em` de `candidatos.csv`). |
| `linguagem` | texto | — | `language` (linguagem principal detectada pelo GitHub); vazio se não houver. |
| `criado_em` | data-hora | — | `created_at` do repositório. |
| `contribuidores` | inteiro | pessoas | Número da última página de `GET /repos/{repo}/contributors?per_page=1&anon=true` (cabeçalho `Link`). Vazio quando a API recusa a lista em repositórios muito grandes. |
| `branch_padrao` | texto | — | `default_branch`. |
| `faixa` | texto | — | Faixa de estrelas do `config.yaml` em que o repositório foi encontrado (ex.: `1000..2000`, `>=50000`). |

### `releases.csv`

Todas as releases de cada repositório da amostra, dentro e fora da janela.
Origem: `GET /repos/{repo}/releases`.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | Repositório. |
| `tag` | texto | — | `tag_name`. |
| `publicada_em` | data-hora | — | `published_at`; vazio em drafts. |
| `draft` | booleano | — | `draft`. |
| `prerelease` | booleano | — | `prerelease`. |
| `url` | texto | — | `html_url` (página da release no GitHub). |

### `tags.csv`

Todas as tags de cada repositório (variante "tag" da RQ 07). Origem: GraphQL
`repository.refs(refPrefix: "refs/tags/")`, com o commit apontado (tags anotadas são seguidas até o commit).

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | Repositório. |
| `nome` | texto | — | `name` da ref. |
| `sha` | texto | — | `oid` do commit apontado; vazio se a tag não aponta para um commit. |
| `data_autor` | data-hora | — | `author.date` do commit apontado. É a data usada para situar a tag na janela. |
| `data_committer` | data-hora | — | `committer.date` do commit apontado. |

### `compares.csv`

Uma linha por item publicado na janela, em cada uma das três cadeias de deploy, pareado com o
item imediatamente anterior da mesma cadeia (que pode estar fora da janela).

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | Repositório. |
| `cadeia` | texto | — | `release` (definição principal: `draft = false`, sem pré-releases), `release_prerelease` (inclui pré-releases) ou `tag`. |
| `tag` | texto | — | Tag do item. |
| `publicada_em` | data-hora | — | `published_at` (releases) ou `data_autor` (tags). |
| `tag_anterior` | texto | — | Tag do item anterior da cadeia; vazio se é o primeiro da história. |
| `status` | texto | — | `ok`; `primeira` (sem anterior); ou o código HTTP do erro do compare (ex.: `404`). |
| `n_commits` | inteiro | commits | Commits obtidos no compare (linhas em `commits.csv`). |
| `total_commits_api` | inteiro | commits | Total informado pelo GitHub (`aheadBy` na GraphQL, `ahead_by` no REST), para conferir a paginação. |
| `divergencia` | texto | — | `status` do compare no GitHub: `ahead`, `behind`, `diverged` ou `identical`. |

### `commits.csv`

Commits incluídos em cada par de `compares.csv` com `status = ok`. Origem: GraphQL
`ref.compare(headRef).commits`, ou o REST `GET /repos/{repo}/compare/{base}...{head}` paginado
quando o compare passa de 1.000 commits. Pares repetidos entre cadeias aparecem uma vez.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | Repositório. |
| `tag_anterior` | texto | — | Base do compare. |
| `tag` | texto | — | Head do compare (a release que inclui o commit). |
| `sha` | texto | — | `oid` / `sha` do commit. |
| `data_autor` | data-hora | — | `commit.author.date` (`authoredDate` na GraphQL). |
| `titulo` | texto | — | Primeira linha da mensagem. |
| `mensagem` | texto | — | Mensagem completa do commit (usada na heurística de release corretiva). |

### `runs.csv`

Workflow runs do default branch criados na janela, com `event = push`. Origem:
`GET /repos/{repo}/actions/runs?branch={default_branch}&event=push&created=AAAA-MM-DD..AAAA-MM-DD`,
consultado mês a mês.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | Repositório. |
| `id` | inteiro | — | `id` do run. |
| `workflow_id` | inteiro | — | `workflow_id`; agrupa os runs no tempo de recuperação. |
| `workflow_nome` | texto | — | `name` do workflow. |
| `conclusao` | texto | — | `conclusion`; vazio em runs em andamento. |
| `status` | texto | — | `status` (`completed`, `in_progress`...). |
| `criado_em` | data-hora | — | `created_at`. |
| `iniciado_em` | data-hora | — | `run_started_at` (início da última tentativa). |
| `atualizado_em` | data-hora | — | `updated_at`; usado como fim do run de sucesso que encerra um episódio. |
| `head_sha` | texto | — | `head_sha` (commit executado). |
| `tentativa` | inteiro | tentativas | `run_attempt`. A listagem devolve só a última tentativa de cada run; `tentativa > 1` indica que o run foi reexecutado sem novo commit. |

### `runs_intervalos.csv`

Uma linha por consulta de runs feita. Um mês com mais de 1.000 runs (teto da API com filtros) é
dividido ao meio até caber.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | Repositório. |
| `inicio` | data | — | Primeiro dia do intervalo consultado (inclusivo). |
| `fim` | data | — | Último dia do intervalo consultado (inclusivo). |
| `total` | inteiro | runs | `total_count` da consulta. |
| `truncado` | booleano | — | `1` se o intervalo é um único dia com mais de 1.000 runs (dados incompletos). |

## Validação manual (`dados/validacao/`)

### `amostra_ouro.csv`

As releases sorteadas para a amostra-ouro: 60 repositórios da amostra final
(`DataFrame.sample(random_state=42)` sobre a lista ordenada por nome) e 5 releases de cada,
sorteadas da mesma forma entre as da cadeia `release` de `compares.csv`.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | Repositório sorteado. |
| `tag` | texto | — | Tag da release sorteada. |
| `tag_anterior` | texto | — | Release imediatamente anterior na cadeia `release` (por data de publicação); vazio se é a primeira da história. |
| `publicada_em` | data-hora | — | `published_at` da release. |
| `url_release` | texto | — | Página da release no GitHub (`html_url`). |
| `url_commits` | texto | — | `https://github.com/{repo}/compare/{tag_anterior}...{tag}`: commits incluídos na release; vazio sem anterior. |

### `rotulagem_<avaliador>.xlsx`

Planilha preenchida por cada avaliador. A aba `instrucoes` explica os critérios.

Aba `repositorios` (uma linha por repositório da amostra-ouro):

| Coluna | Tipo | Valores | Significado |
|---|---|---|---|
| `repositorio` | texto | — | Repositório. |
| `url_repositorio` | texto | — | Página do repositório no GitHub. |
| `tipo_projeto` | texto | `biblioteca/framework`, `aplicação/serviço`, `ferramenta CLI`, `outro` | Tipo do projeto (RQ 06). |
| `entregas_reais` | texto | `sim`, `não`, `incerto` | As releases representam entregas reais ao usuário? |
| `observacoes` | texto | livre | Dúvidas e justificativas. |

Aba `releases` (uma linha por release de `amostra_ouro.csv`):

| Coluna | Tipo | Valores | Significado |
|---|---|---|---|
| `repositorio`, `tag`, `tag_anterior`, `publicada_em`, `url_release`, `url_commits` | — | — | Iguais a `amostra_ouro.csv`. |
| `corretiva` | texto | `sim`, `não` | O objetivo principal da release é corrigir um defeito recente? (RQ 03 b) |
| `observacoes` | texto | livre | Dúvidas e justificativas. |

## Seleção da amostra

### `dados/candidatos.csv`

Lista congelada de candidatos, gerada uma vez pela busca e reaproveitada nas execuções seguintes.
Origem: `GET /search/repositories?q=stars:{faixa} fork:false archived:false`.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | `full_name`. |
| `faixa` | texto | — | Faixa de estrelas do `config.yaml`. |
| `subintervalo` | texto | — | Pedaço da faixa em que a busca o encontrou (a faixa é dividida até cada consulta ter ≤ 1.000 resultados). |
| `estrelas` | inteiro | estrelas | `stargazers_count` no dia da busca. |
| `linguagem` | texto | — | `language`. |
| `criado_em` | data-hora | — | `created_at`. |
| `branch_padrao` | texto | — | `default_branch`. |
| `url` | texto | — | `html_url`. |
| `buscado_em` | data | — | Data em que a busca foi feita. |

### `dados/candidatos_faixas.csv` e `dados/brutos/faixas_busca.csv`

Uma linha por subintervalo consultado na busca. `candidatos_faixas.csv` traz também `buscado_em`.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `faixa` | texto | — | Faixa de estrelas do `config.yaml`. |
| `subintervalo` | texto | — | Pedaço da faixa consultado. |
| `consulta` | texto | — | Parâmetro `q` usado na busca. |
| `disponiveis` | inteiro | repositórios | `total_count` da busca. |
| `obtidos` | inteiro | repositórios | Itens efetivamente recebidos. Igual a `disponiveis` quando nada ficou de fora. |
| `buscado_em` | data | — | Data da busca (só em `candidatos_faixas.csv`). |

### `dados/brutos/funil.csv`

Um candidato por linha, na ordem de avaliação (hash SHA-256 de `semente:nome`). Cada candidato
para no primeiro filtro em que reprova.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | Repositório. |
| `faixa` | texto | — | Faixa de estrelas. |
| `estrelas` | inteiro | estrelas | Estrelas no dia da busca. |
| `situacao` | texto | — | `incluido` ou o motivo do descarte: `nao_avaliado` (a amostra encheu antes), `erro_api`, `sem_actions`, `poucas_releases`, `poucos_runs`. |
| `n_workflows` | inteiro | workflows | `total_count` de `GET /repos/{repo}/actions/workflows`; vazio se não chegou a essa etapa. |
| `n_releases_janela` | inteiro | releases | Releases publicadas na janela (`draft = false`, sem pré-releases); vazio se não chegou a essa etapa. |
| `n_runs_validos` | inteiro | runs | Runs `push` do default branch na janela com `conclusion` de sucesso ou falha; vazio se não chegou a essa etapa. |
| `detalhe` | texto | — | Mensagem do erro, quando `situacao = erro_api`. |

### `dados/brutos/funil_resumo.csv`

Quantos repositórios restam após cada etapa do funil (tabela da Metodologia).

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `etapa` | texto | — | `candidatos`, `avaliados`, `acessiveis_pela_api`, `usam_actions`, `com_min_releases`, `com_min_runs_validos`, `amostra_final`. |
| `restantes` | inteiro | repositórios | Repositórios que seguem após a etapa. |
| `descartados` | inteiro | repositórios | Repositórios descartados na etapa. |
| `motivo_descarte` | texto | — | Valor de `situacao` em `funil.csv` correspondente aos descartados. |
