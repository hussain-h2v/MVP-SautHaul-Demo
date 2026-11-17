from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.ai.models import PROVIDER_KINDS, TASKS

CAPABILITIES = ("chat", "tools", "json", "vision", "multilingual")
ERROR_CODES = ("timeout", "rate_limit", "server_error", "network", "auth")
CONDITION_KEYS = {"languages", "max_input_chars", "min_input_chars"}


# ---------------------------------------------------------------- providers
class ProviderIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    kind: str
    base_url: str | None = Field(default=None, max_length=300)
    rate_limit_rpm: int | None = Field(default=None, ge=1, le=100000)
    allow_pii: bool = False
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in PROVIDER_KINDS:
            raise ValueError("kind must be one of " + ", ".join(PROVIDER_KINDS))
        return v

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v and not v.lower().startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return v.rstrip("/") if v else v


class ProviderPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    base_url: str | None = Field(default=None, max_length=300)
    status: Literal["enabled", "disabled"] | None = None
    rate_limit_rpm: int | None = Field(default=None, ge=1, le=100000)
    allow_pii: bool | None = None
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v and not v.lower().startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return v.rstrip("/") if v else v


class ProviderOut(BaseModel):
    id: UUID
    name: str
    kind: str
    base_url: str | None
    status: str
    rate_limit_rpm: int | None
    allow_pii: bool
    last_error: str | None
    last_checked_at: datetime | None
    notes: str | None
    key_count: int = 0
    model_count: int = 0
    breaker: str = "closed"


class TestOut(BaseModel):
    ok: bool
    latency_ms: int
    model: str | None = None
    error: str | None = None


class FailureIn(BaseModel):
    error_code: str
    seconds: int = Field(default=60, ge=1, le=300)

    @field_validator("error_code")
    @classmethod
    def _code(cls, v: str) -> str:
        if v not in ERROR_CODES:
            raise ValueError("error_code must be one of " + ", ".join(ERROR_CODES))
        return v


# ---------------------------------------------------------------- keys
class KeyIn(BaseModel):
    provider_id: UUID
    label: str = Field(min_length=1, max_length=100)
    api_key: str = Field(min_length=8, max_length=500)
    monthly_budget: Decimal | None = Field(default=None, ge=0)
    weight: int = Field(default=1, ge=1, le=100)


class KeyPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=100)
    status: Literal["active", "disabled"] | None = None
    monthly_budget: Decimal | None = Field(default=None, ge=0)
    weight: int | None = Field(default=None, ge=1, le=100)


class RotateIn(BaseModel):
    api_key: str = Field(min_length=8, max_length=500)


class KeyOut(BaseModel):
    id: UUID
    provider_id: UUID
    provider_name: str = ""
    label: str
    key_last4: str
    status: str
    last_used_at: datetime | None
    monthly_budget: Decimal | None
    weight: int
    last_error: str | None
    month_spend: Decimal = Decimal("0")
    month_requests: int = 0


# ---------------------------------------------------------------- models
class ModelIn(BaseModel):
    provider_id: UUID
    model_name: str = Field(min_length=1, max_length=150)
    capabilities: list[str] = ["chat"]
    context_window: int | None = Field(default=None, ge=1)
    input_price: Decimal = Field(default=Decimal("0"), ge=0)
    output_price: Decimal = Field(default=Decimal("0"), ge=0)

    @field_validator("capabilities")
    @classmethod
    def _caps(cls, v: list[str]) -> list[str]:
        bad = [c for c in v if c not in CAPABILITIES]
        if bad:
            raise ValueError("Unknown capabilities: " + ", ".join(bad))
        return v


class ModelPatch(BaseModel):
    model_name: str | None = Field(default=None, min_length=1, max_length=150)
    capabilities: list[str] | None = None
    context_window: int | None = Field(default=None, ge=1)
    input_price: Decimal | None = Field(default=None, ge=0)
    output_price: Decimal | None = Field(default=None, ge=0)
    status: Literal["active", "disabled"] | None = None

    @field_validator("capabilities")
    @classmethod
    def _caps(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and [c for c in v if c not in CAPABILITIES]:
            raise ValueError("Unknown capability")
        return v


class ModelOut(BaseModel):
    id: UUID
    provider_id: UUID
    provider_name: str = ""
    model_name: str
    capabilities: list[str]
    context_window: int | None
    input_price: Decimal
    output_price: Decimal
    status: str


class ModelTestIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


class ModelTestOut(BaseModel):
    text: str | None = None
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost: Decimal = Decimal("0")
    error: str | None = None


# ---------------------------------------------------------------- routes
class StepIn(BaseModel):
    model_id: UUID
    key_id: UUID | None = None
    key_ids: list[UUID] = []
    key_strategy: Literal["single", "round_robin", "weighted"] = "single"
    timeout_ms: int = Field(default=20000, ge=1000, le=120000)
    max_retries: int = Field(default=1, ge=0, le=3)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=800, ge=1, le=8192)
    conditions: dict[str, Any] = {}

    @field_validator("conditions")
    @classmethod
    def _cond(cls, v: dict) -> dict:
        bad = set(v) - CONDITION_KEYS
        if bad:
            raise ValueError("Unknown condition keys: " + ", ".join(sorted(bad)) + " (allowed: " + ", ".join(sorted(CONDITION_KEYS)) + ")")
        return v


