from app.core.session_serialization import serialize_session_bootstrap_payload
from app.core.session_types import SessionBootstrapPayload, StartupArtifact


def test_serialize_session_bootstrap_payload_preserves_compatibility_fields():
    payload = SessionBootstrapPayload(
        module_id="aims",
        session_id="sid-1",
        already_active=True,
        participant_context={"character": "Person: Zia", "scene": "Reason for visit"},
        module_state={"persona": {"name": "Zia"}, "personaId": "zia", "personaName": "Zia"},
        artifacts=(
            StartupArtifact(kind="scenario_card", title="Scenario Briefing", content="Person: Zia"),
            StartupArtifact(kind="checklist", title="Checklist", content="Use AIMS", metadata={"priority": 1}),
        ),
    )

    data = serialize_session_bootstrap_payload(payload)

    assert data["status"] == "ok"
    assert data["moduleId"] == "aims"
    assert data["sessionId"] == "sid-1"
    assert data["alreadyActive"] is True
    assert data["character"] == "Person: Zia"
    assert data["scene"] == "Reason for visit"
    assert data["persona"] == {"name": "Zia"}
    assert data["personaId"] == "zia"
    assert data["personaName"] == "Zia"
    assert data["initialCard"] == "Person: Zia"
    assert data["module"] == {
        "id": "aims",
        "participantContext": {"character": "Person: Zia", "scene": "Reason for visit"},
        "state": {"persona": {"name": "Zia"}, "personaId": "zia", "personaName": "Zia"},
        "artifacts": [
            {
                "kind": "scenario_card",
                "title": "Scenario Briefing",
                "content": "Person: Zia",
                "metadata": {},
            },
            {
                "kind": "checklist",
                "title": "Checklist",
                "content": "Use AIMS",
                "metadata": {"priority": 1},
            },
        ],
    }


def test_serialize_session_bootstrap_payload_includes_transport_metadata_when_present():
    payload = SessionBootstrapPayload(
        module_id="aims",
        session_id="sid-2",
        transport_metadata={"source": "module"},
    )

    data = serialize_session_bootstrap_payload(payload)

    assert data["transport"] == {"source": "module"}


def test_serialize_session_bootstrap_payload_keeps_generic_structure_without_compatibility_aliases():
    payload = SessionBootstrapPayload(
        module_id="interview",
        session_id="sid-3",
        participant_context={"role": "Hiring Manager"},
        module_state={"round": "onsite"},
        artifacts=(StartupArtifact(kind="interview_brief", title="Interview Setup", content="Discuss one project"),),
    )

    data = serialize_session_bootstrap_payload(payload)

    assert data["module"] == {
        "id": "interview",
        "participantContext": {"role": "Hiring Manager"},
        "state": {"round": "onsite"},
        "artifacts": [
            {
                "kind": "interview_brief",
                "title": "Interview Setup",
                "content": "Discuss one project",
                "metadata": {},
            }
        ],
    }
    assert data["character"] is None
    assert data["scene"] is None
    assert data["persona"] is None
    assert data["initialCard"] == "Discuss one project"
