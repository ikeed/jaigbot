from app.core.session_serialization import serialize_session_bootstrap_payload
from app.core.session_types import SessionBootstrapPayload, StartupArtifact


def test_serialize_session_bootstrap_payload_preserves_compatibility_fields():
    payload = SessionBootstrapPayload(
        module_id="aims",
        session_id="sid-1",
        already_active=True,
        participant_context={"character": "Person: Zia", "scene": "Reason for visit"},
        module_state={"persona": {"name": "Zia"}, "personaId": "zia", "personaName": "Zia"},
        artifacts=(StartupArtifact(kind="scenario_card", title="Scenario Briefing", content="Person: Zia"),),
    )

    data = serialize_session_bootstrap_payload(payload)

    assert data == {
        "status": "ok",
        "moduleId": "aims",
        "sessionId": "sid-1",
        "alreadyActive": True,
        "character": "Person: Zia",
        "scene": "Reason for visit",
        "persona": {"name": "Zia"},
        "personaId": "zia",
        "personaName": "Zia",
        "initialCard": "Person: Zia",
    }


def test_serialize_session_bootstrap_payload_includes_transport_metadata_when_present():
    payload = SessionBootstrapPayload(
        module_id="aims",
        session_id="sid-2",
        transport_metadata={"source": "module"},
    )

    data = serialize_session_bootstrap_payload(payload)

    assert data["transport"] == {"source": "module"}
