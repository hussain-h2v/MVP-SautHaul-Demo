"""Deterministic, model-free parsing of short driver answers (times, durations, causes, choices) and script-based language
detection. The agent uses these to read replies to its own questions, so the conversation works even when AI is off."""
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

HOUR_WORDS = r"hours?|hrs?|hr|ghante|ghanta|ghantey|ghanta|घंटे|घंटा|घण्टे|గంట(?:లు|ల)?|तास|ਘੰਟੇ|ਘੰਟਾ|மணி|ಗಂಟೆ|ঘণ্টা"
MIN_WORDS = r"mins?|minutes?|minute|मिनट|నిమిషా(?:లు|ల)?|मिनिटे|ਮਿੰਟ|நிமிடம்|ನಿಮಿಷ|মিনিট"
NUMBER_WORDS = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5, "chhe": 6, "saat": 7, "aath": 8, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "सात": 7, "आठ": 8,
    "ఒక": 1, "రెండు": 2, "మూడు": 3, "నాలుగు": 4, "ఐదు": 5, "దोन": 2, "दोन": 2, "ਦੋ": 2, "ਤਿੰਨ": 3,
}
CAUSES = {
    "BREAKDOWN": ["breakdown", "broke down", "puncture", "engine", "kharab", "खराब", "ख़राब", "బ్రేక్‌డౌన్", "చెడిపోయ", "बिघाड", "ਖਰਾਬ"],
    "TRAFFIC": ["traffic", "jam", "जाम", "ट्रैफिक", "ట్రాఫిక్", "वाहतूक", "ਜਾਮ"],
    "WEATHER": ["rain", "weather", "fog", "barish", "बारिश", "कोहरा", "వర్షం", "पाऊस", "ਮੀਂਹ"],
}
YES = ["yes", "yeah", "ok", "okay", "haan", "ha", "theek hai", "thik hai", "हाँ", "हां", "ठीक है", "అవును", "सरे", "हो", "ਹਾਂ", "சரி"]
NO = ["no", "nahi", "nope", "नहीं", "వద్దు", "नको", "ਨਹੀਂ", "வேண்டாம்"]
REPAIR_WORDS = ["repair", "theek hone", "ठीक होने", "मरम्मत", "fix", "रिपेयर", "మరమ్మత్తు"]
TOTAL_WORDS = ["total", "kul", "कुल", "arrival", "reach", "pahunch", "पहुँच", "పూర్తి"]


def parse_time(text: str, now: datetime, tz: str) -> datetime | None:
    """A clock time in the facility's zone (today, or tomorrow if already past) as an aware datetime, else None."""
    t = text.lower()
    zone = ZoneInfo(tz)
    local = now.astimezone(zone)
    hh = mm = None
    m = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\s*(am|pm)?\b", t)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        if m.group(3) == "pm" and hh < 12:
            hh += 12
        if m.group(3) == "am" and hh == 12:
            hh = 0
    else:
        m = re.search(r"\b(\d{1,2})\s*(am|pm|baje|बजे|గంటలకు)", t)
        if m:
            hh, mm = int(m.group(1)), 0
            if m.group(2) == "pm" and hh < 12:
                hh += 12
            elif m.group(2) in ("baje", "बजे") and hh < 7:
                hh += 12
    if hh is None or hh > 23:
        return None
    cand = datetime.combine(local.date(), time(hh, mm), tzinfo=zone)
    if cand < local - timedelta(minutes=5):
        cand += timedelta(days=1)
    return cand.astimezone(now.tzinfo)


def parse_minutes(text: str) -> int | None:
    """A duration in minutes ('2 hours', '45 min', 'do ghante', 'दो घंटे')."""
    t = text.lower()
    m = re.search(rf"(\d+(?:\.\d+)?)\s*(?:{HOUR_WORDS})", t)
    if m:
        return int(float(m.group(1)) * 60)
    m = re.search(rf"(\d+)\s*(?:{MIN_WORDS})", t)
    if m:
        return int(m.group(1))
    for word, n in NUMBER_WORDS.items():
        if re.search(rf"{re.escape(word)}\s*(?:{HOUR_WORDS})", t):
            return n * 60
    return None


def parse_cause(text: str) -> str | None:
    t = text.lower()
    for code, words in CAUSES.items():
        if any(w in t for w in words):
            return code
    return None


def parse_delay_meaning(text: str) -> str | None:
    t = text.lower()
    if any(w in t for w in REPAIR_WORDS):
        return "repair"
    if any(w in t for w in TOTAL_WORDS):
        return "total"
    return None


def is_yes(text: str) -> bool:
    t = text.strip().lower()
    return any(t == w or t.startswith(w + " ") for w in YES)


def is_no(text: str) -> bool:
    t = text.strip().lower()
    return any(t == w or t.startswith(w + " ") for w in NO)


def parse_choice_number(text: str, limit: int) -> int | None:
    t = text.lower()
    m = re.search(r"\b(?:option\s*)?(\d{1,2})\b", t)
    if m and 1 <= int(m.group(1)) <= limit:
        return int(m.group(1))
    for word, n in (("first", 1), ("second", 2), ("third", 3), ("pehla", 1), ("doosra", 2), ("पहला", 1), ("दूसरा", 2)):
        if word in t and n <= limit:
            return n
    return None


SCRIPTS = [("hi", r"[ऀ-ॿ]"), ("te", r"[ఀ-౿]"), ("ta", r"[஀-௿]"), ("gu", r"[઀-૿]"),
           ("pa", r"[਀-੿]"), ("kn", r"[ಀ-೿]"), ("bn", r"[ঀ-৿]")]


def detect_language(text: str, fallback: str) -> str:
    """Reply in the language the driver writes: by script; Latin-script (incl. transliterated Hindi) keeps the driver's
    preferred language."""
    for lang, rx in SCRIPTS:
        if re.search(rx, text):
            return lang
    return fallback