class RoutePut(BaseModel):
    enabled: bool | None = None
    fallback_on_refusal: bool | None = None
    steps: list[StepIn] = Field(max_length=6)


class EnabledIn(BaseModel):
    enabled: bool


class StepOut(BaseModel):
    id: UUID
    priority: int
    model_id: UUID
    model_name: str
    provider_name: str
    key_id: UUID | None
    key_ids: list[Any]
    key_strategy: str
    timeout_ms: int
    max_retries: int
    temperature: float
    max_tokens: int
    conditions: dict[str, Any]


class RouteOut(BaseModel):
    task: str
    description: str | None
    enabled: bool
    fallback_on_refusal: bool
    steps: list[StepOut]


class RouteSimOut(BaseModel):
    used: dict | None
    fallback_depth: int
    path: list[dict]
    unavailable: bool


# ---------------------------------------------------------------- prompts
class PromptIn(BaseModel):
    task: str
    language: str = Field(default="en", min_length=2, max_length=10)
    template: str = Field(min_length=1, max_length=12000)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("task")
    @classmethod
    def _task(cls, v: str) -> str:
        if v not in TASKS:
            raise ValueError("Unknown task")
        return v


class PromptPatch(BaseModel):
    template: str | None = Field(default=None, min_length=1, max_length=12000)
    notes: str | None = Field(default=None, max_length=500)


class PromptOut(BaseModel):
    id: UUID
    task: str
    language: str
    prompt_version: int
    template: str
    status: str
    notes: str | None
    created_at: datetime


class RollbackIn(BaseModel):
    version: int = Field(ge=1)


class PromptTestIn(BaseModel):
    template: str | None = None
    prompt_id: UUID | None = None
    variables: dict[str, Any] = {}
    task: str = "intent_classify"
    model_id: UUID | None = None
    sample_message: str = Field(min_length=1, max_length=2000)
    language: str | None = None

    @model_validator(mode="after")
    def _one(self):
        if not self.template and not self.prompt_id:
            raise ValueError("Provide template or prompt_id")
        return self


# ---------------------------------------------------------------- budgets / safety / test
class BudgetIn(BaseModel):
    scope: Literal["global", "provider", "task", "key"]
    scope_id: str | None = Field(default=None, max_length=64)
    period: Literal["daily", "monthly"] = "monthly"
    limit_amount: Decimal = Field(gt=0)
    alert_threshold: float = Field(default=0.8, gt=0, le=1)
    enabled: bool = True


class BudgetPatch(BaseModel):
    limit_amount: Decimal | None = Field(default=None, gt=0)
    alert_threshold: float | None = Field(default=None, gt=0, le=1)
    enabled: bool | None = None
    period: Literal["daily", "monthly"] | None = None


class BudgetOut(BaseModel):
    id: UUID
    scope: str
    scope_id: str | None
    scope_label: str | None = None
    period: str
    limit_amount: Decimal
    alert_threshold: float
    enabled: bool
    spent: Decimal = Decimal("0")
    percent: float = 0.0
    state: str = "ok"


class BreakerIn(BaseModel):
    threshold: int = Field(ge=1, le=100)
    window_seconds: int = Field(ge=1, le=3600)
    cooldown_seconds: int = Field(ge=1, le=3600)


class SafetyPut(BaseModel):
    kill_switch: bool | None = None
    log_bodies: bool | None = None
    log_retention_days: int | None = Field(default=None, ge=1, le=3650)
    breaker: BreakerIn | None = None


class PlaygroundIn(BaseModel):
    task: str
    messages: list[dict[str, Any]] = Field(min_length=1, max_length=20)
    schema_: Literal["intent"] | None = Field(default=None, alias="schema")
    context: dict[str, Any] = {}

    model_config = {"populate_by_name": True}

    @field_validator("task")
    @classmethod
    def _task(cls, v: str) -> str:
        if v not in TASKS:
            raise ValueError("Unknown task")
        return v
