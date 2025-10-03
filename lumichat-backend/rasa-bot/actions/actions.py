# actions.py
# =============================================================================
# MERGED ACTIONS for Rasa 3.x  (Laravel-friendly)
# -----------------------------------------------------------------------------
# This file merges two previous action modules:
#   A) Numbered Response Selector + Safety Override
#   B) Appointment Flow (Cebuano/English helpers) + Coping Assist + Referral
#
# Clear section banners below show where each set starts/ends so you can
# easily maintain or extract them in the future.
#
# Drop-in usage:
#   - Save this as actions.py at your project root.
#   - Ensure endpoints.yml -> action_endpoint points to your actions server.
#   - Start with: `rasa run actions`
# =============================================================================

from __future__ import annotations

from typing import Any, Text, Dict, List, Optional
from datetime import datetime, timedelta
import os
import re

from rasa_sdk import Action, Tracker, FormValidationAction
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, EventType
from rasa_sdk.types import DomainDict

# =============================================================================
# SECTION A — Numbered Response Selector + Crisis Safety
# (ActionSelectNumberedResponse)
# =============================================================================

CRISIS_KEYWORDS = {
    "suicide", "kill myself", "end my life", "self harm", "self-harm",
    "i want to die", "i want to end it", "hurt myself"
}

class ActionSelectNumberedResponse(Action):
    def name(self) -> Text:
        return "action_select_numbered_response"

    def _latest_intent_name(self, tracker: Tracker) -> Text:
        return (tracker.latest_message.get("intent") or {}).get("name", "") or ""

    def _has_crisis_terms(self, text: Text) -> bool:
        t = (text or "").lower()
        return any(k in t for k in CRISIS_KEYWORDS)

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:
        # 1) Safety override via intent or keywords
        latest_intent = self._latest_intent_name(tracker)
        user_text = tracker.latest_message.get("text", "")

        if latest_intent == "safety_critical" or self._has_crisis_terms(user_text):
            if "utter_crisis" in (domain.get("responses") or {}):
                dispatcher.utter_message(response="utter_crisis")
            else:
                dispatcher.utter_message(text=(
                    "I'm concerned for your safety. If you're in immediate danger, "
                    "please call local emergency services now."
                ))
            return []

        # 2) Map <base>/pNNNN -> utter_<base>/pNNNN or <base> -> utter_<base>
        if "/" in latest_intent:
            base, suffix = latest_intent.split("/", 1)
            key = f"utter_{base}/{suffix}"
        else:
            base = latest_intent
            key = f"utter_{base}"

        responses: Dict[str, Any] = domain.get("responses") or {}

        # 3) Prefer numbered template; fallback to parent; then generic text
        if key in responses:
            dispatcher.utter_message(response=key)
        else:
            parent = f"utter_{base}"
            if parent in responses:
                dispatcher.utter_message(response=parent)
            else:
                dispatcher.utter_message(text="I'm here with you. Tell me a bit more about what you're feeling.")
        return []


# =============================================================================
# SECTION B — Helpers (Cebuano/English), Appointment Flow & Coping Assist
# =============================================================================

# ---- Optional dependency (graceful fallback if not installed) ----
try:
    from dateutil import parser as dateparser  # pip install python-dateutil
except Exception:  # pragma: no cover
    dateparser = None  # skip fuzzy parsing if missing

# ---- Cebuano / English normalization maps ----
CEB_DATE_MAP: Dict[str, str] = {
    "ugma": "tomorrow",
    "karon": "today",
    "unya": "later",
    "sunod semana": "next week",
}

EN_MISSPELLINGS: Dict[str, str] = {
    "tommorow": "tomorrow",
    "tomorow": "tomorrow",
    "tmrw": "tomorrow",
}

CEB_TIME_KEYWORDS: Dict[str, str] = {
    "buntag": "morning",
    "hapon": "afternoon",
    "udto": "noon",
    "gabii": "evening",
    "karon": "now",
}

def _lang(meta: Dict[str, Any]) -> Text:
    """Extract UI language from message metadata (default: 'en')."""
    try:
        return str(((meta.get("lumichat") or {}).get("lang") or "en")).lower()
    except Exception:
        return "en"


def _one(lang: Text, en: Text, ceb: Text) -> Text:
    """Pick English or Cebuano text by language code."""
    return ceb if lang == "ceb" else en


def _appointment_link() -> str:
    """
    Build appointment URL:
    - honors LUMICHAT_APPOINTMENT_URL if set
    - falls back to local route
    - ensures scheme is present
    """
    link = os.getenv("LUMICHAT_APPOINTMENT_URL") or "http://127.0.0.1:8000/appointment"
    if not re.match(r"^https?://", link):
        link = "https://" + link.lstrip("/")
    return link


