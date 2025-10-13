import pytest

from app.services.vertex_gateway import VertexGateway


class TypeErrorClient:
    def __init__(self, project, region, model_id):
        self.model_id = model_id

    # Define generate_text that only supports positional args to trigger TypeError on kwargs
    def generate_text(self, prompt, temperature, max_tokens):
        # Return tuple to test normalization
        return (f"ok-{self.model_id}", {"usage": 1})


def test_generate_text_typeerror_compatibility():
    gw = VertexGateway(project="p", region="r", primary_model="m", fallbacks=[], client_cls=TypeErrorClient)
    out = gw.generate_text(prompt="hi", system_instruction="ignored")
    assert out == "ok-m"


def test_generate_text_json_typeerror_compatibility():
    gw = VertexGateway(project="p", region="r", primary_model="m", fallbacks=[], client_cls=TypeErrorClient)
    out = gw.generate_text_json(prompt="{}", response_schema={})
    assert out == "ok-m"


class AlwaysFailClient:
    def __init__(self, project, region, model_id):
        self.model_id = model_id
    def generate_text(self, *args, **kwargs):
        raise RuntimeError(f"fail-{self.model_id}")


def test_generate_text_json_raises_last_error():
    gw = VertexGateway(project="p", region="r", primary_model="a", fallbacks=["b"], client_cls=AlwaysFailClient)
    with pytest.raises(RuntimeError) as ei:
        gw.generate_text_json(prompt="{}", response_schema={})
    # Last attempted should be 'b'
    assert "fail-b" in str(ei.value)
