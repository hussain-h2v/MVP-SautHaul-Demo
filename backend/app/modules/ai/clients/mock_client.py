"""Deterministic offline provider used by tests, the WhatsApp simulator and demos. No network, no key, no cost.
Model names pick the behaviour, so every router path (timeout, 429, 5xx, bad JSON, auth failure, refusal) can be
exercised and the evaluation screens can compare a strong model with a weak one."""
import json
import re

from app.modules.ai.clients import base
from app.modules.ai.clients.base import CallRequest, CallResponse, ProviderError

REPAIR_MARKER = "Return only valid JSON"

# keyword -> intent, checked in order (safety first). English plus Hindi/Hinglish/Telugu/Marathi/Punjabi/Tamil words.
SAFETY = ["accident", "injur", "fire", "robbery", "robbed", "medical", "ambulance", "durghatna", "हादसा", "दुर्घटना", "आग", "लूट",
          "chori", "danka", "apaghatam", "ప్రమాదం", "अपघात", "ਹਾਦਸਾ", "விபத்து", "bimar", "hospital"]
ARRIVAL = ["reached", "arrived", "at the gate", "gate pe", "gate par", "pahunch gaya", "pahunch gayi", "पहुँच गया", "पहुंच गया", "చేరుకున్నాను",
           "पोहोचलो", "ਪਹੁੰਚ ਗਿਆ", "வந்துவிட்டேன"]
OPTIONS = ["what slots", "which slots", "any slot", "slot options", "options", "slots possible", "kaunsa slot", "slot kab", "कौन सा स्लॉट",
           "स्लॉट", "slot milega", "ఏ స్లాట్", "कोणता स्लॉट", "ਕਿਹੜਾ ਸਲਾਟ"]
STATUS = ["my appointment", "status", "when is my", "kab hai meri", "meri booking", "मेरी बुकिंग", "appointment kab"]
GATE = ["which gate", "gate number", "contact number", "gate info", "gate kaun", "gate kahan", "कौन सा गेट", "संपर्क"]
ACCEPT = ["yes", "accept", "ok book", "confirm", "haan", "theek hai", "ठीक है", "हाँ", "sare", "అవును", "हो", "ਹਾਂ", "சரி"]
DECLINE = ["no thanks", "decline", "not possible", "nahi", "नहीं", "వద్దు", "नको", "ਨਹੀਂ", "வேண்டாம்"]
DELAY = ["late", "delay", "stuck", "breakdown", "broke down", "puncture", "traffic", "jam", "der", "deri", "ghante", "ghanta", "लेट",
         "देर", "देरी", "जाम", "खराब", "ఆలస్యం", "లేట్", "उशीर", "ਦੇਰ", "லேட்", "தாமதம்", "hours", "hour", "mins", "minutes", "min "]
WEAK_ONLY_ENGLISH = {"late", "delay", "stuck", "breakdown", "traffic", "accident", "reached", "arrived", "options", "slot options"}

_NUM_WORDS = {"ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5, "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "one": 1, "two": 2,
              "three": 3, "four": 4, "five": 5, "రెండు": 2, "మూడు": 3, "दोन": 2, "तीन ": 3, "ਦੋ": 2}


def _has(text: str, words: list[str]) -> bool:
    t = text.lower()
    return any(w in t for w in words)


def _eta_time(text: str) -> str | None:
    m = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", text)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    m = re.search(r"\b(?:by|at|around|tak|को|पर|baje)?\s*(\d{1,2})\s*(am|pm|baje|बजे)\b", text.lower())
    if m:
        h = int(m.group(1))
        if m.group(2) == "pm" and h < 12:
            h += 12
        if m.group(2) == "baje" and h < 7:
            h += 12
        return f"{h % 24:02d}:00"
    return None


