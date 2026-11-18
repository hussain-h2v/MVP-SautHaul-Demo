"""Deterministic guardrails. They run BEFORE any model sees a message and do not depend on AI being available:
safety words in every supported language, penalty/compensation/dispute requests, and prompt-injection phrases.
Driver text is data: it is never executed, never echoed into tool arguments, and a model only ever sees it inside a
delimited block with a strict output schema."""
import re

SAFETY = [
    "accident", "injur", "fire", "burning", "robbery", "robbed", "looted", "hijack", "medical", "ambulance", "heart attack", "kidnap",
    "durghatna", "haadsa", "hadsa", "chot lag", "aag lag", "lootera", "dacoit", "baimaan", "dard ho",
    "दुर्घटना", "हादसा", "एक्सीडेंट", "चोट", "आग", "लूट", "डकैती", "अस्पताल", "एंबुलेंस", "बीमार",
    "ప్రమాదం", "యాక్సిడెంట్", "గాయ", "అగ్ని", "మంటలు", "దోపిడీ", "ఆసుపత్రి", "అంబులెన్స్",
    "अपघात", "जखमी", "आगीत", "दरोडा", "रुग्णालय",
    "ਹਾਦਸਾ", "ਸੱਟ", "ਅੱਗ", "ਲੁੱਟ", "ਹਸਪਤਾਲ",
    "விபத்து", "காயம்", "தீ விபத்து", "கொள்ளை", "மருத்துவமனை",
    "ಅಪಘಾತ", "ಗಾಯ", "ಬೆಂಕಿ", "ದರೋಡೆ", "ಆಸ್ಪತ್ರೆ",
    "અકસ્માત", "ઈજા", "આગ", "લૂંટ", "હોસ્પિટલ",
    "দুর্ঘটনা", "আঘাত", "আগুন", "ডাকাতি", "হাসপাতাল",
]
DISPUTE = ["penalty", "fined", "fine for", "fine of", "compensation", "refund", "dispute", "detention charge", "demurrage", "claim money", "pay me",
           "jurmana", "muavza", "mujhe paisa", "जुर्माना", "मुआवज़ा", "मुआवजा", "पेनल्टी", "జరిమానా", "పరిహారం", "दंड", "ਜੁਰਮਾਨਾ"]
INJECTION = [
    r"ignore (?:all |the |any )?(?:previous|above|prior|earlier) (?:instructions|rules|messages)", r"system prompt", r"you are now",
    r"\bact as (?:an? )?", r"developer (?:message|mode)", r"jailbreak", r"reveal (?:your|the) (?:instructions|prompt|rules)",
    r"forget (?:all |your |the )?(?:rules|instructions)", r"pretend (?:to be|you)", r"confirm (?:my|the) (?:slot|booking) (?:now|anyway)",
    r"override (?:the )?(?:priority|rules|policy)", r"change (?:my|the) priority", r"<\s*/?\s*(?:system|assistant|tool)\s*>",
]
_INJ = re.compile("|".join(INJECTION), re.IGNORECASE)


def is_safety(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in SAFETY)


def is_dispute(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in DISPUTE)


def looks_like_injection(text: str) -> bool:
    return bool(_INJ.search(text))
