"""The ONLY file in this project that calls a language model.

Every other module (nlu.py, tools.py, conversation.py, scheduler_tool.py)
is deterministic, offline, and network-free by construction -- that is
what the brief and the project's own instructions ask for, and what makes
tests.test_concurrency.py a repeatable proof rather than a flaky one.

This module exists for exactly one situation: the rule-based parser in
nlu.py found no usable signal at all in a driver's message (not a delay,
not a time, not a yes/no, not a status question) -- the point where the
conversation layer would otherwise just say "I didn't understand" and ask
the driver to repeat themselves. Before giving up, it makes ONE call to a
small model, asking it to fill the exact same structured fields nlu.py
already extracts, and the result is fed into the SAME deterministic
pipeline as any other parsed message. The model is never asked, and never
allowed, to decide feasibility, priority, or commitment -- those still
only happen in tools.py, unchanged.

Design note (why this is "less LLM calling," not more): this is a
fallback, not a replacement for nlu.py -- every seeded scenario message in
this project is handled by the rule-based parser alone and never reaches
this file. It only fires on messages genuinely outside that rule set,
which is precisely where the brief says an agent "earns its place."

Uses OpenRouter (https://openrouter.ai), a single HTTPS API in front of
many models -- no AWS-specific setup (no Bedrock model-access approval,
no IAM grant), just one API key read from the OPENROUTER_API_KEY
environment variable. Only the standard library (urllib) is used to make
the call, so no extra dependency is added to requirements.txt. Any
failure here (no key configured, network error, bad JSON, timeout) is
swallowed and treated as "no fallback available" -- the conversation
layer falls back to asking the driver directly, exactly as it would if
this file did not exist.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Optional

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_DEFAULT_MODEL = "anthropic/claude-haiku-4.5"

_SYSTEM_PROMPT = """You read one truck driver's free-text message to a logistics dispatch system. \
The driver writes in Hindi, Hinglish (romanised Hindi mixed with English), or English. \
Extract ONLY what the message actually states -- never guess a value it does not contain.

Reply with ONLY a single JSON object (no prose, no markdown fences), with these keys:
- "reports_delay": true if the driver is reporting a delay or new arrival time, else false
- "delay_minutes": integer minutes of delay if stated as a duration, else null
- "explicit_time_hhmm": a stated clock time as "HH:MM" (24-hour) if the driver gave one, else null
- "ambiguous_duration": true if a delay duration was given but it is unclear whether it is the \
new arrival time or something else (like a repair duration), else false
- "reason_code": one of "TRAFFIC","BREAKDOWN","WEATHER","LATE_DEPARTURE","ROUTE_ISSUE", or null
- "wants_options_only": true if the driver is only asking what slots exist, not booking
- "wants_confirmation": true if the driver is confirming/accepting an offered option
- "wants_decline": true if the driver is declining/rejecting an offered option
- "is_status_check": true if the driver is only asking about their current booking's status
- "latest_acceptable_hhmm": a stated "I need to leave by HH:MM" constraint, else null
- "selection_ordinal": the offered option number if the driver names "the first/second/third" option \
or replies with its number, else null
- "selection_dock_code": a dock code such as "D3" if the driver explicitly selects that offered dock, else null

If the current simulated hour-of-day is given, use it only to resolve a bare hour with no AM/PM \
marker (e.g. if it is already past that hour once today, a bare "1" likely means 1 PM)."""


def try_llm_fallback(text: str, current_hour: Optional[int]) -> Optional[dict]:
    """Returns a dict of ParsedMessage-shaped fields, or None if the model
    could not be reached or did not return something usable."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return {"_error": "OPENROUTER_API_KEY is not set in this process's environment."}
    model = os.environ.get("OPENROUTER_MODEL", _DEFAULT_MODEL)
    user_text = text if current_hour is None else f"[current simulated hour: {current_hour}] {text}"

    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0,
        "max_tokens": 300,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    req = urllib.request.Request(
        _OPENROUTER_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # OpenRouter asks for these two for attribution; harmless if ignored.
            "HTTP-Referer": "https://setuhaul-fde-demo.local",
            "X-Title": "SetuHaul FDE demo",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        raw = payload["choices"][0]["message"]["content"].strip()
        if raw.startswith("```"):
            raw = raw.strip("`").split("\n", 1)[-1]
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return data
    except Exception as exc:  # noqa: BLE001 -- any failure here means "no fallback", never a crash
        # Returned, not raised: a failed fallback must never break the
        # conversation. The conversation layer only ever treats this as "no
        # usable fields" (the _error key isn't one of ParsedMessage's), so
        # this is safe in production; it also makes the failure reason
        # inspectable via the "debug_llm_fallback" action in agentcore_app.py.
        return {"_error": f"{type(exc).__name__}: {exc}"}
