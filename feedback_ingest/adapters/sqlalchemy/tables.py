from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint, true
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TenantRow(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    api_key_hash: Mapped[str] = mapped_column(unique=True)


class SourceRow(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("id", "tenant_id"),)
    id: Mapped[str] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    type: Mapped[str]
    name: Mapped[str]
    mode: Mapped[str]
    config: Mapped[dict[str, str]] = mapped_column(JSON)
    webhook_secret: Mapped[str | None]
    cursor: Mapped[str | None]
    enabled: Mapped[bool] = mapped_column(default=True, server_default=true())


class RawEventRow(Base):
    __tablename__ = "raw_events"
    __table_args__ = (
        UniqueConstraint("source_id", "external_event_id"),
        ForeignKeyConstraint(["source_id", "tenant_id"], ["sources.id", "sources.tenant_id"]),
        Index("ix_raw_events_status_next_attempt_at", "status", "next_attempt_at"),
    )
    id: Mapped[str] = mapped_column(primary_key=True)
    tenant_id: Mapped[str]
    source_id: Mapped[str]
    external_event_id: Mapped[str]
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    received_at: Mapped[datetime]
    status: Mapped[str]
    attempts: Mapped[int]
    next_attempt_at: Mapped[datetime]
    lease_until: Mapped[datetime | None]
    error: Mapped[str | None]


class FeedbackRecordRow(Base):
    __tablename__ = "feedback_records"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id"),
        ForeignKeyConstraint(["source_id", "tenant_id"], ["sources.id", "sources.tenant_id"]),
        Index("ix_feedback_records_tenant_created", "tenant_id", "source_created_at"),
    )
    id: Mapped[str] = mapped_column(primary_key=True)
    tenant_id: Mapped[str]
    source_id: Mapped[str]
    source_type: Mapped[str]
    external_id: Mapped[str]
    kind: Mapped[str]
    title: Mapped[str | None]
    text: Mapped[str]
    author: Mapped[str | None]
    language: Mapped[str | None]
    rating: Mapped[int | None]
    source_created_at: Mapped[datetime]
    source_updated_at: Mapped[datetime | None]
    ingested_at: Mapped[datetime]
    deleted_at: Mapped[datetime | None]
    connector_version: Mapped[int]
    source_metadata: Mapped[dict[str, object]] = mapped_column("metadata", JSON)
