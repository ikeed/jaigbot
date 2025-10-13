from __future__ import annotations

from typing import Dict, List


class VaccineRelevanceGate:
    """Applies vaccine-relevance gating to a classification payload.

    Mirrors the logic in main.py exactly to avoid behavior changes.
    """

    VAX_CUES = [
        "vaccine",
        "vaccin",
        "shot",
        "jab",
        "jabs",
        "mmr",
        "measles",
        "booster",
        "immuniz",
        "side effect",
        "adverse event",
        "vaers",
        "thimerosal",
        "immunity",
        "immune",
        "schedule",
        "dose",
        "hib",
        "pcv",
        "hepb",
        "mmrv",
        "rotavirus",
        "pertussis",
        "varicella",
        "dtap",
        "polio",
        "option",
        "options",
        "decision",
    ]

    VALID_STEPS = {"Announce", "Inquire", "Mirror", "Secure", "Mirror+Inquire"}

    @staticmethod
    def gate(
        *,
        cls_payload: Dict,
        clinician_text: str,
        parent_last: str,
        parent_recent_concerns: List[str],
        prior_announced: bool,
    ) -> Dict:
        lt_msg = (clinician_text or "").strip().lower()
        pt_msg = (parent_last or "").strip().lower()
        ctx_blob = ("\n".join(parent_recent_concerns) if parent_recent_concerns else "").lower()

        is_vax_related = (
            any(cue in lt_msg for cue in VaccineRelevanceGate.VAX_CUES)
            or any(cue in pt_msg for cue in VaccineRelevanceGate.VAX_CUES)
            or any(cue in ctx_blob for cue in VaccineRelevanceGate.VAX_CUES)
            or bool(prior_announced)
        )

        if not is_vax_related and (cls_payload.get("step") in VaccineRelevanceGate.VALID_STEPS):
            return {
                "step": None,
                "score": 0,
                "reasons": [
                    "Non-vaccine rapport/small talk — AIMS not applied"
                ],
                "tips": [
                    "When you're ready, lead with a brief vaccine-specific Announce."
                ],
            }

        return cls_payload


class AimsPostProcessor:
    """Applies post-hoc corrections and score normalization to classification.

    Exact behavior preserved from main.py.
    """

    @staticmethod
    def correct_inquire_to_secure(cls_payload: Dict, clinician_text: str) -> Dict:
        lt = (clinician_text or "").strip().lower()
        if (cls_payload.get("step") == "Inquire") and ("?" not in lt):
            if any(
                tok in lt
                for tok in [
                    "study",
                    "studies",
                    "evidence",
                    "data",
                    "statistic",
                    "percent",
                    "%",
                    "risk",
                    "safe",
                    "side effect",
                    "protect",
                    "immun",
                    "schedule",
                    "dose",
                    "herd immunity",
                ]
            ):
                cls_payload = dict(cls_payload)
                cls_payload["reasons"] = [
                    "Didactic education detected; overriding Inquire to Secure"
                ] + (cls_payload.get("reasons") or [])
                cls_payload["step"] = "Secure"
        return cls_payload

    @staticmethod
    def normalize_score(cls_payload: Dict) -> Dict:
        if (
            cls_payload.get("step") in {"Announce", "Inquire", "Mirror", "Secure", "Mirror+Inquire"}
            and int(cls_payload.get("score", 0)) < 1
        ):
            cls_payload = dict(cls_payload)
            cls_payload["score"] = 1
        return cls_payload

    @staticmethod
    def post_process(cls_payload: Dict, clinician_text: str) -> Dict:
        cls_payload = AimsPostProcessor.correct_inquire_to_secure(cls_payload, clinician_text)
        cls_payload = AimsPostProcessor.normalize_score(cls_payload)
        return cls_payload
