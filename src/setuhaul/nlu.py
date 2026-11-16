"""Free-text understanding -- the one place in this project where the
input is messy human language instead of structured fields.

Per the brief's own layer table, this is where "an agent earns its place":
reading free text and asking questions. It is deliberately NOT a language
model call. A regex/keyword parser is the simplest thing that handles the
seeded messages correctly, it needs no network access or API key to run or
grade, and every decision it makes is inspectable. Per the project
instruction to avoid LLM use except where genuinely required: everything
downstream of this module (feasibility, commitment, priority, escalation)
is pure deterministic code in tools.py, never a model guess. If a real
deployment later needed to understand harder phrasing, only this module
would be replaced -- by, for example, a single structured-output call to
an LLM that returns the same ParsedMessage fields it returns today. Nothing
else in the system would need to change.

Language note: SetuHaul's drivers mostly write in Hindi or Hinglish
(romanised Hindi mixed with English), not formal English, so this parser
reads both. The two languages aren't handled by separate code paths --
keyword lists simply carry both English and Hinglish entries, and one
extra pattern (`baje`, the Hindi word for "o'clock") is added because
Hindi word order puts the clock time *before* the verb ("2 baje
pahunchunga" = "I'll reach at 2"), the opposite of English ("reach at 2"),
so it cannot reuse the English verb-then-time pattern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# English words used with "... hours" (e.g. "two hours late").
_WORD_NUMBERS = {
    "half": 0.5, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "a": 1, "an": 1,
}

# Hindi/Hinglish words used with "... ghanta/ghante" (the Hindi word for
# "hour(s)"), e.g. "ek ghanta late" = "one hour late".
_HINDI_NUMBERS = {
    "aadha": 0.5, "adha": 0.5, "ek": 1, "sava": 1.25, "dedh": 1.5,
    "do": 2, "dhai": 2.5, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5,
}

_REASON_KEYWORDS = {
    "TRAFFIC": ["traffic", "jam", "congestion"],
    "BREAKDOWN": ["tyre", "tire", "breakdown", "broke down", "engine", "repair",
                  "panchar", "puncture", "gaadi kharab", "gadi kharab", "truck kharab",
                  "engine kharab"],
    "WEATHER": ["rain", "weather", "storm", "flood", "baarish", "barish", "paani"],
    "LATE_DEPARTURE": ["released me late", "left late", "loading delay at origin", "origin released",
                        "mandi se der", "load late mila", "loading mein der", "der se nikla"],
    "ROUTE_ISSUE": ["closure", "diversion", "detour", "blocked road",
                     "rasta band", "raasta band", "road band"],
}

_CONFIRM_WORDS = [
    "take it", "book it", "confirm", "that works", "works for me", "yes please",
    "go ahead", "book that", "lock it",
    "haan", "ha theek hai", "theek hai", "thik hai", "theek h", "ok kar do", "ok kardo",
    "kar do", "kardo", "le lo", "chalega", "book kar do", "book kardo", "bilkul", "haa",
]
_DECLINE_WORDS = [
    "no thanks", "not that one", "doesn't work", "does not work", "cancel",
    "nahi", "nahin", "mat karo", "cancel kar do", "rehne do", "nahi chahiye",
]
_ASK_ONLY_WORDS = [
    "what slot", "what options", "possible", "any slot", "anything after",
    "could you check", "show me", "options",
    "kaunsa slot", "konsa slot", "kya slot", "slot batao", "kya khali hai",
    "kya available hai", "koi khali slot", "khali slot",
]
_STATUS_CHECK_WORDS = [
    "still active", "still valid", "has a new dock", "any update", "status",
    "abhi bhi hai kya", "abhi bhi active hai", "slot hai kya", "chal raha hai kya",
    "koi update hai",
]
_SECOND_PICKUP_WORDS = [
    "another pickup", "second pickup", "i also have",
    "ek aur load", "ek aur pickup", "doosra load", "dusra load", "dusra pickup",
]
_DELAY_SIGNAL_WORDS = ["late", "delay", "der", "der ho", "der ho gayi", "der ho gaya", "vilamb"]


@dataclass
class ParsedMessage:
    raw_text: str
    reports_delay: bool = False
    delay_minutes: Optional[int] = None
    explicit_time_hhmm: Optional[str] = None
    ambiguous_duration: bool = False
    reason_code: Optional[str] = None
    wants_options_only: bool = False
    wants_confirmation: bool = False
    wants_decline: bool = False
    is_status_check: bool = False
    latest_acceptable_hhmm: Optional[str] = None
    selection_ordinal: Optional[int] = None
    selection_dock_code: Optional[str] = None
    selection_time_hhmm: Optional[str] = None
    mentions_second_pickup: bool = False


_AFTER_RE = re.compile(r"\bafter\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.IGNORECASE)
_BY_RE = re.compile(r"\b(?:leave|by)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.IGNORECASE)
_DELAY_MIN_RE = re.compile(r"\b(\d{1,3})\s*(?:minutes|minute|mins|min)\b", re.IGNORECASE)
_DELAY_HOUR_RE = re.compile(
    r"\b(?:late\s+by\s+|around\s+|about\s+)?(" +
    r"|".join(_WORD_NUMBERS) + r"|\d+(?:\.\d+)?)\s*hours?\b", re.IGNORECASE
)
_DELAY_GHANTA_RE = re.compile(
    r"\b(" + r"|".join(_HINDI_NUMBERS) + r"|\d+(?:\.\d+)?)\s*ghant[ae]\b", re.IGNORECASE
)
_ORDINAL_RE = re.compile(r"\bthe\s+(first|second|third)\b", re.IGNORECASE)
_ORDINALS = {"first": 1, "second": 2, "third": 3}
_ORDINAL_RE_HI = re.compile(r"\b(pehla|pehli|doosra|dusra|teesra|tisra)\b", re.IGNORECASE)
_ORDINALS_HI = {"pehla": 1, "pehli": 1, "doosra": 2, "dusra": 2, "teesra": 3, "tisra": 3}
_NUMERIC_SELECTION_RE = re.compile(r"(?:option\s*)?(\d+)", re.IGNORECASE)
_DOCK_SELECTION_RE = re.compile(
    r"\b(?:book|confirm|hold|choose|select|take)\s+"
    r"(?:(?:the\s+)?(?:slot|dock)\s+)?(?:dock\s+)?([A-Za-z]\d{1,2})\b",
    re.IGNORECASE,
)

# "baje" = Hindi for "o'clock". Hindi puts the time before the verb
# ("11 baje pahunchunga"), so this is matched on its own and then
# classified by what's nearby, rather than anchored to a verb like the
# English "reach/arrive/eta ... <time>" pattern below.
_BAJE_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*baje\b", re.IGNORECASE)
_LEAVE_WORDS_HI = ["nikal", "nikalna", "chalna hai", "nikalna hai"]
_AFTER_WORDS_HI = ["baad", "uske baad", "ke baad"]

_PM_CONTEXT_WORDS = ["evening", "tonight", "night", "shaam", "sham", "raat", "dopahar"]


def _to_24h(h: int, m: int, ap: Optional[str], pm_context: bool = False,
            current_hour: Optional[int] = None) -> str:
    h = int(h)
    if ap:
        ap = ap.lower()
        if ap == "pm" and h != 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
    elif pm_context and 1 <= h <= 8:
        # "Evening traffic. ETA 6:30." / "Shaam ko 6:30 tak pahunch jaunga"
        # has no am/pm marker, but the context makes it unambiguous.
        h += 12
    elif current_hour is not None and 1 <= h <= 8 and current_hour > h:
        # Hindi 12-hour time ("1 baje") carries no am/pm marker at all, and
        # drivers rarely add one. If the conversation's own current time of
        # day has already passed that bare hour once today (e.g. it's 9 AM
        # and the driver says "1 baje"), the only sensible reading left is
        # the afternoon/evening one. Documented limitation (problem
        # definition sheet): a bare early-morning hour mentioned before
        # that hour has passed is still read as-is and could be mis-parsed.
        h += 12
    return f"{h:02d}:{m:02d}"


def _classify_baje_matches(low: str, pm: ParsedMessage, pm_context: bool,
                            current_hour: Optional[int]) -> None:
    for m in _BAJE_RE.finditer(low):
        hh = int(m.group(1))
        mm = int(m.group(2) or 0)
        before = low[max(0, m.start() - 20):m.start()]
        after = low[m.end():m.end() + 20]
        ts = _to_24h(hh, mm, None, pm_context=pm_context, current_hour=current_hour)
        # "Leave by" phrasing can read either way in natural Hindi word
        # order -- "nikalna hai 1:30 baje tak" or (more common) "1:30 baje
        # tak nikalna hai" -- so both sides of the match are checked.
        if any(w in before or w in after for w in _LEAVE_WORDS_HI) and pm.latest_acceptable_hhmm is None:
            pm.latest_acceptable_hhmm = ts
        elif any(w in after for w in _AFTER_WORDS_HI) and pm.selection_time_hhmm is None:
            pm.selection_time_hhmm = ts
            pm.wants_options_only = True
        elif pm.explicit_time_hhmm is None:
            pm.explicit_time_hhmm = ts
            pm.reports_delay = True


def parse_driver_message(text: str, current_hour: Optional[int] = None) -> ParsedMessage:
    """current_hour: the conversation's current simulated hour-of-day (0-23),
    used only to resolve a bare Hindi hour with no am/pm marker (see
    _to_24h). Optional -- omitting it just disables that one heuristic."""
    t = text.strip()
    low = t.lower()
    pm = ParsedMessage(raw_text=t)
    pm_context = any(w in low for w in _PM_CONTEXT_WORDS)

    for code, keywords in _REASON_KEYWORDS.items():
        if any(k in low for k in keywords):
            pm.reason_code = code
            break

    if any(w in low for w in _CONFIRM_WORDS):
        pm.wants_confirmation = True
    if any(w in low for w in _DECLINE_WORDS):
        pm.wants_decline = True
    if any(w in low for w in _ASK_ONLY_WORDS) and not pm.wants_confirmation:
        pm.wants_options_only = True
    if any(w in low for w in _STATUS_CHECK_WORDS):
        pm.is_status_check = True
    if any(w in low for w in _SECOND_PICKUP_WORDS):
        pm.mentions_second_pickup = True

    m = _ORDINAL_RE.search(low)
    if m:
        pm.selection_ordinal = _ORDINALS[m.group(1)]
    else:
        m_hi = _ORDINAL_RE_HI.search(low)
        if m_hi:
            pm.selection_ordinal = _ORDINALS_HI[m_hi.group(1).lower()]

    if pm.selection_ordinal is None:
        numeric_selection = _NUMERIC_SELECTION_RE.fullmatch(low)
        if numeric_selection:
            pm.selection_ordinal = int(numeric_selection.group(1))
    if pm.selection_ordinal is not None:
        pm.wants_confirmation = True

    dock_selection = _DOCK_SELECTION_RE.search(low)
    if dock_selection:
        pm.selection_dock_code = dock_selection.group(1).upper()
        pm.wants_confirmation = True

    # Hindi "X baje" time mentions, classified by nearby context, first --
    # they are the more specific signal (an exact clock time).
    _classify_baje_matches(low, pm, pm_context, current_hour)

    by_m = _BY_RE.search(low)
    if by_m and pm.latest_acceptable_hhmm is None:
        pm.latest_acceptable_hhmm = _to_24h(int(by_m.group(1)), int(by_m.group(2) or 0), by_m.group(3),
                                             current_hour=current_hour)

    after_m = _AFTER_RE.search(low)
    if after_m and pm.selection_time_hhmm is None:
        pm.selection_time_hhmm = _to_24h(int(after_m.group(1)), int(after_m.group(2) or 0), after_m.group(3),
                                          current_hour=current_hour)
        pm.wants_options_only = True

    delay_min_m = _DELAY_MIN_RE.search(low)
    delay_hr_m = _DELAY_HOUR_RE.search(low)
    delay_ghanta_m = _DELAY_GHANTA_RE.search(low)
    if delay_min_m:
        pm.delay_minutes = int(delay_min_m.group(1))
        pm.reports_delay = True
    elif delay_hr_m:
        word = delay_hr_m.group(1).lower()
        qty = _WORD_NUMBERS.get(word, None)
        if qty is None:
            try:
                qty = float(word)
            except ValueError:
                qty = 1.0
        pm.delay_minutes = int(round(qty * 60))
        pm.reports_delay = True
    elif delay_ghanta_m:
        word = delay_ghanta_m.group(1).lower()
        qty = _HINDI_NUMBERS.get(word, None)
        if qty is None:
            try:
                qty = float(word)
            except ValueError:
                qty = 1.0
        pm.delay_minutes = int(round(qty * 60))
        pm.reports_delay = True

    if pm.explicit_time_hhmm is None and pm.selection_time_hhmm is None:
        arrival_phrase = re.search(
            r"\b(?:reach(?:ing)?|arriv\w*|eta|pahunch\w*|pahoch\w*)\D{0,12}?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
            low,
        )
        if arrival_phrase:
            pm.explicit_time_hhmm = _to_24h(
                int(arrival_phrase.group(1)), int(arrival_phrase.group(2) or 0), arrival_phrase.group(3),
                pm_context=pm_context, current_hour=current_hour,
            )
            pm.reports_delay = True

    if not pm.reports_delay and any(w in low for w in _DELAY_SIGNAL_WORDS):
        # A delay is clearly being reported ("der ho gayi" / "running late")
        # but with no number or time attached yet -- the conversation layer
        # will ask for one rather than treating this as an unrecognised message.
        pm.reports_delay = True

    if pm.reports_delay and pm.delay_minutes is not None and not pm.explicit_time_hhmm:
        has_arrival_verb = any(w in low for w in ["reach", "arriv", "eta", "pahunch", "pahoch"])
        if not has_arrival_verb:
            pm.ambiguous_duration = True

    return pm