def normalize_date_text(text: str) -> str:
    t = (text or "").strip().lower()
    if t in EN_MISSPELLINGS:
        t = EN_MISSPELLINGS[t]
    for k, v in CEB_DATE_MAP.items():
        if k in t:
            t = t.replace(k, v)
    return t


def normalize_time_text(text: str) -> str:
    t = (text or "").strip().lower()
    for k, v in CEB_TIME_KEYWORDS.items():
        if k in t:
            t = v
    return t.replace(" ", "")


def parse_date(value: str) -> Optional[str]:
    s = normalize_date_text(value)

    if s in {"today", "now"}:
        return datetime.now().date().isoformat()
    if s == "tomorrow":
        return (datetime.now() + timedelta(days=1)).date().isoformat()
    if s == "nextweek":
        return (datetime.now() + timedelta(days=7)).date().isoformat()

    if dateparser:
        try:
            dt = dateparser.parse(s, fuzzy=True, dayfirst=False)
            if dt:
                return dt.date().isoformat()
        except Exception:
            pass

    if re.search(r"\b(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|[a-z]{3,}\s+\d{1,2})\b", s):
        return s
    return None


def parse_time(value: str) -> Optional[str]:
    s = normalize_time_text(value)

    m = re.match(r"^(\d{1,2})(?::(\d{2}))?(am|pm)?$", s)
    if m:
        h = int(m.group(1))
        mins = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm:
            if ampm == "pm" and h != 12:
                h += 12
            if ampm == "am" and h == 12:
                h = 0
        if 0 <= h < 24 and 0 <= mins < 60:
            return f"{h:02d}:{mins:02d}"

    WORD_MAP = {
        "morning": "09:00",
        "noon": "12:00",
        "afternoon": "15:00",
        "evening": "18:00",
        "now": datetime.now().strftime("%H:%M"),
    }
    if s in WORD_MAP:
        return WORD_MAP[s]

    m2 = re.search(r"alas\s*(\d{1,2})\s*(?:sa)?\s*(buntag|hapon|gabii)", (value or "").lower())
    if m2:
        h = int(m2.group(1))
        part = m2.group(2)
        if part == "buntag":  # morning
            if h == 12:
                h = 0
        elif part in {"hapon", "gabii"}:  # afternoon/evening
            if h < 12:
                h += 12
        return f"{h:02d}:00"
    return None


def normalize_yes_no(value: Optional[str]) -> Text:
    v = (value or "").strip().lower()
    if v in {
        "yes","y","yep","yeah","yup","sure","ok","okay","okk","okie",
        "go ahead","please","yes please","proceed","sige","oo","oo, sige","oo sige"
    }:
        return "yes"
    if v in {"no","nope","nah","not now","maybe later","dili","ayaw"}:
        return "no"
    return v or ""


# ---- Reflective support ----
class ActionReflectiveSupport(Action):
    def name(self) -> Text:
        return "action_reflective_support"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: DomainDict) -> List[EventType]:
        intent = (tracker.latest_message.get("intent") or {}).get("name", "")
        lang = _lang(tracker.latest_message.get("metadata") or {})

        if intent == "express_happiness":
            msg = _one(lang,
                       "I'm glad to hear you’re feeling good. Anything you want to share?",
                       "Maayo kaayo nga nalingaw ka. Aduna bay gusto nimo ipa-ambit?")
        elif intent == "express_sadness":
            msg = _one(lang,
                       "I’m sorry you’re feeling down. Do you want to talk about what happened?",
                       "Pasayloa ko nga medyo mingaw imong gibati. Gusto ka mosulti unsay nahitabo?")
        elif intent == "express_anxiety":
            msg = _one(lang,
                       "That sounds stressful. Let’s take it one step at a time. What’s worrying you most?",
                       "Murag lisod gyud na. Hinay-hinay ta. Unsay pinakadako nimong kabalakan?")
        elif intent == "express_stress":
            msg = _one(lang,
                       "Thanks for sharing. Would a short breathing tip or scheduling a counselor help?",
                       "Salamat sa pag-ambit. Gusto ka og mubo nga breathing tip o magpa-iskedyul sa counselor?")
        else:
            msg = _one(lang,
                       "I’m here for you. Tell me more so I can help better.",
                       "Anaa ra ko para nimo. Sultihi ko og dugang para mas matabangan tika.")

        dispatcher.utter_message(text=msg)
        return []






