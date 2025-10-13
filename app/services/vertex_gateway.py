import json
from typing import List, Optional

from ..vertex import VertexClient as DefaultVertexClient


class VertexGateway:
    """Thin wrapper around VertexClient providing model-fallback and typed calls.

    This abstraction improves testability and removes duplicated fallback loops.
    It intentionally mirrors existing behavior from app.main._vertex_call and
    _vertex_call_json, including return value normalization and logging event
    shapes (delegated to caller).
    """

    def __init__(
        self,
        project: Optional[str],
        region: str,
        primary_model: str,
        fallbacks: Optional[List[str]] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        client_cls=None,
    ) -> None:
        self.project = project
        self.region = region
        self.primary_model = primary_model
        self.fallbacks = [m for m in (fallbacks or []) if m and m != primary_model]
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.client_cls = client_cls or DefaultVertexClient

    def _models_to_try(self) -> List[str]:
        return [self.primary_model] + self.fallbacks

    @staticmethod
    def _normalize_result(result) -> str:
        # Preserve historical behavior: support tuple(result, usage) and plain strings
        if isinstance(result, tuple) and len(result) == 2:
            return str(result[0])
        return str(result)

    def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        log_fallback: Optional[callable] = None,
    ) -> str:
        last_err = None
        for mid in self._models_to_try():
            client = self.client_cls(project=self.project, region=self.region, model_id=mid)
            try:
                try:
                    result = client.generate_text(
                        prompt=prompt,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        system_instruction=system_instruction,
                    )
                except TypeError:
                    # Backward compatibility for older client signature
                    result = client.generate_text(prompt, self.temperature, self.max_tokens)
                return self._normalize_result(result)
            except Exception as e:
                last_err = e
                if log_fallback:
                    log_fallback(mid)
                continue
        if last_err:
            raise last_err
        raise RuntimeError("Vertex call failed with no models attempted")

    def generate_text_json(
        self,
        prompt: str,
        response_schema: dict,
        system_instruction: Optional[str] = None,
        log_fallback: Optional[callable] = None,
    ) -> str:
        last_err = None
        for mid in self._models_to_try():
            client = self.client_cls(project=self.project, region=self.region, model_id=mid)
            try:
                try:
                    result = client.generate_text(
                        prompt=prompt,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=response_schema,
                    )
                except TypeError:
                    # Backward compatibility for older client signature
                    result = client.generate_text(prompt, self.temperature, self.max_tokens)
                return self._normalize_result(result)
            except Exception as e:
                last_err = e
                if log_fallback:
                    log_fallback(mid)
                continue
        if last_err:
            raise last_err
        raise RuntimeError("Vertex call failed with no models attempted")
