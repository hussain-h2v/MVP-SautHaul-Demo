from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamped, UUIDPK, Versioned

PROVIDER_KINDS = ("openai", "anthropic", "google", "azure_openai", "openai_compatible", "mock")
TASKS = ("driver_chat", "intent_classify", "translate", "summarise", "driver_insight", "dock_insight",
         "coordinator_suggestion", "transcribe")


class AIProvider(Base, UUIDPK, Timestamped, Versioned):
    """A vendor endpoint. allow_pii=False means phone numbers, driver names and vehicle registrations are masked before
    anything is sent (and restored in the response)."""

    __tablename__ = "ai_providers"
    __table_args__ = (
        CheckConstraint("kind IN ('openai','anthropic','google','azure_openai','openai_compatible','mock')", name="ck_ai_provider_kind"),
        CheckConstraint("status IN ('enabled','disabled')", name="ck_ai_provider_status"),
    )

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(10), default="disabled", nullable=False)
    rate_limit_rpm: Mapped[int | None] = mapped_column(Integer)
    allow_pii: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String(500))


class AIProviderKey(Base, UUIDPK, Timestamped, Versioned):
    """Encrypted at the application layer (AES-GCM). Only the last four characters are ever shown."""

    __tablename__ = "ai_provider_keys"
    __table_args__ = (CheckConstraint("status IN ('active','disabled','failed')", name="ck_ai_key_status"),)

    provider_id: Mapped[UUID] = mapped_column(ForeignKey("ai_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    encrypted_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    key_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="active", nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    monthly_budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    weight: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(500))


class AIModel(Base, UUIDPK, Timestamped, Versioned):
    __tablename__ = "ai_models"
    __table_args__ = (
        CheckConstraint("status IN ('active','disabled')", name="ck_ai_model_status"),
        UniqueConstraint("provider_id", "model_name", name="uq_ai_model_provider_name"),
    )

    provider_id: Mapped[UUID] = mapped_column(ForeignKey("ai_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(150), nullable=False)
    capabilities: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    context_window: Mapped[int | None] = mapped_column(Integer)
    input_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"), nullable=False)  # per 1M tokens
    output_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"), nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="active", nullable=False)


class AIRoute(Base, UUIDPK, Timestamped, Versioned):
    __tablename__ = "ai_routes"

    task: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fallback_on_refusal: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AIRouteStep(Base, UUIDPK, Timestamped, Versioned):
    """One link of a fallback chain. A step may use a pool of keys (single / round_robin / weighted)."""

    __tablename__ = "ai_route_steps"
    __table_args__ = (
        UniqueConstraint("route_id", "priority", name="uq_ai_step_priority"),
        CheckConstraint("key_strategy IN ('single','round_robin','weighted')", name="ck_ai_step_strategy"),
    )

    route_id: Mapped[UUID] = mapped_column(ForeignKey("ai_routes.id", ondelete="CASCADE"), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    model_id: Mapped[UUID] = mapped_column(ForeignKey("ai_models.id"), nullable=False)
    key_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_provider_keys.id"))
    key_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    key_strategy: Mapped[str] = mapped_column(String(12), default="single", nullable=False)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=20000, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.2, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=800, nullable=False)
    conditions: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class AIPrompt(Base, UUIDPK, Timestamped, Versioned):
    __tablename__ = "ai_prompts"
    __table_args__ = (
        CheckConstraint("status IN ('draft','active','archived')", name="ck_ai_prompt_status"),
        UniqueConstraint("task", "language", "prompt_version", name="uq_ai_prompt_version"),
    )

    task: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)  # the prompt's revision; `version` is the lock column
    template: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="draft", nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))


class AIUsageLog(Base):
    """Every AI call. Immutable, so not Versioned. Prompt/response bodies are stored (redacted) only when enabled."""

    __tablename__ = "ai_usage_logs"
    __table_args__ = (
        Index("ix_ai_usage_task_created", "task", "created_at"),
        Index("ix_ai_usage_provider_created", "provider", "created_at"),
        Index("ix_ai_usage_key_created", "key_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    request_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    task: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(150))
    key_id: Mapped[UUID | None] = mapped_column()
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    fallback_depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(40))
    trace_id: Mapped[str | None] = mapped_column(String(64))
    path: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    prompt_redacted: Mapped[str | None] = mapped_column(Text)
    response_redacted: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class AIBudget(Base, UUIDPK, Timestamped, Versioned):
    __tablename__ = "ai_budgets"
    __table_args__ = (
        CheckConstraint("scope IN ('global','provider','task','key')", name="ck_ai_budget_scope"),
        CheckConstraint("period IN ('daily','monthly')", name="ck_ai_budget_period"),
    )

    scope: Mapped[str] = mapped_column(String(10), nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(64))
    period: Mapped[str] = mapped_column(String(8), default="monthly", nullable=False)
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    alert_threshold: Mapped[float] = mapped_column(Float, default=0.8, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AIEvalCase(Base, UUIDPK, Timestamped, Versioned):
    """Golden set: a driver message with the expected intent and fields."""

    __tablename__ = "ai_eval_cases"

    language: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    text: Mapped[str] = mapped_column(String(1000), nullable=False)
    expected: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="custom", nullable=False)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AIEvalRun(Base, UUIDPK, Timestamped, Versioned):
    __tablename__ = "ai_eval_runs"

    label: Mapped[str] = mapped_column(String(150), nullable=False)
    task: Mapped[str] = mapped_column(String(40), default="intent_classify", nullable=False)
    model_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_models.id"))
    status: Mapped[str] = mapped_column(String(12), default="running", nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    correct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accuracy: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"), nullable=False)
    by_language: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    results: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
