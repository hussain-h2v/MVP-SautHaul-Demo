"""Mask personal data before it leaves the system (when the provider is not allowed to receive it) and restore it in
the response. Phone numbers, vehicle registrations and the driver/contact names passed in `context['pii_names']`."""
import re

PHONE = re.compile(r"(?<![\w])(?:\+?\d{1,3}[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?![\w])|\+\d{8,15}")
VEHICLE = re.compile(r"\b[A-Z]{2}[ -]?\d{1,2}[ -]?[A-Z]{0,3}[ -]?\d{4}\b")


class Masker:
    def __init__(self, names: list[str] | None = None) -> None:
        self.map: dict[str, str] = {}
        self._counts = {"PHONE": 0, "VEHICLE": 0, "NAME": 0}
        self._names = sorted({n.strip() for n in (names or []) if n and len(n.strip()) > 2}, key=len, reverse=True)

    def _token(self, kind: str, original: str) -> str:
        for k, v in self.map.items():
            if not k.startswith(f"[[{kind}_"):
                continue
            if v == original or (kind == "NAME" and v.lower() == original.lower()) or (
                    kind == "PHONE" and re.sub(r"\D", "", v) == re.sub(r"\D", "", original)):
                return k
        self._counts[kind] += 1
        token = f"[[{kind}_{self._counts[kind]}]]"
        self.map[token] = original
        return token

    def mask(self, text: str) -> str:
        for n in self._names:
            text = re.sub(rf"(?<!\w){re.escape(n)}(?!\w)", lambda m: self._token("NAME", m.group(0)), text, flags=re.IGNORECASE)
        text = VEHICLE.sub(lambda m: self._token("VEHICLE", m.group(0)), text)
        return PHONE.sub(lambda m: self._token("PHONE", m.group(0)), text)

    def mask_messages(self, messages: list[dict]) -> list[dict]:
        return [{**m, "content": self.mask(m["content"]) if isinstance(m.get("content"), str) else m.get("content")} for m in messages]

    def unmask(self, text: str) -> str:
        for token, original in self.map.items():
            text = text.replace(token, original)
        return text


def redact(text: str) -> str:
    """One-way redaction for stored log bodies."""
    return PHONE.sub("[phone]", VEHICLE.sub("[vehicle]", text))
