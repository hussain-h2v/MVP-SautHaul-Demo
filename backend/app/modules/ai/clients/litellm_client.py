"""The only place a provider SDK is imported (LiteLLM, the unified client library underneath our own router)."""
from app.modules.ai.clients import base
from app.modules.ai.clients.base import CallRequest, CallResponse, ProviderError

PREFIX = {"openai": "", "anthropic": "anthropic/", "google": "gemini/", "azure_openai": "azure/", "openai_compatible": "openai/"}


def _map_error(exc: Exception) -> ProviderError:
    name = type(exc).__name__
    msg = str(exc)[:300]
    table = {
        "Timeout": base.TIMEOUT, "APITimeoutError": base.TIMEOUT, "RateLimitError": base.RATE_LIMIT,
        "AuthenticationError": base.AUTH, "PermissionDeniedError": base.AUTH, "ContentPolicyViolationError": base.REFUSAL,
        "BadRequestError": base.BAD_REQUEST, "APIConnectionError": base.NETWORK, "ServiceUnavailableError": base.SERVER_ERROR,
        "InternalServerError": base.SERVER_ERROR, "APIError": base.SERVER_ERROR, "BadGatewayError": base.SERVER_ERROR,
    }
    return ProviderError(table.get(name, base.SERVER_ERROR), f"{name}: {msg}")


class LiteLLMClient:
    async def complete(self, req: CallRequest) -> CallResponse:
        import litellm  # noqa: PLC0415  (provider SDK: allowed only in modules/ai)

        kwargs = {
            "model": PREFIX.get(req.kind, "") + req.model_name, "messages": req.messages, "temperature": req.temperature,
            "max_tokens": req.max_tokens, "timeout": req.timeout_s, "num_retries": 0,
        }
        if req.api_key:
            kwargs["api_key"] = req.api_key
        if req.base_url:
            kwargs["api_base"] = req.base_url
        if req.tools:
            kwargs["tools"] = req.tools
        if req.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            r = await litellm.acompletion(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise _map_error(exc) from exc
        choice = r.choices[0]
        msg = choice.message
        calls = [{"id": t.id, "name": t.function.name, "arguments": t.function.arguments} for t in (getattr(msg, "tool_calls", None) or [])]
        usage = getattr(r, "usage", None)
        finish = getattr(choice, "finish_reason", "stop") or "stop"
        if finish == "content_filter":
            raise ProviderError(base.REFUSAL, "provider content filter")
        return CallResponse(text=msg.content or "", tool_calls=calls, tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
                            tokens_out=getattr(usage, "completion_tokens", 0) or 0, finish_reason=finish)
