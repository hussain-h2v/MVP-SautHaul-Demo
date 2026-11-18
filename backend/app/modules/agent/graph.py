"""The driver conversation graph (LangGraph). One inbound WhatsApp message = one run; state is persisted per thread by a
PostgreSQL checkpointer, so a conversation resumes where it left off.

Nodes: identify_driver, safety, escalate_safety, guard, out_of_scope, escalated_reply, resolve_shipment, classify_intent,
extract_facts, ask_missing, record_eta, find_options, present_options, wait_for_choice, place_hold, notify_coordinator,
wait_for_decision, inform_driver, unknown_reply, escalate.

Rules: facts the database already holds are never asked; a shipment is never guessed (ambiguous -> ask with a list);
low confidence after one clarifying question escalates; the bot never promises or confirms a slot (only the booking
service does, and the bot then reports it); times, dates and dock codes come from code into catalogue strings."""
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.core.errors import ConflictError, SlotTakenError, SlotUnavailableError
from app.modules.agent import guards, parse
from app.modules.agent.catalogue import STRINGS, t
from app.modules.agent.tools import AgentTools, friendly, to_local
from app.modules.ai import tasks as ai_tasks
from app.modules.booking import engine
from app.modules.exceptions import service as exceptions_service

MAX_TURNS = 60
MAX_CLARIFICATIONS = 6
MENU_ROWS = [("menu:delay", "menu_delay"), ("menu:options", "menu_options"), ("menu:status", "menu_status"),
             ("menu:gate", "menu_gate"), ("menu:human", "menu_human")]
CAUSE_TO_EXC = {"BREAKDOWN": "BREAKDOWN", "TRAFFIC": "TRAFFIC", "WEATHER": "WEATHER", "OTHER": "DELAY"}
CAUSE_TO_ETA = {"BREAKDOWN": "BREAKDOWN", "TRAFFIC": "TRAFFIC", "WEATHER": "WEATHER", "OTHER": "OTHER"}
SEVERITY = {"CRITICAL": "CRITICAL", "HIGH": "HIGH", "NORMAL": "MEDIUM", "LOW": "LOW"}


class AgentState(TypedDict, total=False):
    inbound: dict
    driver_id: str
    thread_id: str
    name: str
    language: str
    pref_language: str
    shipments: list
    shipment_id: str | None
    shipment_code: str | None
    tz: str
    facility: str
    stage: str | None
    facts: dict
    exception_id: str | None
    offered: list
    request_id: str | None
    turns: int
    clarifications: int
    unknown_count: int
    retries: dict
    pending_text: str | None
    intent: str | None
    review: bool
    escalated_now: bool
    esc_reason: str | None
    escalation_id: str | None
    outbound: list
    next: str | None
    phone_line: str
    choice: str | None
    retry: str | None
    ai_off: bool
    hold_pick: dict
    hold_id: str
    hold_minutes: int
    missing: str | None


# ---------------------------------------------------------------- message builders
def text(state, key, purpose="", **kw) -> dict:
    return {"kind": "text", "text": t(state["language"], key, **kw), "purpose": purpose or key}


def buttons(state, key, items: list[tuple[str, str]], purpose="", **kw) -> dict:
    return {"kind": "buttons", "text": t(state["language"], key, **kw), "purpose": purpose or key,
            "buttons": [{"id": i, "title": t(state["language"], tk)} for i, tk in items]}


def menu(state, intro_key="menu", **kw) -> dict:
    return {"kind": "list", "text": t(state["language"], intro_key, **kw), "purpose": "menu", "list_button": t(state["language"], "menu_button"),
            "rows": [{"id": i, "title": t(state["language"], k), "description": t(state["language"], k + "_d")} for i, k in MENU_ROWS]}


def say(state, *msgs: dict) -> dict:
    return {"outbound": [*state.get("outbound", []), *msgs]}


def now_of(state) -> datetime:
    return datetime.fromisoformat(state["inbound"]["now"])


