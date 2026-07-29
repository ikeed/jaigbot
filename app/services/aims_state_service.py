from __future__ import annotations

from typing import Any

from app.constants import (
    KEY_AIMS_STATE,
    PHASE_INQUIRE_MIRROR,
    PHASE_PRE_ANNOUNCE,
    PHASE_SECURE,
    SESSION_CHARACTER,
    STEP_ANNOUNCE,
    STEP_ANNOUNCE_INQUIRE,
    STEP_INQUIRE,
    STEP_MIRROR,
    STEP_MIRROR_INQUIRE,
    STEP_MIRROR_SECURE,
    STEP_SECURE,
    STEP_SECURE_INQUIRE,
)
from app.services.aims_metrics_service import AimsMetricsService
from app.services.coaching_tip_sanitizer import opens_with_open_concern_question
from app.services.conversation_service import (
    mark_mirrored_multi,
    mark_secured_by_topic,
    maybe_add_person_concern,
)


class AimsStateService:
    """Owns AIMS phase transitions, concern state, and stateful coaching guidance."""

    TOPICAL_CUES = {
        "autism": ["autism", "asd"],
        "immune_load": [
            "too many",
            "too soon",
            "immune overload",
            "immune system load",
            "viral load",
            "overwhelm the immune",
            "overload the immune",
        ],
        "side_effects": [
            "safe",
            "safety",
            "side effect",
            "adverse event",
            "vaers",
            "reaction to the vaccine",
            "reaction to the shot",
            "after the shot",
            "after the vaccine",
        ],
        "ingredients": ["thimerosal", "aluminum", "adjuvant", "preservative", "ingredient"],
        "schedule_timing": ["schedule", "spacing", "delay", "alternative schedule", "wait"],
        "disease_risk": [
            "measles was pretty much gone",
            "measles is pretty much gone",
            "measles was gone",
            "measles is gone",
            "measles basically gone",
            "thing of the past",
            "old disease",
            "from the past",
            "don't see it around",
            "do not see it around",
            "haven't seen any cases",
            "have not seen any cases",
            "never seen a case",
            "never seen it",
            "never actually seen it",
            "hard to picture",
            "hard to imagine",
            "real threat",
            "real danger",
            "still around",
            "catching it",
            "actually catching it",
        ],
        "effectiveness": ["effective", "efficacy", "works", "breakthrough"],
        "trust": [
            "data",
            "study",
            "studies",
            "pharma",
            "big pharma",
            "trust",
            "look into things",
            "look things up",
            "own research",
            "do my own research",
            "find out myself",
            "find out for myself",
            "look it up",
            "informed decision",
            "informed choice",
            "conflicting information",
            "hard to know what to believe",
            "sort through",
        ],
        "autonomy": [
            "pressured",
            "pressure",
            "pushed",
            "cornered",
            "forced",
            "lectured",
            "steamroll",
            "don't like being told",
            "my choice",
            "my decision",
            "right to choose",
            "right to decide",
            "your choice",
            "your decision",
            "not ready",
            "without pressure",
            "not pushed",
        ],
        "requirements": [
            "required",
            "requirement",
            "mandatory",
            "have to",
            "need to",
            "supposed to",
            "allowed",
            "okay here",
            "okay in canada",
            "is it okay here",
            "is it okay in canada",
        ],
    }

    ANALYTICAL_KEYWORDS = (
        "analytical",
        "data",
        "evidence",
        "need for cognition",
        "epistemic",
        "statistical",
        "peer-reviewed",
        "research",
    )

    CLOSURE_FOLLOWUP_CUES = (
        "follow-up",
        "follow up",
        "future visit",
        "next visit",
        "revisit",
        "book",
        "appointment",
        "vaccination clinic",
        "come back",
        "talk again",
        "talk about it again",
        "talk it over again",
        "talk more",
        "review this in",
        "review it in",
    )

    CLOSURE_LITERATURE_CUES = (
        "handout",
        "handouts",
        "brochure",
        "pamphlet",
        "literature",
        "written information",
        "written info",
        "information to take home",
        "take-home information",
        "take home information",
        "materials",
        "resource",
        "resources",
        "printout",
        "printed information",
        "info sheet",
        "read over",
        "look over",
    )

    COMPOUND_EXPANSIONS = AimsMetricsService.COMPOUND_EXPANSIONS
    VALID_STEPS = AimsMetricsService.VALID_STEPS

    def __init__(self, *, logger: Any) -> None:
        self._logger = logger

    def update(
        self,
        mem: dict[str, Any] | None,
        cls_payload: dict[str, Any],
        clinician_message: str,
        person_last: str,
        llm_topic: str | None = None,
    ) -> None:
        """Update AIMS state and coaching guidance. Mutates mem and cls_payload."""
        if mem is None:
            return

        try:
            state = mem.setdefault(
                KEY_AIMS_STATE,
                {
                    "announced": False,
                    "phase": PHASE_PRE_ANNOUNCE,
                    "first_inquire_done": False,
                    "pending_concerns": True,
                    "parent_concerns": [],
                },
            )
            step_main = cls_payload.get("step")
            steps = self.component_steps(step_main, cls_payload.get("steps"))

            if person_last:
                maybe_add_person_concern(state, person_last, self.TOPICAL_CUES, llm_topic)

            if STEP_MIRROR in steps:
                mark_mirrored_multi(
                    state,
                    clinician_message,
                    person_last,
                    self.TOPICAL_CUES,
                    llm_topic=llm_topic,
                )
            if STEP_SECURE in steps:
                mark_secured_by_topic(state, clinician_message, self.secure_topical_cues())

            character = mem.get(SESSION_CHARACTER)
            self.apply_coaching_guidance(
                cls_payload,
                step_main,
                state,
                clinician_message,
                person_last,
                character=character,
            )

            self.update_observational_state(state, step_main, steps)
            cls_payload["phase"] = state.get("phase")
            mem[KEY_AIMS_STATE] = state

        except Exception as e:
            self._logger.exception("AIMS state update failed: %s", e)

    @classmethod
    def component_steps(cls, step_current: str | None, steps: list[str] | None = None) -> list[str]:
        """Return de-duplicated atomic AIMS steps for state transitions."""
        out: list[str] = []

        def add(component_name: str | None) -> None:
            if not component_name:
                return
            expanded = cls.COMPOUND_EXPANSIONS.get(component_name, [component_name])
            for item in expanded:
                if item and item not in out:
                    out.append(item)

        for item_name in steps or []:
            add(item_name)
        add(step_current)
        return out

    @classmethod
    def detect_trust_style(cls, character: str | None) -> str:
        """Detect the persona's epistemic trust style from character text."""
        if not character:
            return "default"
        text = character.lower()
        if any(keyword in text for keyword in cls.ANALYTICAL_KEYWORDS):
            return "analytical"
        return "default"

    def apply_coaching_guidance(
        self,
        cls_payload: dict[str, Any],
        step_current: str | None,
        state: dict[str, Any],
        clinician_message: str,
        person_last: str,
        *,
        character: str | None = None,
    ) -> None:
        """Apply coaching-specific guidance rules."""
        concerns_list = state.get("parent_concerns") or []
        if concerns_list:
            topics: dict[str, bool] = {}
            for concern in concerns_list:
                topic = str(concern.get("topic", "unknown"))
                topics[topic] = topics.get(topic, False) or bool(concern.get("is_mirrored"))

            if all(topics.values()):
                filtered_tips = []
                for tip in cls_payload.get("tips") or []:
                    tip_lower = (tip or "").lower()
                    if not ("mirror" in tip_lower or "what else" in tip_lower):
                        filtered_tips.append(tip)
                cls_payload["tips"] = filtered_tips

        if step_current == STEP_ANNOUNCE and state.get("phase") == PHASE_INQUIRE_MIRROR:
            reasons = list(cls_payload.get("reasons") or [])
            if not any("announce after inquiry" in reason.lower() for reason in reasons):
                reasons.insert(0, "Avoid moving to Announce after inquiry before all concerns are mirrored.")
            cls_payload["reasons"] = reasons
            cls_payload["score"] = min(2, int(cls_payload.get("score", 2)))
            cls_payload.setdefault("tips", []).append(
                "Keep it brief and invite input (e.g., 'How does that sound?')."
            )

        component_steps = set(self.component_steps(step_current))

        if STEP_MIRROR in component_steps:
            mark_mirrored_multi(state, clinician_message, person_last, self.TOPICAL_CUES)

        if STEP_SECURE in component_steps and step_current != STEP_SECURE:
            mark_secured_by_topic(state, clinician_message, self.secure_topical_cues())
        elif step_current == STEP_SECURE:
            self._apply_secure_guidance(cls_payload, state, clinician_message, person_last, character)
        self._add_closure_plan_tip(cls_payload, state, clinician_message)

    def _apply_secure_guidance(
        self,
        cls_payload: dict[str, Any],
        state: dict[str, Any],
        clinician_message: str,
        _person_last: str,
        character: str | None,
    ) -> None:
        first_inquire_done = state.get("first_inquire_done", False)
        if not first_inquire_done:
            if opens_with_open_concern_question(clinician_message):
                reason = "You asked an open question, then moved into reassurance before giving them space to answer."
                tip = "After asking what's on their mind, pause before offering reassurance."
            else:
                reason = "You moved into reassurance before asking about their concerns — try an open question first"
                tip = "Ask what's on their mind (e.g., 'What are your thoughts about the vaccines we discussed?') before offering reassurance."
            cls_payload["reasons"] = [reason] + (cls_payload.get("reasons") or [])
            cls_payload.setdefault("tips", []).append(tip)
            try:
                cls_payload["score"] = min(2, int(cls_payload.get("score", 2)))
            except Exception as e:
                self._logger.debug("Score normalization failed (secure before inquire): %s", e)
                cls_payload["score"] = 2
            recent = state.get("recent_coaching") or []
            recent.append("secure_before_inquire")
            state["recent_coaching"] = recent[-3:]

        needs_mirror = self._has_material_unmirrored_concern(state)

        if needs_mirror and first_inquire_done:
            self._add_secure_before_mirror_feedback(cls_payload, state, character)
        else:
            state["recent_coaching"] = []

        mark_secured_by_topic(state, clinician_message, self.secure_topical_cues())

    @classmethod
    def secure_topical_cues(cls) -> dict[str, list[str]]:
        cues = {topic: list(topic_cues) for topic, topic_cues in cls.TOPICAL_CUES.items()}
        cues.setdefault("requirements", []).extend(
            [
                "what happens",
                "consequence",
                "consequences",
                "necessary",
                "must happen",
                "must do",
                "must postpone",
                "not an emergency decision",
                "recommended today",
                "right this minute",
                "future visit",
                "follow-up appointment",
                "vaccination clinic",
            ]
        )
        cues.setdefault("side_effects", []).extend(
            [
                "what to expect afterward",
                "afterward",
                "soreness",
                "sore",
                "tired",
                "mild fever",
                "needle went in",
                "common thing you might notice",
            ]
        )
        return cues

    @classmethod
    def _add_closure_plan_tip(
        cls,
        cls_payload: dict[str, Any],
        state: dict[str, Any],
        clinician_message: str,
    ) -> None:
        if cls_payload.get("tips"):
            return
        if STEP_SECURE not in cls.component_steps(cls_payload.get("step"), cls_payload.get("steps")):
            return

        concerns = state.get("parent_concerns") or []
        if concerns and not all(concern.get("is_mirrored") for concern in concerns):
            return

        text = (clinician_message or "").lower()
        has_literature = any(cue in text for cue in cls.CLOSURE_LITERATURE_CUES)
        has_followup = any(cue in text for cue in cls.CLOSURE_FOLLOWUP_CUES)
        if has_followup and not has_literature:
            cls_payload["tips"] = [
                "You have a follow-up plan; offer some information to review at home so they can come back with specific questions."
            ]
        elif has_literature and not has_followup:
            cls_payload["tips"] = [
                "You offered take-home information; also book a follow-up so they know when they can bring questions back."
            ]

    def _add_secure_before_mirror_feedback(
        self,
        cls_payload: dict[str, Any],
        state: dict[str, Any],
        character: str | None,
    ) -> None:
        recent = state.get("recent_coaching") or []

        unmirrored_topics = self._unmirrored_topics_requiring_feedback(state)
        first_unmirrored = unmirrored_topics[0] if unmirrored_topics else None
        secure_before_mirror_key = self._secure_before_mirror_key(first_unmirrored)
        repeat_count = self._secure_before_mirror_repeat_count(recent, first_unmirrored)

        if repeat_count == 0:
            if self.detect_trust_style(character) == "analytical":
                reason = "You're educating before reflecting — try validating their reasoning first; this person values having their logic acknowledged"
                tip = "Reflect the reasoning (e.g., 'You want to weigh absolute vs. relative risk individually — did I capture that right?')."
            else:
                reason = "You moved into education before reflecting the concern — try mirroring first so they feel heard"
                tip = "Before educating, briefly reflect the concern (e.g., 'It feels like a lot at once — did I get that right?')."
        elif repeat_count == 1:
            topic_hint = f" ('{first_unmirrored}')" if first_unmirrored else ""
            reason = f"You're still educating without reflecting — the concern{topic_hint} hasn't been mirrored yet"
            tip = f"Try reflecting the specific concern{topic_hint} before more education."
        else:
            count = repeat_count + 1
            topic_hint = f" about '{first_unmirrored}'" if first_unmirrored else ""
            reason = f"You've had {count} Secure turns without mirroring{topic_hint} — try pausing to reflect before more education"
            tip = f"Pause and mirror: acknowledge the concern{topic_hint} before sharing more facts."

        cls_payload["reasons"] = [reason] + (cls_payload.get("reasons") or [])
        cls_payload.setdefault("tips", []).append(tip)
        try:
            cls_payload["score"] = min(2, int(cls_payload.get("score", 2)))
        except Exception as e:
            self._logger.debug("Score normalization failed (secure before mirror): %s", e)
            cls_payload["score"] = 2

        recent.append(secure_before_mirror_key)
        state["recent_coaching"] = recent[-3:]

    @classmethod
    def _has_material_unmirrored_concern(cls, state: dict[str, Any]) -> bool:
        return bool(cls._unmirrored_topics_requiring_feedback(state))

    @classmethod
    def _unmirrored_topics_requiring_feedback(cls, state: dict[str, Any]) -> list[str]:
        concerns = state.get("parent_concerns") or []
        mirrored_evidence: set[str] = set()
        for concern in concerns:
            if concern.get("is_mirrored"):
                mirrored_evidence.update(cls._evidence_set(concern))

        topics: list[str] = []
        for concern in concerns:
            if concern.get("is_mirrored"):
                continue
            evidence = cls._evidence_set(concern)
            if evidence and evidence.issubset(mirrored_evidence):
                continue
            topics.append(str(concern.get("topic", "unknown")))
        return topics

    @staticmethod
    def _evidence_set(concern: dict[str, Any]) -> set[str]:
        raw_evidence = concern.get("evidence")
        if raw_evidence is None:
            raw_evidence = concern.get("desc")

        values: list[Any]
        if isinstance(raw_evidence, str):
            values = [raw_evidence]
        elif isinstance(raw_evidence, (list, tuple, set)):
            values = list(raw_evidence)
        else:
            values = []

        return {str(item).strip().lower() for item in values if str(item).strip()}

    @staticmethod
    def _secure_before_mirror_key(topic: str | None) -> str:
        normalized = str(topic).strip() if topic else ""
        return f"secure_before_mirror:{normalized}" if normalized else "secure_before_mirror"

    @classmethod
    def _secure_before_mirror_repeat_count(cls, recent: list[Any], topic: str | None) -> int:
        topic_key = cls._secure_before_mirror_key(topic)
        generic_key = "secure_before_mirror"

        count = 0
        for item in recent:
            if item == topic_key:
                count += 1
            elif item == generic_key and topic_key != generic_key:
                # Backward compatibility for sessions seeded before topic-local keys.
                count += 1
        return count

    def update_observational_state(
        self,
        state: dict[str, Any],
        step_current: str | None,
        steps: list[str] | None = None,
    ) -> None:
        """Update observed AIMS phase state from detected step(s)."""
        all_steps = set(self.component_steps(step_current, steps))

        if STEP_ANNOUNCE in all_steps:
            state["announced"] = True

        if (
            step_current
            in (STEP_INQUIRE, STEP_ANNOUNCE_INQUIRE, STEP_MIRROR_INQUIRE, STEP_SECURE_INQUIRE)
            or STEP_INQUIRE in all_steps
        ):
            state["first_inquire_done"] = True
            state["phase"] = PHASE_INQUIRE_MIRROR
        elif step_current == STEP_MIRROR_SECURE:
            concerns = state.get("parent_concerns") or []
            all_mirrored = all(concern.get("is_mirrored") for concern in concerns) if concerns else True
            state["phase"] = PHASE_SECURE if all_mirrored else PHASE_INQUIRE_MIRROR
            state["pending_concerns"] = (
                not all(
                    concern.get("is_mirrored") and concern.get("is_secured")
                    for concern in concerns
                )
                if concerns
                else False
            )
        elif step_current == STEP_MIRROR or (STEP_MIRROR in all_steps and STEP_SECURE not in all_steps):
            state["phase"] = PHASE_INQUIRE_MIRROR
        elif step_current == STEP_SECURE:
            concerns = state.get("parent_concerns") or []
            all_mirrored = all(concern.get("is_mirrored") for concern in concerns) if concerns else True
            if all_mirrored:
                state["phase"] = PHASE_SECURE

        concerns = state.get("parent_concerns") or []
        all_resolved = (
            all(concern.get("is_mirrored") and concern.get("is_secured") for concern in concerns)
            if concerns
            else True
        )
        state["pending_concerns"] = not all_resolved

        if all_resolved and concerns and state.get("announced") and state.get("first_inquire_done"):
            state["phase"] = PHASE_SECURE
