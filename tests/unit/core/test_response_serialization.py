from app.core.response_serialization import game_over_completion, serialize_response_envelope
from app.core.response_types import ModuleResponseEnvelope


def test_serialize_response_envelope_preserves_generic_and_compatibility_fields():
    envelope = ModuleResponseEnvelope(
        module_id="aims",
        reply="hello",
        model="gemini-test",
        latency_ms=12,
        session={"totalTurns": 1},
        feedback={"step": "Announce"},
        artifacts=({"kind": "briefing"},),
        events=({"type": "training_start"},),
        summary={"overallScore": 2.0},
        completion=game_over_completion({"title": "Done"}),
        transport_metadata={"source": "module"},
    )

    payload = serialize_response_envelope(
        envelope,
        session_id="sid-1",
        compatibility_overrides={"coaching": {"step": "Announce"}, "coachPost": {"title": "Done"}},
    )

    assert payload["reply"] == "hello"
    assert payload["text"] == "hello"
    assert payload["model"] == "gemini-test"
    assert payload["modelId"] == "gemini-test"
    assert payload["latencyMs"] == 12
    assert payload["latency_ms"] == 12
    assert payload["session"] == {"totalTurns": 1}
    assert payload["summary"] == {"overallScore": 2.0}
    assert payload["artifacts"] == [{"kind": "briefing"}]
    assert payload["events"] == [{"type": "training_start"}]
    assert payload["transport"] == {"source": "module"}
    assert payload["sessionId"] == "sid-1"
    assert payload["gameOver"] is True
    assert payload["coaching"] == {"step": "Announce"}
    assert payload["coachPost"] == {"title": "Done"}
