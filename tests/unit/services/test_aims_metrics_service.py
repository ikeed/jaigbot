from app.constants import KEY_AIMS_METRICS
from app.services.aims_metrics_service import AimsMetricsService


class DummyLogger:
    def __init__(self):
        self.debug_messages = []

    def debug(self, message, *args):
        self.debug_messages.append(message % args if args else message)


def test_component_steps_expands_compounds_and_deduplicates():
    assert AimsMetricsService.component_steps(
        "Mirror+Secure",
        ["Announce+Inquire", "Mirror"],
    ) == ["Announce", "Inquire", "Mirror", "Secure"]


def test_persist_counts_compound_step_and_running_averages():
    service = AimsMetricsService(logger=DummyLogger())
    mem = {}

    service.persist(mem, {"step": "Announce+Inquire", "score": 3})
    service.persist(mem, {"step": "Announce", "score": 1})

    aims = mem[KEY_AIMS_METRICS]
    assert aims["totalTurns"] == 2
    assert aims["perStepCounts"]["Announce+Inquire"] == 1
    assert aims["perStepCounts"]["Announce"] == 2
    assert aims["perStepCounts"]["Inquire"] == 1
    assert aims["runningAverage"]["Announce"] == 2.0


def test_build_summary_handles_none_empty_and_existing_scores():
    service = AimsMetricsService(logger=DummyLogger())

    assert service.build_summary(None) is None

    empty_summary = service.build_summary({})
    assert empty_summary["totalTurns"] == 0
    assert empty_summary["perStepCounts"]["Announce"] == 0
    assert empty_summary["runningAverage"] == {}

    summary = service.build_summary({
        "persona": {"name": "Zia", "patient_name": "Nathaniel"},
        KEY_AIMS_METRICS: {
            "totalTurns": 2,
            "perStepCounts": {"Mirror": 2},
            "scores": {"Mirror": [2, 3]},
        }
    })
    assert summary["totalTurns"] == 2
    assert summary["perStepCounts"]["Mirror"] == 2
    assert summary["runningAverage"]["Mirror"] == 2.5
    assert summary["personaName"] == "Zia"
    assert summary["patientName"] == "Nathaniel"


def test_running_average_errors_are_logged_and_skipped():
    logger = DummyLogger()
    service = AimsMetricsService(logger=logger)

    summary = service.build_summary({
        KEY_AIMS_METRICS: {
            "scores": {"Announce": ["bad"]},
        }
    })

    assert "Announce" not in summary["runningAverage"]
    assert any("Failed to calculate running average" in message for message in logger.debug_messages)
