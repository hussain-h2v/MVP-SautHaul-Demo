"""Provider client contract. Every provider SDK lives behind this interface and is imported only inside modules/ai."""
from dataclasses import dataclass, field
from typing import Any, Protocol

# Stable error codes the router understands (and logs)
TIMEOUT = "timeout"
RATE_LIMIT = "rate_limit"
SERVER_ERROR = "server_error"
NETWORK = "network"
AUTH = "auth"
REFUSAL = "refusal"
BAD_REQUEST = "bad_request"
INVALID_OUTPUT = "invalid_output"
RETRYABLE = {TIMEOUT, SERVER_ERROR, NETWORK}


class ProviderError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message or code
        super().__init__(f"{code}: {self.message}")


@dataclass
class CallRequest:
    kind: str
    base_url: str | None
    model_name: str
    api_key: str | None
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    json_mode: bool = False
    temperature: float = 0.2
    max_tokens: int = 800
    timeout_s: float = 20.0
    attempt: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class CallResponse:
    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    finish_reason: str = "stop"


class ProviderClient(Protocol):
    async def complete(self, req: CallRequest) -> CallResponse: ...
