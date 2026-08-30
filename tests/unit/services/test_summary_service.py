import json

from app.services.summary_service import (
    _enforce_metrics_consistency,
    _structured_analysis_bullets,
)


def test_structured_analysis_bullets_renders_sections_and_drops_bad_metric_note():
    narrative = json.dumps(
        {
            "overall_commentary": "Good rapport with room to slow down.",
            "strengths": ["Announce was clear."],
            "growth_areas": ["Mirror could go deeper."],
            "metric_notes": [
                {
                    "step": "Mirror",
                    "status": "not_used",
                    "text": "Mirror was skipped.",
                },
                {
                    "step": "Secure",
                    "status": "not_used",
                    "text": "Secure was not used.",
                },
            ],
        }
    )

    bullets = _structured_analysis_bullets(
        narrative,
        {
            "Announce": 1,
            "Inquire": 1,
            "Mirror": 1,
            "Secure": 0,
        },
    )

    assert bullets == [
        "Good rapport with room to slow down.",
        "Announce was clear.",
        "Mirror could go deeper.",
        "Secure was not used.",
    ]


def test_structured_analysis_bullets_accepts_fenced_json():
    narrative = """```json
{"overall_commentary":"Good work.","strengths":[],"growth_areas":[],"metric_notes":[]}
```"""

    assert _structured_analysis_bullets(narrative, {}) == ["Good work."]


def test_structured_analysis_bullets_returns_none_for_legacy_text():
    narrative = "- Good use of inquiry\n- Consider mirroring once more"

    assert _structured_analysis_bullets(narrative, {}) is None


def test_structured_analysis_bullets_strips_prose_preamble_before_fenced_json():
    # Reproduces a real staging leak: the model prepended "Here is the JSON
    # requested:" before the fenced block instead of returning it bare, so
    # the raw.startswith("```") check missed it and the preamble fell through
    # to the raw-line fallback, rendering as a visible summary bullet.
    narrative = (
        "Here is the JSON requested:\n\n```json\n"
        '{"overall_commentary":"Good work.","strengths":[],"growth_areas":[],"metric_notes":[]}\n'
        "```"
    )

    assert _structured_analysis_bullets(narrative, {}) == ["Good work."]


def test_structured_analysis_bullets_strips_prose_preamble_before_bare_json():
    narrative = (
        'Here is the JSON requested:\n{"overall_commentary":"Good work.",'
        '"strengths":[],"growth_areas":[],"metric_notes":[]}'
    )

    assert _structured_analysis_bullets(narrative, {}) == ["Good work."]


def test_legacy_metrics_consistency_still_rewrites_text_fallback():
    bullets = _enforce_metrics_consistency(
        ["Mirror was skipped.", "Keep this."],
        {"Mirror": 1},
    )

    assert bullets[0].startswith("Mirror was used")
    assert bullets[1] == "Keep this."
