"""Coleta de dados da API do GitHub (seleção, releases, commits, workflow runs).

Todo acesso à API é feito por código próprio (sem PyGithub ou similares), com
cache em disco, retomada e tratamento de rate limit.
"""
