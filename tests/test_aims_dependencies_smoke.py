from app.services import aims_dependencies as deps


def test_aims_dependency_protocols_are_defined():
    assert hasattr(deps, "ClassifierDependency")
    assert hasattr(deps, "PatientReplyDependency")
    assert hasattr(deps, "AimsMetricsDependency")
    assert hasattr(deps, "CoachFeedbackHistoryDependency")
    assert hasattr(deps, "AimsStateDependency")
    assert hasattr(deps, "AimsEndgameDependency")
    assert hasattr(deps, "AimsTelemetryDependency")
    assert hasattr(deps, "AimsTurnCoordinatorDependency")
