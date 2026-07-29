import json
from unittest.mock import Mock, patch

from app.services.aims_turn_telemetry import AimsTurnTelemetry


def test_classify_end_logs_semantic_contract_flags():
    logger = Mock()
    telemetry = AimsTurnTelemetry(logger=logger, model_id="configured-model")

    with patch("app.services.aims_turn_telemetry.time.time", return_value=10.5):
        telemetry.classify_end(
            session_id="sid",
            request_id="req",
            started=10.0,
            model_used="gemini",
            step="Mirror",
            score=3,
            semantic_contract={
                "observations": True,
                "feedback_items": False,
                "person_events": True,
                "resolution": False,
            },
        )

    payload = json.loads(logger.info.call_args.args[0])
    assert payload["event"] == "aims_classify_end"
    assert payload["durationMs"] == 500
    assert payload["hasObservations"] is True
    assert payload["hasFeedbackItems"] is False
    assert payload["hasPersonEvents"] is True
    assert payload["hasResolution"] is False
