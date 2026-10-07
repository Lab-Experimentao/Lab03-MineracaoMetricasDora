"""Registros produzidos pela coleta, já reduzidos aos campos que as métricas usam."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def ler_data(valor: str | None) -> datetime | None:
    """Converte uma data ISO 8601 da API em datetime UTC.

    O REST usa "Z"; a GraphQL devolve o fuso do autor (ex.: "-04:00").
    """
    if not valor:
        return None
    return datetime.fromisoformat(valor.replace("Z", "+00:00")).astimezone(timezone.utc)


@dataclass(frozen=True)
class Candidato:
    """Repositório devolvido pela busca; os metadados vêm do próprio item da busca."""

    nome: str  # owner/repo
    estrelas: int
    linguagem: str | None
    criado_em: datetime
    branch_padrao: str
    url: str
    faixa: str

    @classmethod
    def da_api(cls, item: dict[str, Any], faixa: str) -> Candidato:
        return cls(
            nome=item["full_name"],
            estrelas=item["stargazers_count"],
            linguagem=item.get("language"),
            criado_em=ler_data(item["created_at"]),
            branch_padrao=item["default_branch"],
            url=item["html_url"],
            faixa=faixa,
        )


@dataclass(frozen=True)
class Release:
    tag: str
    publicada_em: datetime | None  # None em drafts
    draft: bool
    prerelease: bool
    url: str

    @classmethod
    def da_api(cls, item: dict[str, Any]) -> Release:
        return cls(
            tag=item["tag_name"],
            publicada_em=ler_data(item.get("published_at")),
            draft=bool(item.get("draft")),
            prerelease=bool(item.get("prerelease")),
            url=item.get("html_url", ""),
        )


@dataclass(frozen=True)
class Tag:
    """Tag com as datas do commit apontado, já que a tag em si não tem data."""

    nome: str
    sha: str
    data_autor: datetime | None
    data_committer: datetime | None


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    data_autor: datetime | None  # commit.author.date (authoredDate na GraphQL)
    mensagem: str  # completa: a heurística da RQ 03 (b) procura fix/revert/hotfix nela

    @property
    def titulo(self) -> str:
        """Primeira linha da mensagem (o messageHeadline da GraphQL corta em ~70 caracteres)."""
        return self.mensagem.splitlines()[0] if self.mensagem else ""

    @classmethod
    def da_graphql(cls, no: dict[str, Any]) -> CommitInfo:
        return cls(sha=no["oid"], data_autor=ler_data(no.get("authoredDate")), mensagem=no.get("message") or "")


@dataclass(frozen=True)
class RunColetado:
    id: int
    workflow_id: int
    workflow_nome: str
    conclusao: str | None
    status: str
    criado_em: datetime
    iniciado_em: datetime | None  # run_started_at
    atualizado_em: datetime  # updated_at
    head_sha: str

    @classmethod
    def da_api(cls, item: dict[str, Any]) -> RunColetado:
        return cls(
            id=item["id"],
            workflow_id=item["workflow_id"],
            workflow_nome=item.get("name") or "",
            conclusao=item.get("conclusion"),
            status=item.get("status") or "",
            criado_em=ler_data(item["created_at"]),
            iniciado_em=ler_data(item.get("run_started_at")),
            atualizado_em=ler_data(item["updated_at"]),
            head_sha=item.get("head_sha") or "",
        )
