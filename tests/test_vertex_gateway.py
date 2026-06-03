import pytest

from app.services.vertex_gateway import VertexGateway


class FakeClient:
    calls = []
    behavior = {}

    def __init__(self, project, region, model_id):
        self.project = project
        self.region = region
        self.model_id = model_id

    def generate_text(self, *args, **kwargs):
        FakeClient.calls.append((self.model_id, args, kwargs))
        action = FakeClient.behavior.get(self.model_id)
        if action is None:
            return "ok from %s" % self.model_id
        if isinstance(action, Exception):
            raise action
        if action == "tuple":
            return "tuple-ok %s" % self.model_id, {"usage": 1}
        if callable(action):
            return action(*args, **kwargs)
        return str(action)


def setup_function(fn):
    FakeClient.calls = []
    FakeClient.behavior = {}


def test_generate_text_fallbacks_and_normalization():
    # first model fails, second succeeds with tuple result
    FakeClient.behavior = {
        "primary": RuntimeError("boom"),
        "fallback": "tuple",  # return (text, meta)
    }
    gw = VertexGateway(project="p", region="r", primary_model="primary", fallbacks=["fallback"], client_cls=FakeClient)

    order = []
    def on_fb(mid):
        order.append(mid)

    out = gw.generate_text(prompt="hi", system_instruction="sys", log_fallback=on_fb)
    assert out.startswith("tuple-ok fallback")
    # ensure fallback was reported for the failed primary
    assert order == ["primary"]
    # ensure both models were attempted in order
    models_called = [mid for (mid, _args, _kw) in [(c[0], c[1], c[2]) for c in FakeClient.calls]]
    assert models_called == ["primary", "fallback"]


def test_generate_text_json_uses_same_fallback_logic():
    FakeClient.behavior = {
        "m1": RuntimeError("fail1"),
        "m2": "ok-json",
    }
    gw = VertexGateway(project="p", region="r", primary_model="m1", fallbacks=["m2"], client_cls=FakeClient)

    order = []
    def on_fb(mid):
        order.append(mid)

    out = gw.generate_text_json(prompt="{}", response_schema={"type": "object"}, system_instruction=None, log_fallback=on_fb)
    assert out == "ok-json"
    assert order == ["m1"]


def test_all_fail_raises_last_error():
    FakeClient.behavior = {
        "a": RuntimeError("A"),
        "b": RuntimeError("B"),
    }
    gw = VertexGateway(project="p", region="r", primary_model="a", fallbacks=["b"], client_cls=FakeClient)
    with pytest.raises(RuntimeError) as ei:
        gw.generate_text(prompt="x")
    # Last error should be from the last attempted model (b)
    assert str(ei.value) == "B"


class AsyncFakeClient:
    calls = []
    behavior = {}

    def __init__(self, project, region, model_id):
        self.model_id = model_id

    async def generate_text_async(self, *args, **kwargs):
        AsyncFakeClient.calls.append((self.model_id, args, kwargs))
        action = AsyncFakeClient.behavior.get(self.model_id)
        if isinstance(action, Exception):
            raise action
        return action or f"async-ok-{self.model_id}"


@pytest.mark.asyncio
async def test_agenerate_text_fallbacks_and_records_last_model():
    AsyncFakeClient.calls = []
    AsyncFakeClient.behavior = {
        "primary": RuntimeError("rate limited"),
        "fallback": "fallback-ok",
    }
    gateway = VertexGateway(
        project="p",
        region="r",
        primary_model="primary",
        fallbacks=["primary", "fallback"],
        client_cls=AsyncFakeClient,
    )
    failed_models = []

    result = await gateway.agenerate_text(
        prompt="hello",
        system_instruction="sys",
        log_fallback=failed_models.append,
    )

    assert result == "fallback-ok"
    assert gateway.last_model_used == "fallback"
    assert failed_models == ["primary"]
    assert [call[0] for call in AsyncFakeClient.calls] == ["primary", "fallback"]
    assert AsyncFakeClient.calls[0][2]["system_instruction"] == "sys"


@pytest.mark.asyncio
async def test_agenerate_text_json_passes_json_options_and_raises_last_error():
    AsyncFakeClient.calls = []
    AsyncFakeClient.behavior = {
        "m1": RuntimeError("503 overloaded"),
        "m2": RuntimeError("429 rate limited"),
    }
    gateway = VertexGateway(
        project="p",
        region="r",
        primary_model="m1",
        fallbacks=["m2"],
        client_cls=AsyncFakeClient,
    )

    with pytest.raises(RuntimeError, match="429 rate limited"):
        await gateway.agenerate_text_json(
            prompt="{}",
            response_schema={"type": "object"},
            system_instruction="sys",
        )

    assert [call[0] for call in AsyncFakeClient.calls] == ["m1", "m2"]
    assert AsyncFakeClient.calls[0][2]["response_mime_type"] == "application/json"
    assert AsyncFakeClient.calls[0][2]["response_schema"] == {"type": "object"}


def test_generate_text_fallback_callback_exception_does_not_interrupt_fallback():
    FakeClient.behavior = {
        "primary": RuntimeError("503 overloaded"),
        "fallback": "fallback-ok",
    }
    gateway = VertexGateway(
        project="p",
        region="r",
        primary_model="primary",
        fallbacks=["fallback"],
        client_cls=FakeClient,
    )

    def failing_callback(model_id):
        raise RuntimeError(f"callback failed for {model_id}")

    assert gateway.generate_text(prompt="x", log_fallback=failing_callback) == "fallback-ok"
    assert gateway.last_model_used == "fallback"