# ---- Coping follow-up (optional) ----
MOOD_TO_SUPPORT_UTTER: Dict[str, str] = {
    "anxiety": "utter_support_anxiety",
    "depression": "utter_support_depression",
    "stress_burnout": "utter_support_stress_burnout",
    "anger": "utter_support_anger",
    "addiction": "utter_support_addiction",
    "self_esteem_body": "utter_support_self_esteem_body",
    "grief_loss": "utter_support_grief_loss",
    "sleep_insomnia": "utter_support_sleep_insomnia",
    "loneliness_isolation": "utter_support_loneliness_isolation",
    "trauma_ptsd": "utter_support_trauma_ptsd",
    "relationship_romance": "utter_support_relationship_romance",
    "school_academic": "utter_support_school_academic",
}

MOOD_TO_COPING_UTTER: Dict[str, str] = {
    "anxiety": "utter_coping_anxiety",
    "depression": "utter_coping_depression",
    "stress_burnout": "utter_coping_stress_burnout",
    "anger": "utter_coping_anger",
    "addiction": "utter_coping_addiction",
    "self_esteem_body": "utter_coping_self_esteem_body",
    "grief_loss": "utter_coping_grief_loss",
    "sleep_insomnia": "utter_coping_sleep_insomnia",
    "loneliness_isolation": "utter_coping_loneliness_isolation",
    "trauma_ptsd": "utter_coping_trauma_ptsd",
    "relationship_romance": "utter_coping_relationship_romance",
    "school_academic": "utter_coping_school_academic",
}

def _canonical_mood_from_intent(intent_name: Text) -> Text:
    if intent_name.startswith("express_"):
        key = intent_name.replace("express_", "")
        if key == "sadness": key = "depression"
        if key == "stress": key = "stress_burnout"
        if key == "sleep": key = "sleep_insomnia"
        if key == "relationship": key = "relationship_romance"
        if key == "low_self_esteem": key = "self_esteem_body"
        return key
    m = re.match(r"([a-z_]+?)(?:_p\\d+)$", intent_name)
    base = m.group(1) if m else intent_name
    aliases = {
        "stress":"stress_burnout","burnout":"stress_burnout",
        "relationship":"relationship_romance","romance":"relationship_romance",
        "selfesteem":"self_esteem_body","self_esteem":"self_esteem_body","bodyimage":"self_esteem_body",
        "grief":"grief_loss","loneliness":"loneliness_isolation",
        "trauma":"trauma_ptsd","ptsd":"trauma_ptsd",
        "sleep":"sleep_insomnia","insomnia":"sleep_insomnia",
        "school":"school_academic","sad":"depression",
    }
    for k,v in aliases.items():
        if base.startswith(k):
            return v
    return base

class ActionAnalyzeIssue(Action):
    def name(self) -> Text:
        return "action_analyze_issue"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: DomainDict) -> List[EventType]:
        intent = (tracker.latest_message.get("intent") or {}).get("name", "") or ""
        mood = _canonical_mood_from_intent(intent)
        support_utter = MOOD_TO_SUPPORT_UTTER.get(mood)

        if support_utter:
            dispatcher.utter_message(response=support_utter)
        else:
            dispatcher.utter_message(text="Thanks for sharing. I’m here to listen and help with next steps.")

        # Offer generic coping (domain should define 'utter_offer_coping' or per-mood offers)
        if "responses" in domain and "utter_offer_coping" in domain["responses"]:
            dispatcher.utter_message(response="utter_offer_coping")
        return [SlotSet("mood", mood)]

class ActionGiveCoping(Action):
    def name(self) -> Text:
        return "action_give_coping"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: DomainDict) -> List[EventType]:
        intent_name = (tracker.latest_message.get("intent") or {}).get("name", "") or ""
        mood = tracker.get_slot("mood") or _canonical_mood_from_intent(intent_name)
        coping_utter = MOOD_TO_COPING_UTTER.get(mood)

        if coping_utter and "responses" in domain and coping_utter in domain["responses"]:
            dispatcher.utter_message(response=coping_utter)
        else:
            dispatcher.utter_message(text="Here are some general steps: breathe slowly, ground with your senses, and take one small helpful action.")

        # After coping, offer referral (domain should define 'utter_offer_referral' or 'utter_ask_book_counselor')
        if "responses" in domain:
            if "utter_offer_referral" in domain["responses"]:
                dispatcher.utter_message(response="utter_offer_referral")
            elif "utter_ask_book_counselor" in domain["responses"]:
                dispatcher.utter_message(response="utter_ask_book_counselor")
        return []


__all__ = [
    "ActionSelectNumberedResponse",
    "parse_date", "parse_time", "normalize_yes_no",
    "ActionReflectiveSupport",
    "ActionAskAppointmentDate",
    "ActionAskAppointmentTime",
    "ActionAskConsent",
    "ValidateAppointmentForm",
    "ActionSubmitAppointment",
    "ActionAnalyzeIssue",
    "ActionGiveCoping",
]
