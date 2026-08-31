from __future__ import annotations

import copy
import re
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
from app.message_catalog import message, message_list, message_map
from app.services.aims_metrics_service import AimsMetricsService
from app.services.coaching_tip_sanitizer import opens_with_open_concern_question
from app.services.conversation_service import (
    apply_concern_events,
    mark_mirrored_multi,
    mark_secured_by_topic,
    maybe_add_person_concern,
)


class AimsStateService:
    """Owns AIMS phase transitions, concern state, and stateful coaching guidance."""

    TOPICAL_CUES = message_map("lexicon.aims_state.topical_cues")
    ANALYTICAL_KEYWORDS = tuple(message_list("lexicon.aims_state.analytical_keywords"))
    CLOSURE_FOLLOWUP_CUES = tuple(message_list("lexicon.aims_state.closure_followup_cues"))
    CLOSURE_LITERATURE_CUES = tuple(message_list("lexicon.aims_state.closure_literature_cues"))
    # Shared with coaching_display._is_important_feedback - same locale key, single source
    # of truth, so both layers agree on what counts as "about mirroring".
    MIRROR_TIP_KEYWORDS = tuple(
        kw.strip().lower()
        for kw in message_list("lexicon.coaching_display.mirror_keywords")
        if str(kw or "").strip()
    ) or ("mirror",)

    COMPOUND_EXPANSIONS = AimsMetricsService.COMPOUND_EXPANSIONS
    VALID_STEPS = AimsMetricsService.VALID_STEPS

    def __init__(
        self,
        *,
        logger: Any,
        heuristic_fallback_enabled: bool = False,
    ) -> None:
        self._logger = logger
        self._heuristic_fallback_enabled = heuristic_fallback_enabled

    def update(
        self,
        mem: dict[str, Any] | None,
        cls_payload: dict[str, Any],
        clinician_message: str,
        person_last: str,
        llm_topic: str | None = None,
        person_events: list[Any] | None = None,
    ) -> None:
        """Update AIMS state and coaching guidance. Mutates mem and cls_payload."""
        if mem is None:
            return

        # mem.setdefault below inserts the state dict into mem immediately and
        # every subsequent step mutates it in place, so an exception partway
        # through would otherwise leave a half-updated state behind while the
        # except block swallows the failure. Snapshot first so a failed turn's
        # state update either fully lands or fully doesn't.
        had_prior_state = KEY_AIMS_STATE in mem
        prior_state = copy.deepcopy(mem.get(KEY_AIMS_STATE)) if had_prior_state else None

        try:
            seeded_concerns = self._seed_parent_concerns(mem)
            state = mem.setdefault(
                KEY_AIMS_STATE,
                {
                    "announced": False,
                    "phase": PHASE_PRE_ANNOUNCE,
                    "is_undiscovered_concerns": bool(seeded_concerns),
                    "pending_concerns": True,
                    "parent_concerns": seeded_concerns,
                },
            )
            # Captured before apply_concern_events runs below, so this reflects the
            # turn's starting value - _update_sweep_attempt_tracking needs to compare
            # "was something undiscovered going into this turn" against the recomputed
            # value after the turn's own discovery matching has had its chance.
            was_undiscovered_before = bool(state.get("is_undiscovered_concerns"))
            step_main = cls_payload.get("step")
            steps = self.component_steps(step_main, cls_payload.get("steps"))
            handled_events = apply_concern_events(
                state,
                person_events,
                person_text=person_last,
            )

            if (
                self._heuristic_fallback_enabled
                and person_last
                and "concern_presence" not in handled_events
            ):
                maybe_add_person_concern(state, person_last, self.TOPICAL_CUES, llm_topic)

            if (
                self._heuristic_fallback_enabled
                and STEP_MIRROR in steps
                and "mirrored" not in handled_events
            ):
                mark_mirrored_multi(
                    state,
                    clinician_message,
                    person_last,
                    self.TOPICAL_CUES,
                    llm_topic=llm_topic,
                )
            if (
                self._heuristic_fallback_enabled
                and STEP_SECURE in steps
                and "secured" not in handled_events
            ):
                mark_secured_by_topic(state, clinician_message, self.secure_topical_cues())

            self._recompute_undiscovered_concerns(state)
            self._update_sweep_attempt_tracking(state, steps, was_undiscovered_before)
            self._update_closure_signals(state, clinician_message)

            character = mem.get(SESSION_CHARACTER)
            self.apply_coaching_guidance(
                cls_payload,
                step_main,
                state,
                clinician_message,
                person_last,
                character=character,
            )
            self._apply_inquire_nudge(cls_payload, state, steps)

            self.update_observational_state(state, step_main, steps)
            cls_payload["phase"] = state.get("phase")
            mem[KEY_AIMS_STATE] = state

        except Exception as e:
            self._logger.exception("AIMS state update failed: %s", e)
            # Restore the turn's starting state rather than leaving whatever
            # partial mutation the failure interrupted (see snapshot above).
            if had_prior_state:
                mem[KEY_AIMS_STATE] = prior_state
            else:
                mem.pop(KEY_AIMS_STATE, None)

    @staticmethod
    def _seed_parent_concerns(mem: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Pre-seed parent_concerns from the persona's static checklist.

        Each entry is tagged from_checklist=True so the Endgame backstop and
        Inquire nudge only ever reason about the persona's own known concerns,
        never about ad-hoc concerns _apply_concern_presence_event creates
        organically from unrecognized topics.
        """
        persona = (mem or {}).get("persona") or {}
        concerns = persona.get("concerns") or []
        seeded: list[dict[str, Any]] = []
        for concern in concerns:
            if not isinstance(concern, dict):
                continue
            topic = concern.get("topic")
            if not topic:
                continue
            seeded.append(
                {
                    "topic": topic,
                    "desc": concern.get("desc") or "",
                    "is_discovered": False,
                    "is_mirrored": False,
                    "is_secured": False,
                    "from_checklist": True,
                }
            )
        return seeded

    @staticmethod
    def _recompute_undiscovered_concerns(state: dict[str, Any]) -> None:
        """Recompute is_undiscovered_concerns from the checklist's own state.

        Scoped to from_checklist=True entries only - an ad-hoc concern the
        classifier invents for an unrecognized topic must never factor into
        this (see _apply_concern_presence_event's unknown-topic handling).

        Sessions with no checklist at all (no persona data, e.g. a custom
        character outside the persona system) have zero from_checklist
        entries - fall back to the pre-checklist behavior for those (true
        until any concern at all has been captured) rather than reading an
        empty checklist as "definitely nothing to discover."
        """
        concerns = state.get("parent_concerns") or []
        checklist_concerns = [c for c in concerns if c.get("from_checklist")]
        if checklist_concerns:
            state["is_undiscovered_concerns"] = any(
                not concern.get("is_discovered") for concern in checklist_concerns
            )
        else:
            state["is_undiscovered_concerns"] = not bool(concerns)

    @staticmethod
    def _update_sweep_attempt_tracking(
        state: dict[str, Any], steps: list[str], was_undiscovered_before: bool
    ) -> None:
        """Track whether the clinician has genuinely tried to surface a hidden concern.

        A checklist concern's is_discovered only flips via the classifier's structured
        semantic matching (see conversation_service.apply_concern_events) - never merely
        because the clinician asked an open question and the patient said "no, that's
        everything." Without this, a persona that simply never volunteers a checklist
        topic leaves is_undiscovered_concerns permanently true, and the endgame backstop
        (aims_endgame_service.py) blocks every closing turn forever with no way out.

        This counts a turn as a genuine sweep attempt only when Inquire was present AND
        something was still undiscovered going in AND it's STILL undiscovered after this
        turn's own recompute - i.e. the clinician asked, and it didn't surface anything.
        One such attempt is treated as sufficient signal (a real "no" is real
        information; asking the identical question again isn't going to produce a
        different answer) - see aims_endgame_service.py for how this is consumed.
        """
        if not was_undiscovered_before:
            return
        if state.get("is_undiscovered_concerns"):
            if STEP_INQUIRE in steps:
                attempts = int(state.get("sweep_inquire_attempts_since_undiscovered", 0) or 0) + 1
                state["sweep_inquire_attempts_since_undiscovered"] = attempts
                if attempts >= 1:
                    # Sticky - deliberately never reset back to False once set. This is
                    # consumed as a one-way "the clinician has genuinely tried" signal
                    # for the endgame bypass; un-sticking it would let a single later
                    # discovery re-arm the backstop's most restrictive state right when
                    # the conversation is closest to resolving.
                    state["patient_unreceptive_to_further_inquire"] = True
            # else: neither Secure-only nor any other non-Inquire turn changes the
            # counter - only a genuine Inquire attempt counts, matching the "unchanged
            # on neither" spirit of _apply_inquire_nudge's own counter.
        else:
            state["sweep_inquire_attempts_since_undiscovered"] = 0

    @classmethod
    def _update_closure_signals(cls, state: dict[str, Any], clinician_message: str) -> None:
        """Track, across the whole session, whether literature/follow-up were offered.

        Sticky (only ever sets True, never unsets) - this replaces _add_closure_plan_tip's
        old behavior of re-scanning only the current turn's text, which missed anything
        offered earlier in the conversation. Reuses the existing cue matchers as-is.
        """
        text = (clinician_message or "").lower()
        if cls._has_closure_literature(text):
            state["literature_offered"] = True
        if any(cue in text for cue in cls.CLOSURE_FOLLOWUP_CUES):
            state["followup_confirmed"] = True

    def _apply_inquire_nudge(
        self,
        cls_payload: dict[str, Any],
        state: dict[str, Any],
        steps: list[str],
    ) -> None:
        """Mid-conversation Tip: nudge toward Inquire after 2 Secure turns in a row.

        Plain global integer counter (deliberately NOT secure_before_mirror's
        topic-keyed recent_coaching mechanism - this tracks the clinician's
        overall behavior, not a specific concern). Increments on any turn with
        STEP_SECURE present, resets to 0 on any turn with STEP_INQUIRE present
        (both including compounds), left unchanged on a turn with neither.
        Fires the same flat text every qualifying turn - no escalation tiers,
        unlike secure_before_mirror.
        """
        counter = int(state.get("secure_since_inquire_count", 0) or 0)
        if STEP_INQUIRE in steps:
            counter = 0
        elif STEP_SECURE in steps:
            counter += 1
        state["secure_since_inquire_count"] = counter

        if counter < 2 or not state.get("is_undiscovered_concerns"):
            return

        text = message("state_feedback.inquire_nudge_tip")
        if self._has_structured_feedback(cls_payload):
            self._append_feedback_item(
                cls_payload,
                step=STEP_INQUIRE,
                code="inquire_nudge",
                text=text,
            )
        else:
            cls_payload.setdefault("tips", []).append(text)

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
        has_structured_feedback = self._has_structured_feedback(cls_payload)
        concerns_list = state.get("parent_concerns") or []
        if (
            self._heuristic_fallback_enabled
            and concerns_list
            and not has_structured_feedback
        ):
            topics: dict[str, bool] = {}
            for concern in concerns_list:
                topic = str(concern.get("topic", "unknown"))
                topics[topic] = topics.get(topic, False) or bool(concern.get("is_mirrored"))

            if all(topics.values()):
                resolved_markers = message_list("lexicon.aims_state.resolved_concern_tip_markers")
                filtered_tips = []
                for tip in cls_payload.get("tips") or []:
                    tip_lower = (tip or "").lower()
                    if not any(marker in tip_lower for marker in resolved_markers):
                        filtered_tips.append(tip)
                cls_payload["tips"] = filtered_tips

        if step_current == STEP_ANNOUNCE and state.get("phase") == PHASE_INQUIRE_MIRROR:
            if has_structured_feedback:
                self._append_feedback_item(
                    cls_payload,
                    step=STEP_ANNOUNCE,
                    code="announce_after_inquiry",
                    text=message("state_feedback.announce_after_inquiry"),
                )
            else:
                reasons = list(cls_payload.get("reasons") or [])
                announce_feedback = message("state_feedback.announce_after_inquiry")
                if not any(announce_feedback == reason for reason in reasons):
                    reasons.insert(0, announce_feedback)
                cls_payload["reasons"] = reasons
                cls_payload.setdefault("tips", []).append(
                    message("state_feedback.announce_after_inquiry_tip")
                )
            cls_payload["score"] = min(2, int(cls_payload.get("score", 2)))

        component_steps = set(self.component_steps(step_current))

        if self._heuristic_fallback_enabled and STEP_MIRROR in component_steps:
            mark_mirrored_multi(state, clinician_message, person_last, self.TOPICAL_CUES)

        if (
            self._heuristic_fallback_enabled
            and STEP_SECURE in component_steps
            and step_current != STEP_SECURE
        ):
            mark_secured_by_topic(state, clinician_message, self.secure_topical_cues())
        elif STEP_SECURE in component_steps and STEP_MIRROR not in component_steps:
            # Exact-match on step_current == STEP_SECURE used to skip this
            # entirely for compound steps (Secure+Inquire, Mirror+Secure,
            # Mirror+Secure+Inquire) even though component_steps was already
            # computed above for exactly this purpose. Secure+Inquire has no
            # mirror this turn, so the check should apply exactly like plain
            # Secure. Mirror+Secure(+Inquire) DO have a same-turn mirror --
            # excluded deliberately, not just because _has_material_unmirrored_concern
            # would self-correct for the just-mirrored concern (it would,
            # since mirror events are applied earlier in update()), but
            # because flagging "secure before mirror" in the same breath as
            # a mirror the clinician just did reads as contradictory
            # feedback, even when it's technically about a different concern.
            self._apply_secure_guidance(
                cls_payload,
                state,
                clinician_message,
                person_last,
                character,
                prefer_structured_feedback=has_structured_feedback,
            )
        self._add_closure_plan_tip(cls_payload, state, clinician_message)

    def _apply_secure_guidance(
        self,
        cls_payload: dict[str, Any],
        state: dict[str, Any],
        clinician_message: str,
        _person_last: str,
        character: str | None,
        *,
        prefer_structured_feedback: bool = False,
    ) -> None:
        is_undiscovered_concerns = state.get("is_undiscovered_concerns", True)
        if is_undiscovered_concerns:
            opened_with_concern_question = self._observed_open_concern_question(cls_payload)
            if (
                opened_with_concern_question is None
                and self._heuristic_fallback_enabled
            ):
                opened_with_concern_question = opens_with_open_concern_question(clinician_message)
            if prefer_structured_feedback:
                code = (
                    "secure_before_inquire_after_question"
                    if opened_with_concern_question
                    else "secure_before_inquire"
                )
                text_key = (
                    "state_feedback.secure_before_inquire_after_question"
                    if opened_with_concern_question
                    else "state_feedback.secure_before_inquire"
                )
                self._append_feedback_item(
                    cls_payload,
                    step=STEP_SECURE,
                    code=code,
                    text=message(text_key),
                )
            else:
                if opened_with_concern_question:
                    reason = message("state_feedback.secure_before_inquire_after_question")
                    tip = message("state_feedback.secure_before_inquire_after_question_tip")
                else:
                    reason = message("state_feedback.secure_before_inquire_reason")
                    tip = message("state_feedback.secure_before_inquire_tip")
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

        if needs_mirror and not is_undiscovered_concerns:
            state["secure_before_mirror_total"] = int(state.get("secure_before_mirror_total", 0)) + 1
            unmirrored_topics = self._unmirrored_topics_requiring_feedback(state)
            state["secure_before_mirror_last_topic_hint"] = self._user_facing_topic_hint(
                unmirrored_topics[0] if unmirrored_topics else None
            )
            if prefer_structured_feedback:
                self._add_secure_before_mirror_feedback_item(cls_payload, state, character)
            else:
                self._add_secure_before_mirror_feedback(cls_payload, state, character)
        else:
            state["recent_coaching"] = []

        if self._heuristic_fallback_enabled:
            mark_secured_by_topic(state, clinician_message, self.secure_topical_cues())

    @classmethod
    def secure_topical_cues(cls) -> dict[str, list[str]]:
        cues = {topic: list(topic_cues) for topic, topic_cues in cls.TOPICAL_CUES.items()}
        extensions = message_map("lexicon.aims_state.secure_topic_extensions")
        for topic, topic_cues in extensions.items():
            if isinstance(topic_cues, list):
                cues.setdefault(topic, []).extend(str(cue) for cue in topic_cues)
        return cues

    @classmethod
    def _closure_plan_ready(cls, state: dict[str, Any], *, unreceptive: bool) -> bool:
        """Is the conversation actually near closure?

        Gates the "you haven't offered anything to take home" nudge, which tells
        the clinician to start wrapping up. The bar is the full checklist:
        every concern discovered, mirrored AND secured -- not merely that the
        concerns surfaced so far happen to be mirrored, which is true as early
        as turn 2 and produced a wrap-up nudge mid-conversation in production.

        The one exception is an unreceptive patient: once they have stopped
        offering anything new, nothing further can be discovered or mirrored, and
        this nudge is precisely the guidance that situation needs.
        """
        if unreceptive:
            return True
        if state.get("is_undiscovered_concerns"):
            return False
        concerns = state.get("parent_concerns") or []
        if not concerns:
            return False
        return all(
            concern.get("is_mirrored") and concern.get("is_secured")
            for concern in concerns
        )

    @classmethod
    def _add_closure_plan_tip(
        cls,
        cls_payload: dict[str, Any],
        state: dict[str, Any],
        _clinician_message: str,
    ) -> None:
        """Nudge toward completing the closure plan: literature and/or a follow-up.

        Reads the session-level literature_offered/followup_confirmed flags (set by
        _update_closure_signals every turn) rather than re-scanning only the current
        turn's text, so an offer made several turns ago is still remembered.

        The mirrored-completeness gate is bypassed when
        patient_unreceptive_to_further_inquire is set: once the clinician has genuinely
        tried to surface a hidden concern and the patient isn't giving anything more,
        nothing further can be mirrored, and this nudge is exactly the guidance that
        scenario needs - suppressing it here would silently defeat the whole point of
        tracking that flag.
        """
        if STEP_SECURE not in cls.component_steps(cls_payload.get("step"), cls_payload.get("steps")):
            return

        concerns = state.get("parent_concerns") or []
        unreceptive = bool(state.get("patient_unreceptive_to_further_inquire"))
        if concerns and not all(concern.get("is_mirrored") for concern in concerns) and not unreceptive:
            return

        has_literature = bool(state.get("literature_offered"))
        has_followup = bool(state.get("followup_confirmed"))

        if has_followup and not has_literature:
            code = "closure_followup_without_literature"
            text = message("state_feedback.closure_followup_without_literature")
        elif has_literature and not has_followup:
            code = "closure_literature_without_followup"
            text = message("state_feedback.closure_literature_without_followup")
        elif not has_literature and not has_followup:
            # The other two branches are safe on any Secure turn: the clinician has
            # already signalled they are closing (offered literature / booked a
            # follow-up), so completing the plan is apt guidance. THIS branch is
            # different - it tells a clinician to start wrapping up, which is wrong
            # unless the conversation is genuinely near closure. Reported from
            # production: it fired on turn 3 while concerns were still undiscovered
            # and nothing had been secured.
            if not cls._closure_plan_ready(state, unreceptive=unreceptive):
                return
            code = "offer_literature"
            text = message("state_feedback.offer_literature_tip")
        else:
            return  # both already offered - nothing to nudge

        if cls._has_structured_feedback(cls_payload):
            cls._append_feedback_item(cls_payload, step=STEP_SECURE, code=code, text=text)
        elif not cls_payload.get("tips"):
            cls_payload["tips"] = [text]

    @classmethod
    def _has_closure_literature(cls, text: str) -> bool:
        if any(cue in text for cue in cls.CLOSURE_LITERATURE_CUES):
            return True
        return any(
            re.search(pattern, text)
            for pattern in message_list("lexicon.aims_state.closure_literature_patterns")
        )

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
                reason = message("state_feedback.secure_before_mirror_analytical_reason")
                tip = message("state_feedback.secure_before_mirror_analytical_tip")
            else:
                reason = message("state_feedback.secure_before_mirror_reason")
                tip = message("state_feedback.secure_before_mirror_tip")
        elif repeat_count == 1:
            topic_hint = self._user_facing_topic_hint(first_unmirrored)
            reason = message("state_feedback.secure_before_mirror_repeat_reason", topic_hint=topic_hint)
            tip = message("state_feedback.secure_before_mirror_repeat_tip", topic_hint=topic_hint)
        else:
            count = repeat_count + 1
            topic_hint = self._user_facing_topic_hint(first_unmirrored)
            reason = message(
                "state_feedback.secure_before_mirror_many_reason",
                count=count,
                topic_hint=topic_hint,
            )
            tip = message("state_feedback.secure_before_mirror_many_tip", topic_hint=topic_hint)

        cls_payload["reasons"] = [reason] + (cls_payload.get("reasons") or [])
        cls_payload.setdefault("tips", []).append(tip)
        self._cap_score_for_unmirrored_secure(cls_payload)

        recent.append(secure_before_mirror_key)
        state["recent_coaching"] = recent[-3:]

    def _cap_score_for_unmirrored_secure(self, cls_payload: dict[str, Any]) -> None:
        try:
            cls_payload["score"] = min(2, int(cls_payload.get("score", 2)))
        except Exception as e:
            self._logger.debug("Score normalization failed (secure before mirror): %s", e)
            cls_payload["score"] = 2

    def _add_secure_before_mirror_feedback_item(
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
        topic_hint = self._user_facing_topic_hint(first_unmirrored)

        if repeat_count == 0:
            if self.detect_trust_style(character) == "analytical":
                text = message("state_feedback.secure_before_mirror_analytical_reason")
            else:
                text = message("state_feedback.secure_before_mirror_reason")
        elif repeat_count == 1:
            text = message("state_feedback.secure_before_mirror_repeat_reason", topic_hint=topic_hint)
        else:
            text = message(
                "state_feedback.secure_before_mirror_many_reason",
                count=repeat_count + 1,
                topic_hint=topic_hint,
            )

        self._remove_redundant_mirror_feedback_items(cls_payload)
        self._remove_secure_praise_before_mirror(cls_payload)
        self._append_feedback_item(
            cls_payload,
            step=STEP_SECURE,
            code="secure_before_mirror",
            text=text,
        )
        self._cap_score_for_unmirrored_secure(cls_payload)

        recent.append(secure_before_mirror_key)
        state["recent_coaching"] = recent[-3:]

    @classmethod
    def _remove_redundant_mirror_feedback_items(cls, cls_payload: dict[str, Any]) -> None:
        """Drop any classifier-generated feedback item that already flags the same
        secure-before-mirror problem in its own words, so the turn doesn't show two
        differently-worded "Important" lines saying the same thing. The state
        service's own coded item (with proper escalation) replaces it."""
        items = cls_payload.get("feedback_items")
        if not isinstance(items, list):
            return

        def _is_redundant(item: Any) -> bool:
            if not isinstance(item, dict):
                return False
            if str(item.get("tone") or "").strip().lower() == "praise":
                return False
            text = str(item.get("text") or "").lower()
            return any(keyword in text for keyword in cls.MIRROR_TIP_KEYWORDS)

        cls_payload["feedback_items"] = [item for item in items if not _is_redundant(item)]

    @staticmethod
    def _remove_secure_praise_before_mirror(cls_payload: dict[str, Any]) -> None:
        """Drop praise for this turn's Secure content when the turn is about to be
        flagged with the "secure before mirror" Important item -- praising the same
        content the Important item calls premature undermines the correction."""
        items = cls_payload.get("feedback_items")
        if not isinstance(items, list):
            return

        def _is_secure_praise(item: Any) -> bool:
            if not isinstance(item, dict):
                return False
            return (
                str(item.get("tone") or "").strip().lower() == "praise"
                and item.get("step") == STEP_SECURE
            )

        cls_payload["feedback_items"] = [item for item in items if not _is_secure_praise(item)]

    @staticmethod
    def _has_structured_feedback(cls_payload: dict[str, Any]) -> bool:
        return bool(cls_payload.get("feedback_items") or cls_payload.get("step_feedback"))

    @staticmethod
    def _observed_open_concern_question(cls_payload: dict[str, Any]) -> bool | None:
        observations = cls_payload.get("observations")
        model_dump = getattr(observations, "model_dump", None)
        if callable(model_dump):
            observations = model_dump()
        if not isinstance(observations, dict):
            return None
        value = observations.get("open_concern_question_present")
        return value if isinstance(value, bool) else None

    @staticmethod
    def _append_feedback_item(
        cls_payload: dict[str, Any],
        *,
        step: str,
        code: str,
        text: str,
    ) -> None:
        items = cls_payload.setdefault("feedback_items", [])
        for item in items:
            if isinstance(item, dict) and item.get("code") == code:
                return
            if hasattr(item, "code") and item.code == code:
                return
        items.append(
            {
                "step": step,
                "tone": "improvement",
                "code": code,
                "text": text,
            }
        )

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
    def _user_facing_topic_hint(cls, topic: str | None) -> str:
        normalized = str(topic or "").strip()
        if not normalized:
            return ""
        label = message_map("state_feedback.topic_hints").get(
            normalized,
            normalized.replace("_", " "),
        )
        return f" about {label}"

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
            # Discovery is driven exclusively by per-concern matching in
            # _apply_concern_presence_event (via _recompute_undiscovered_concerns,
            # called before this runs), not by step classification alone - an
            # Inquire-classified turn that doesn't happen to elicit any checklist
            # item must not be treated as having discovered one.
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
            state["phase"] = PHASE_SECURE if all_mirrored else PHASE_INQUIRE_MIRROR

        concerns = state.get("parent_concerns") or []
        all_resolved = (
            all(concern.get("is_mirrored") and concern.get("is_secured") for concern in concerns)
            if concerns
            else True
        )
        state["pending_concerns"] = not all_resolved

        if (
            all_resolved
            and concerns
            and state.get("announced")
            and not state.get("is_undiscovered_concerns", True)
        ):
            state["phase"] = PHASE_SECURE