def build(tools: AgentTools) -> Any:
    db = tools.s.db

    # ------------------------------------------------------------ identify driver
    async def identify_driver(state: AgentState) -> dict:
        ctx = await tools.get_driver_context()
        inbound = state["inbound"]
        txt = inbound.get("text") or ""
        pref = ctx["language"] if ctx["language"] in STRINGS else "en"
        lang = parse.detect_language(txt, pref) if txt else state.get("language") or pref
        if lang not in STRINGS:
            lang = pref
        ships = [{"id": str(x["id"]), "code": x["code"], "facility": x["facility"], "eta": x["eta"].isoformat(), "status": x["status"]}
                 for x in ctx["shipments"]]
        phone = await tools.coordinator_phone()
        out = {"driver_id": str(tools.s.driver_id), "thread_id": str(tools.s.thread_id), "name": ctx["name"], "language": lang,
               "pref_language": pref, "shipments": ships, "outbound": [], "intent": None, "review": False, "escalated_now": False,
               "esc_reason": None, "next": None, "retry": None, "choice": None, "missing": None, "ai_off": False, "turns": state.get("turns", 0) + 1, "facts": state.get("facts") or {},
               "retries": state.get("retries") or {}, "phone_line": f": {phone}" if phone else ""}
        return out

    # ------------------------------------------------------------ safety, guard, out of scope
    async def safety(state: AgentState) -> dict:
        txt = state["inbound"].get("text") or ""
        return {"next": "escalate_safety" if guards.is_safety(txt) else None}

    async def escalate_safety(state: AgentState) -> dict:
        await _ensure_shipment_for_escalation(state)
        esc = await tools.create_escalation("SAFETY", "Driver reported a possible safety issue. Call the driver; the bot makes no safety decision.",
                                            {"driver_message": (state["inbound"].get("text") or "")[:300]}, _uuid(state.get("exception_id")))
        return {**say(state, text(state, "safety", phone_line=state["phone_line"])), "stage": "escalated", "escalated_now": True,
                "escalation_id": str(esc.id), "intent": "safety_issue", "review": True}

    async def guard(state: AgentState) -> dict:
        txt = state["inbound"].get("text") or ""
        if state["turns"] > MAX_TURNS:
            return {"next": "escalate", "esc_reason": "TURN_LIMIT"}
        if txt and guards.is_dispute(txt):
            return {"next": "out_of_scope"}
        review = bool(txt and guards.looks_like_injection(txt))
        button = state["inbound"].get("button_id") or ""
        if state.get("stage") == "escalated" and not button.startswith("menu:"):
            return {"next": "escalated_reply", "review": review}
        if button == "menu:human":
            return {"next": "escalate", "esc_reason": "DRIVER_REQUEST"}
        return {"next": "resolve_shipment", "review": review, "stage": None if state.get("stage") == "escalated" else state.get("stage")}

    async def out_of_scope(state: AgentState) -> dict:
        await _ensure_shipment_for_escalation(state)
        esc = await tools.create_escalation("DISPUTE", "Driver asked about penalties, compensation or a dispute. The bot does not handle these.",
                                            {"driver_message": (state["inbound"].get("text") or "")[:300]}, _uuid(state.get("exception_id")))
        return {**say(state, text(state, "out_of_scope")), "stage": "escalated", "escalated_now": True, "escalation_id": str(esc.id), "review": True}

    async def escalated_reply(state: AgentState) -> dict:
        return {**say(state, text(state, "escalated_wait")), "review": True}

    async def escalate(state: AgentState) -> dict:
        await _ensure_shipment_for_escalation(state)
        reason = state.get("esc_reason") or "LOW_CONFIDENCE"
        esc = await tools.create_escalation(reason, f"The assistant could not resolve this conversation ({reason.replace('_', ' ').lower()}).",
                                            {"facts": state.get("facts"), "stage": state.get("stage")}, _uuid(state.get("exception_id")))
        return {**say(state, text(state, "needs_person")), "stage": "escalated", "escalated_now": True, "escalation_id": str(esc.id)}

    async def _ensure_shipment_for_escalation(state: AgentState) -> None:
        if tools.s.shipment_id is None and state.get("shipments"):
            tools.s.shipment_id = UUID(state["shipments"][0]["id"])

    # ------------------------------------------------------------ resolve shipment (never guess)
    async def resolve_shipment(state: AgentState) -> dict:
        ships = state.get("shipments", [])
        button = state["inbound"].get("button_id") or ""
        txt = state["inbound"].get("text") or ""
        bound = state.get("shipment_id")
        if bound:
            from app.modules.shipments import service as shipments_service

            s = (await shipments_service.get_many(db, [UUID(bound)])).get(UUID(bound))
            if s is not None and s.current_status == "CANCELLED":
                return {**say(state, text(state, "shipment_cancelled", code=s.code, phone_line=state["phone_line"])), "shipment_id": None,
                        "next": "end", "stage": None}
            if not any(x["id"] == bound for x in ships):
                bound = None
        chosen = None
        if button.startswith("ship:"):
            chosen = next((x for x in ships if x["code"] == button[5:]), None)
        elif state.get("stage") == "awaiting_shipment":
            chosen = next((x for x in ships if x["code"].lower() in txt.lower()), None)
        if chosen:
            bound = chosen["id"]
        elif bound is None and len(ships) == 1:
            bound = ships[0]["id"]
        if bound is None:
            if not ships:
                return {**say(state, text(state, "no_shipment", phone_line=state["phone_line"])), "next": "end", "stage": None}
            pending = state.get("pending_text") or (txt if state.get("stage") != "awaiting_shipment" else None)
            rows = [{"id": f"ship:{x['code']}", "title": x["code"], "description": x["facility"][:72]} for x in ships[:10]]
            msg = {"kind": "list", "text": t(state["language"], "which_shipment"), "purpose": "which_shipment",
                   "list_button": t(state["language"], "which_shipment_button"), "rows": rows}
            return {**say(state, msg), "stage": "awaiting_shipment", "pending_text": pending or None, "next": "end"}
        tools.s.shipment_id = UUID(bound)
        await tools.set_thread(shipment_id=UUID(bound))
        fac = await tools.facility()
        code = next(x["code"] for x in ships if x["id"] == bound)
        out: dict = {"shipment_id": bound, "shipment_code": code, "tz": fac.timezone, "facility": fac.facility_name, "next": None}
        if state.get("stage") == "awaiting_shipment":
            out["stage"] = None
            if state.get("pending_text"):
                out["inbound"] = {**state["inbound"], "text": state["pending_text"], "button_id": None}
                out["pending_text"] = None
        return out

    # ------------------------------------------------------------ classify intent
    async def classify_intent(state: AgentState) -> dict:
        inbound, facts, stage = state["inbound"], dict(state.get("facts") or {}), state.get("stage")
        button, txt, now = inbound.get("button_id") or "", inbound.get("text") or "", now_of(state)
        retries = dict(state.get("retries") or {})
        tz = state["tz"]

        def done(intent: str, **extra) -> dict:
            return {"intent": intent, "facts": facts, "retries": retries, "unknown_count": 0, "next": None, **extra}

        if button.startswith("menu:"):
            intent = {"menu:delay": "report_delay", "menu:options": "ask_options", "menu:status": "ask_status", "menu:gate": "ask_gate_info"}.get(button)
            if intent == "report_delay":
                facts = {}
                retries = {}
            return done(intent or "unknown", stage=None)
        if button in ("offer_accept", "offer_decline"):
            return done("accept_suggestion" if button == "offer_accept" else "decline_suggestion")
        if button.startswith("opt:"):
            return done("choose_option", choice=button[4:])
        if button.startswith("delay:"):
            facts["meaning"] = button[6:]
            return done("report_delay")
        if button.startswith("cause:"):
            facts["cause"], facts["cause_asked"] = button[6:], True
            return done("report_delay")
        if button == "finish:any":
            facts["finish_asked"] = True
            return done("report_delay")

        # answers to the bot's own question: parsed by code, no model needed
        if stage in ("awaiting_eta", "awaiting_delay_meaning", "awaiting_cause", "awaiting_finish") and txt:
            if stage == "awaiting_eta":
                eta = parse.parse_time(txt, now, tz)
                mins = parse.parse_minutes(txt)
                if eta is not None:
                    facts["eta_iso"] = eta.isoformat()
                elif mins is not None:
                    facts["eta_iso"], facts["eta_relative"] = (now + timedelta(minutes=mins)).isoformat(), True
                else:
                    retries["awaiting_eta"] = retries.get("awaiting_eta", 0) + 1
                    return done("report_delay") | {"retry": "awaiting_eta"}
            elif stage == "awaiting_delay_meaning":
                m = parse.parse_delay_meaning(txt)
                if m is None:
                    retries["awaiting_delay_meaning"] = retries.get("awaiting_delay_meaning", 0) + 1
                    return done("report_delay") | {"retry": "awaiting_delay_meaning"}
                facts["meaning"] = m
            elif stage == "awaiting_cause":
                facts["cause"], facts["cause_asked"] = parse.parse_cause(txt) or "OTHER", True
            else:
                facts["finish_asked"] = True
                f = parse.parse_time(txt, now, tz)
                if f is not None:
                    facts["finish_iso"] = f.isoformat()
            return done("report_delay")

        if stage == "awaiting_choice" and txt:
            n = parse.parse_choice_number(txt, len(state.get("offered") or []))
            if n:
                return done("choose_option", choice=str(n))

        suggested = await tools.latest_suggested_request() if tools.s.shipment_id else None
        if suggested is not None and txt and (parse.is_yes(txt) or parse.is_no(txt)):
            return done("accept_suggestion" if parse.is_yes(txt) else "decline_suggestion")

        if not txt:
            return {"intent": "unknown", "next": None, "unknown_count": state.get("unknown_count", 0)}
        if state.get("review"):  # looks like prompt injection: never sent to a model
            return {"intent": "unknown", "next": None, "unknown_count": state.get("unknown_count", 0)}
        ai = await ai_tasks.classify_intent(txt, state["language"], [state.get("name", "")])
        det_minutes, det_eta, det_cause = parse.parse_minutes(txt), parse.parse_time(txt, now, tz), parse.parse_cause(txt)
        if ai is None or ai.confidence < 0.5 or ai.intent == "unknown":
            if det_minutes is not None or (det_eta is not None and ai is not None):
                intent = "report_delay"  # a stated duration is unambiguous even when the model is unsure
            else:
                return {"intent": "unknown", "next": None, "unknown_count": state.get("unknown_count", 0), "ai_off": ai is None}
        else:
            intent = ai.intent
        if intent == "safety_issue":
            return {"intent": intent, "next": "escalate_safety", "facts": facts}
        if intent == "ask_options":  # "slots after 4 pm": an asked-for earliest time is a constraint, not a delay report
            if det_eta is not None:
                facts["eta_iso"] = det_eta.isoformat()
            elif ai is not None and ai.eta_time:
                e = parse.parse_time(ai.eta_time, now, tz)
                if e:
                    facts["eta_iso"] = e.isoformat()
        if intent == "report_delay":
            if ai is not None:
                if ai.delay_minutes:
                    facts["minutes"] = ai.delay_minutes
                if ai.delay_is_repair_time is True:
                    facts["meaning"] = "repair"
                if ai.eta_time and not facts.get("eta_iso"):
                    e = parse.parse_time(ai.eta_time, now, tz)
                    if e:
                        facts["eta_iso"] = e.isoformat()
                if ai.cause in CAUSE_TO_EXC:
                    facts["cause"] = ai.cause
            if det_minutes and not facts.get("minutes"):
                facts["minutes"] = det_minutes
            if det_eta and not facts.get("eta_iso"):
                facts["eta_iso"] = det_eta.isoformat()
            if det_cause and not facts.get("cause"):
                facts["cause"] = det_cause
            if facts.get("cause"):
                facts["cause_asked"] = True
            f = parse.parse_time(ai.latest_finish_time, now, tz) if ai is not None and ai.latest_finish_time else None
            if f:
                facts["finish_iso"], facts["finish_asked"] = f.isoformat(), True
        return done(intent)

    # ------------------------------------------------------------ report delay: extract facts, ask, record ETA
    async def extract_facts(state: AgentState) -> dict:
        facts = dict(state.get("facts") or {})
        tz, now = state["tz"], now_of(state)
        out: dict = {"facts": facts, "next": None}
        if state.get("exception_id") is None:
            from app.modules.shipments import service as shipments_service

            s = (await shipments_service.get_many(db, [tools.s.shipment_id]))[tools.s.shipment_id]
            exc = await exceptions_service.open_for_thread(db, tools.s.thread_id, tools.s.shipment_id)
            if exc is None:
                exc = await exceptions_service.create_from_agent(
                    db, shipment_id=s.id, driver_id=tools.s.driver_id, thread_id=tools.s.thread_id,
                    exception_type=CAUSE_TO_EXC.get(facts.get("cause") or "", "DELAY"), severity=SEVERITY.get(s.priority_code, "MEDIUM"),
                    description="Driver reported a delay on WhatsApp; facts are being collected by the assistant.")
            out["exception_id"] = str(exc.id)
        if state.get("retry"):
            return {**out, "missing": "retry"}
        missing = None
        if not facts.get("eta_iso"):
            if facts.get("minutes") and not facts.get("meaning"):
                missing = "delay_meaning"
            elif facts.get("minutes") and facts.get("meaning"):
                if facts["meaning"] == "total":
                    base = await _base_eta()
                    facts["eta_iso"] = (base + timedelta(minutes=facts["minutes"])).isoformat()
                else:
                    facts["eta_iso"], facts["eta_vague"] = (now + timedelta(minutes=facts["minutes"])).isoformat(), True
            else:
                missing = "eta"
        if missing is None and not facts.get("cause") and not facts.get("cause_asked"):
            missing = "cause"
        if missing is None and not facts.get("finish_iso") and not facts.get("finish_asked"):
            missing = "finish"
        out["missing"] = missing
        _ = tz
        return out

    async def _base_eta() -> datetime:
        from app.modules.eta import service as eta_service

        e = await eta_service.effective_eta(db, tools.s.shipment_id)
        return e.ts

    async def ask_missing(state: AgentState) -> dict:
        missing = state.get("missing")
        clar = state.get("clarifications", 0) + 1
        facts = dict(state.get("facts") or {})
        if missing == "retry":
            stage = state["retry"] if state.get("retry") else state.get("stage")
            if (state.get("retries") or {}).get(stage, 0) >= 2:
                return {"next": "escalate", "esc_reason": "LOW_CONFIDENCE"}
            if stage == "awaiting_eta":
                msg = text(state, "ask_eta_retry", facility=state["facility"])
            else:
                msg = buttons(state, "ask_delay_meaning", [("delay:repair", "b_repair"), ("delay:total", "b_total")],
                              minutes=facts.get("minutes", ""), facility=state["facility"])
            return {**say(state, msg), "clarifications": clar, "stage": stage}
        if clar > MAX_CLARIFICATIONS:
            return {"next": "escalate", "esc_reason": "TOO_MANY_CLARIFICATIONS"}
        await exceptions_service.set_status(db, _uuid(state.get("exception_id")), "NEEDS_INFORMATION")
        if missing == "delay_meaning":
            m = buttons(state, "ask_delay_meaning", [("delay:repair", "b_repair"), ("delay:total", "b_total")], minutes=facts["minutes"], facility=state["facility"])
            return {**say(state, m), "stage": "awaiting_delay_meaning", "clarifications": clar}
        if missing == "eta":
            return {**say(state, text(state, "ask_eta", facility=state["facility"])), "stage": "awaiting_eta", "clarifications": clar}
        if missing == "cause":
            m = buttons(state, "ask_cause", [("cause:TRAFFIC", "b_traffic"), ("cause:BREAKDOWN", "b_breakdown"), ("cause:OTHER", "b_other")])
            return {**say(state, m), "stage": "awaiting_cause", "clarifications": clar}
        m = buttons(state, "ask_finish", [("finish:any", "b_any_time")])
        return {**say(state, m), "stage": "awaiting_finish", "clarifications": clar}

    async def record_eta(state: AgentState) -> dict:
        facts = dict(state["facts"])
        eta = datetime.fromisoformat(facts["eta_iso"])
        confidence = "LOW" if facts.get("eta_vague") or facts.get("eta_relative") else "MEDIUM"
        await tools.record_eta_update(eta, confidence=confidence, reason=CAUSE_TO_ETA.get(facts.get("cause") or ""), note="Reported on WhatsApp")
        exc = await exceptions_service.get_exception(db, _uuid(state.get("exception_id")))
        if exc is not None:
            exc.declared_eta_ts = eta
            exc.reported_delay_min = facts.get("minutes")
            if facts.get("finish_iso"):
                exc.latest_acceptable_ts = datetime.fromisoformat(facts["finish_iso"])
            if facts.get("cause"):
                exc.exception_type = CAUSE_TO_EXC.get(facts["cause"], "DELAY")
            exc.exception_status = "OPEN"
            exc.description = (f"Driver reports arrival around {to_local(eta, state['tz'], True)}"
                               + (f" ({facts['cause'].lower()})" if facts.get("cause") else "") + ".")
        return {**say(state, text(state, "eta_recorded", facility=state["facility"], eta=friendly(eta, state["tz"], now_of(state)))), "next": None}

    # ------------------------------------------------------------ options
    async def find_options(state: AgentState) -> dict:
        facts = state.get("facts") or {}
        eta = datetime.fromisoformat(facts["eta_iso"]) if facts.get("eta_iso") else None
        finish = datetime.fromisoformat(facts["finish_iso"]) if facts.get("finish_iso") else None
        res = await tools.find_slot_options(eta, finish, 5)
        if not res.options:
            await _ensure_shipment_for_escalation(state)
            esc = await tools.create_escalation("NO_FEASIBLE_SLOT", "No compatible, free slot was found after the driver's ETA.",
                                                {"rejections": res.rejections, "latest_finish": finish.isoformat() if finish else None,
                                                 "eta": eta.isoformat() if eta else None}, _uuid(state.get("exception_id")))
            return {**say(state, text(state, "no_options")), "stage": "escalated", "escalated_now": True, "escalation_id": str(esc.id),
                    "offered": [], "next": "end"}
        offered = [{"n": i, "slot_ids": [str(x) for x in o.slot_ids], "start": o.start.isoformat(), "end": o.end.isoformat(),
                    "dock": o.dock_code, "approval": o.needs_planner_approval} for i, o in enumerate(res.options, start=1)]
        return {"offered": offered, "next": None}

    async def present_options(state: AgentState) -> dict:
        tz = state["tz"]
        rows = []
        for o in state["offered"]:
            s, e = datetime.fromisoformat(o["start"]), datetime.fromisoformat(o["end"])
            rows.append({"id": f"opt:{o['n']}", "title": t(state["language"], "option_title", start=friendly(s, tz, now_of(state)), end=to_local(e, tz)),
                         "description": t(state["language"], "option_desc_approval" if o["approval"] else "option_desc", dock=o["dock"])})
        rows.append({"id": "opt:none", "title": t(state["language"], "option_none"), "description": t(state["language"], "option_none_d")})
        msg = {"kind": "list", "text": t(state["language"], "options_intro"), "purpose": "options",
               "list_button": t(state["language"], "options_button"), "rows": rows}
        await exceptions_service.set_status(db, _uuid(state.get("exception_id")), "SLOT_OPTIONS_SHARED")
        return {**say(state, msg), "stage": "awaiting_choice"}

    async def wait_for_choice(state: AgentState) -> dict:
        return {"stage": "awaiting_choice"}

    async def place_hold(state: AgentState) -> dict:
        offered = state.get("offered") or []
        choice = state["inbound"].get("button_id", "")[4:] if (state["inbound"].get("button_id") or "").startswith("opt:") else None
        choice = choice or (state.get("choice"))
        if choice == "none":
            await _ensure_shipment_for_escalation(state)
            esc = await tools.create_escalation("NO_ACCEPTABLE_OPTION", "The driver declined every option shown.",
                                                {"offered": offered}, _uuid(state.get("exception_id")))
            return {**say(state, text(state, "none_chosen")), "stage": "escalated", "escalated_now": True, "escalation_id": str(esc.id), "next": "end"}
        pick = next((o for o in offered if str(o["n"]) == str(choice)), None)
        if pick is None:
            return {"next": "find_options"}  # stale or missing offer list: refresh instead of guessing
        try:
            hold = await tools.place_hold([UUID(x) for x in pick["slot_ids"]], _uuid(state.get("exception_id")))
        except (SlotTakenError, SlotUnavailableError, ConflictError):
            return {**say(state, text(state, "option_gone")), "next": "find_options"}
        return {"hold_pick": pick, "hold_id": str(hold.id), "hold_minutes": max(1, int((hold.expires_at - now_of(state)).total_seconds() // 60)),
                "next": None}

    async def notify_coordinator(state: AgentState) -> dict:
        pick = state["hold_pick"]
        req = await engine.create_request(db, tools.s.shipment_id, hold_id=UUID(state["hold_id"]), exception_id=_uuid(state.get("exception_id")),
                                          reason_code="DRIVER_DELAY")
        await exceptions_service.set_status(db, _uuid(state.get("exception_id")), "WAITING_CONFIRMATION")
        s, e, tz = datetime.fromisoformat(pick["start"]), datetime.fromisoformat(pick["end"]), state["tz"]
        slot_code = pick["slot_ids"][0]
        sl = await _slot_code(UUID(slot_code))
        return {**say(state, text(state, "hold_placed", slot=sl, dock=pick["dock"], start=friendly(s, tz, now_of(state)), end=to_local(e, tz),
                                  minutes=state["hold_minutes"])), "request_id": str(req.id), "stage": "awaiting_decision", "next": None}

    async def _slot_code(slot_id: UUID) -> str:
        from app.modules.booking import readers

        return (await readers.slots_by_ids(db, [slot_id]))[slot_id].code

    async def wait_for_decision(state: AgentState) -> dict:
        return {"stage": "awaiting_decision"}

    # ------------------------------------------------------------ inform driver: status, gate, arrival, offers
    async def inform_driver(state: AgentState) -> dict:
        intent, tz, now = state["intent"], state["tz"], now_of(state)
        if intent == "ask_status":
            st = await tools.get_shipment_status()
            if st["held"] or st["request_status"]:
                h = st["held"] or {}
                return {**say(state, text(state, "request_pending", slot=h.get("code", "-"), dock=h.get("dock", "-"),
                                          start=friendly(h.get("start"), tz, now))), "next": None}
            if st["appointment"]:
                a = st["appointment"]
                label = t(state["language"], f"status_{a['status'].lower()}")
                return {**say(state, text(state, "status_appt", slot=a["code"], dock=a["dock"], start=friendly(a["start"], tz, now),
                                          end=to_local(a["end"], tz), status=label, eta=friendly(st["eta"], tz, now)))}
            return {**say(state, text(state, "status_none", eta=friendly(st["eta"], tz, now)))}
        if intent == "ask_gate_info":
            g = await tools.get_gate_info()
            if g["contact"]:
                return {**say(state, text(state, "gate_info", facility=g["facility"], contact=g["contact"], hours=g["hours"]))}
            return {**say(state, text(state, "gate_none", facility=g["facility"], phone_line=state["phone_line"]))}
        if intent == "report_arrival":
            await tools.record_arrival()
            return {**say(state, text(state, "arrival_ack"))}
        return await _offer_answer(state, accept=intent == "accept_suggestion")

    async def _offer_answer(state: AgentState, accept: bool) -> dict:
        req = await tools.latest_suggested_request()
        if req is None:
            if accept and await tools.latest_request_status() == "expired":  # the offer lapsed while the driver thought about it
                return {**say(state, text(state, "offer_expired")), "next": "find_options"}
            return {**say(state, text(state, "no_offer"))}
        tz, now = state["tz"], now_of(state)
        if not accept:
            await engine.reject_request(db, req.id, req.decided_by, "Driver declined the suggested slot", now=now)
            await _ensure_shipment_for_escalation(state)
            esc = await tools.create_escalation("DRIVER_DECLINED_OFFER", "The driver declined the slot the coordinator suggested.", {}, req.exception_id)
            return {**say(state, text(state, "offer_declined")), "stage": "escalated", "escalated_now": True, "escalation_id": str(esc.id)}
        try:
            appt = await engine.approve_request(db, req.id, req.decided_by, now=now)
        except (SlotTakenError, SlotUnavailableError, ConflictError):
            return {**say(state, text(state, "offer_expired")), "next": "find_options"}
        sl = await _slot_vars(appt.slot_id, tz, now)
        key = "offer_pending" if appt.appointment_status == "PENDING_CONFIRMATION" else "offer_confirmed"
        return {**say(state, text(state, key, **sl)), "stage": None}

    async def _slot_vars(slot_id: UUID, tz: str, now: datetime) -> dict:
        from app.modules.booking import readers

        sl = (await readers.slots_by_ids(db, [slot_id]))[slot_id]
        dock = (await readers.docks_by_ids(db, [sl.dock_id]))[sl.dock_id]
        return {"slot": sl.code, "dock": dock.dock_code, "start": friendly(sl.slot_start_ts, tz, now), "end": to_local(sl.slot_end_ts, tz)}

    async def unknown_reply(state: AgentState) -> dict:
        count = state.get("unknown_count", 0) + 1
        if count >= 2:
            return {"next": "escalate", "esc_reason": "LOW_CONFIDENCE", "unknown_count": count}
        return {**say(state, menu(state, "unknown")), "unknown_count": count, "stage": None}

    # ------------------------------------------------------------ wiring
    def to(field: str, default: str = "end"):
        def route(state: AgentState) -> str:
            return state.get(field) or default
        return route

    g = StateGraph(AgentState)
    for name, fn in [("identify_driver", identify_driver), ("safety", safety), ("escalate_safety", escalate_safety), ("guard", guard),
                     ("out_of_scope", out_of_scope), ("escalated_reply", escalated_reply), ("escalate", escalate),
                     ("resolve_shipment", resolve_shipment), ("classify_intent", classify_intent), ("extract_facts", extract_facts),
                     ("ask_missing", ask_missing), ("record_eta", record_eta), ("find_options", find_options),
                     ("present_options", present_options), ("wait_for_choice", wait_for_choice), ("place_hold", place_hold),
                     ("notify_coordinator", notify_coordinator), ("wait_for_decision", wait_for_decision),
                     ("inform_driver", inform_driver), ("unknown_reply", unknown_reply)]:
        g.add_node(name, fn)
    g.add_edge(START, "identify_driver")
    g.add_edge("identify_driver", "safety")
    g.add_conditional_edges("safety", lambda s: s.get("next") or "guard", {"escalate_safety": "escalate_safety", "guard": "guard"})
    g.add_conditional_edges("guard", to("next", "resolve_shipment"), {"escalate": "escalate", "out_of_scope": "out_of_scope", "escalated_reply": "escalated_reply",
                                                                     "resolve_shipment": "resolve_shipment"})
    g.add_conditional_edges("resolve_shipment", lambda s: "end" if s.get("next") == "end" else "classify_intent", {"end": END, "classify_intent": "classify_intent"})

    def after_classify(s: AgentState) -> str:
        if s.get("next") == "escalate_safety":
            return "escalate_safety"
        return {"report_delay": "extract_facts", "ask_options": "find_options", "choose_option": "place_hold", "accept_suggestion": "inform_driver",
                "decline_suggestion": "inform_driver", "report_arrival": "inform_driver", "ask_status": "inform_driver",
                "ask_gate_info": "inform_driver"}.get(s.get("intent") or "unknown", "unknown_reply")

    g.add_conditional_edges("classify_intent", after_classify, {k: k for k in ["escalate_safety", "extract_facts", "find_options", "place_hold", "inform_driver", "unknown_reply"]})
    g.add_conditional_edges("extract_facts", lambda s: "ask_missing" if s.get("missing") else "record_eta", {"ask_missing": "ask_missing", "record_eta": "record_eta"})
    g.add_conditional_edges("ask_missing", lambda s: "escalate" if s.get("next") == "escalate" else "end", {"escalate": "escalate", "end": END})
    g.add_edge("record_eta", "find_options")
    g.add_conditional_edges("find_options", lambda s: "end" if s.get("next") == "end" else "present_options", {"end": END, "present_options": "present_options"})
    g.add_edge("present_options", "wait_for_choice")
    g.add_edge("wait_for_choice", END)
    g.add_conditional_edges("place_hold", lambda s: s.get("next") or "notify_coordinator", {"find_options": "find_options", "end": END, "notify_coordinator": "notify_coordinator"})
    g.add_edge("notify_coordinator", "wait_for_decision")
    g.add_edge("wait_for_decision", END)
    g.add_conditional_edges("inform_driver", lambda s: "find_options" if s.get("next") == "find_options" else "end", {"find_options": "find_options", "end": END})
    g.add_conditional_edges("unknown_reply", lambda s: "escalate" if s.get("next") == "escalate" else "end", {"escalate": "escalate", "end": END})
    for terminal in ("escalate_safety", "out_of_scope", "escalated_reply", "escalate"):
        g.add_edge(terminal, END)
    return g


def _uuid(v: str | None) -> UUID | None:
    return UUID(v) if v else None


_ = (UTC,)