def _delay_minutes(text: str, english_only: bool = False) -> int | None:
    t = text.lower()
    units = r"hours?|hrs?" if english_only else r"hours?|hrs?|ghante|ghanta|घंटे|घंटा"
    m = re.search(rf"(\d+(?:\.\d+)?)\s*(?:{units})", t)
    if m:
        return int(float(m.group(1)) * 60)
    m = re.search(r"(\d+)\s*(?:mins?|minutes?|मिनट|minute)", t)
    if m:
        return int(m.group(1))
    for w, n in ({} if english_only else _NUM_WORDS).items():
        if re.search(rf"{re.escape(w)}\s*(?:ghante|ghanta|घंटे|hours?)", t):
            return n * 60
    return None


def classify(text: str, *, english_only: bool = False) -> dict:
    if english_only:  # the weak demo model only understands plain English
        text = re.sub(r"[^\x00-\x7f]", " ", text)
    t = text.lower()

    def hit(words: list[str]) -> bool:
        ws = [w for w in words if (not english_only or w in WEAK_ONLY_ENGLISH or w.isascii() and w in ("what slots", "options"))]
        return _has(t, ws)

    if hit(SAFETY):
        intent = "safety_issue"
    elif hit(ARRIVAL):
        intent = "report_arrival"
    elif hit(GATE):
        intent = "ask_gate_info"
    elif hit(STATUS):
        intent = "ask_status"
    elif hit(OPTIONS) and not hit(DELAY):
        intent = "ask_options"
    elif hit(DELAY) or _delay_minutes(text, english_only) is not None:
        intent = "report_delay"
    elif hit(DECLINE):
        intent = "decline_suggestion"
    elif hit(ACCEPT):
        intent = "accept_suggestion"
    else:
        intent = "unknown"
    delay = _delay_minutes(text, english_only) if intent in ("report_delay", "ask_options") else None
    cause = None
    for words, label in ((["breakdown", "broke down", "puncture", "kharab", "खराब"], "BREAKDOWN"), (["traffic", "jam", "जाम"], "TRAFFIC"),
                         (["rain", "barish", "बारिश", "weather"], "WEATHER")):
        if _has(t, words):
            cause = label
            break
    eta = _eta_time(text) if intent in ("report_delay", "ask_options", "report_arrival") else None
    repair_time = bool(re.search(r"repair|theek hone|ठीक होने|fix", t)) and delay is not None
    return {"intent": intent, "delay_minutes": delay, "delay_is_repair_time": repair_time or None, "eta_time": eta,
            "cause": cause, "latest_finish_time": None, "confidence": 0.9 if intent != "unknown" else 0.3}


def _last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content", "")
            c = c if isinstance(c, str) else json.dumps(c)
            if REPAIR_MARKER in c:
                continue  # a repair request: classify the original driver message
            return c
    return ""


class MockClient:
    async def complete(self, req: CallRequest) -> CallResponse:
        name = req.model_name
        if name == "mock-timeout":
            raise ProviderError(base.TIMEOUT, "mock timeout")
        if name == "mock-429":
            raise ProviderError(base.RATE_LIMIT, "mock rate limit")
        if name == "mock-500":
            raise ProviderError(base.SERVER_ERROR, "mock 503")
        if name == "mock-network":
            raise ProviderError(base.NETWORK, "mock connection reset")
        if name == "mock-auth":
            raise ProviderError(base.AUTH, "mock invalid api key")
        if name == "mock-refusal":
            raise ProviderError(base.REFUSAL, "mock refusal")
        text = _last_user_text(req.messages)
        repairing = any(REPAIR_MARKER in str(m.get("content", "")) for m in req.messages)
        if name == "mock-badjson" or (name == "mock-badjson-once" and not repairing):
            out = "Sure! here is the answer {not json"
        elif req.json_mode:
            out = json.dumps(classify(text, english_only=name == "mock-weak"))
        elif any("translate" in str(m.get("content", "")).lower() for m in req.messages if m.get("role") == "system"):
            out = f"[translated] {text}"
        else:
            out = f"Noted. ({name}) {text[:80]}"
        return CallResponse(text=out, tokens_in=max(1, sum(len(str(m.get("content", ""))) for m in req.messages) // 4),
                            tokens_out=max(1, len(out) // 4))
