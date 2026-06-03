from types import SimpleNamespace

from app.services.model_preflight import check_models_list


def test_check_models_list_treats_malformed_json_as_no_match():
    class Response:
        status_code = 200

        def json(self):
            raise ValueError("bad json")

    class Session:
        def get(self, url):
            return Response()

    application = SimpleNamespace(state=SimpleNamespace(model_check={}))
    settings = SimpleNamespace(
        VERTEX_LOCATION="global",
        PROJECT_ID="test-project",
        MODEL_ID="test-model",
    )

    check_models_list(application, settings=settings, session=Session())

    assert application.state.model_check["listCount"] == 0
    assert application.state.model_check["listMatched"] is False
