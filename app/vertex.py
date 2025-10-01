from typing import Optional
import logging

from google.api_core import exceptions as gax_exceptions
from google.cloud import aiplatform
from vertexai import init as vertex_init
from vertexai.generative_models import GenerativeModel, GenerationConfig


class VertexAIError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class VertexClient:
    def __init__(self, project: str, region: str, model_id: str):
        self.logger = logging.getLogger("app.vertex")
        self.project = project
        self.region = region
        self.model_id = model_id

    def _init(self):
        # Initialize only when needed (each request) to be safe in serverless envs
        self.logger.debug("vertex_init(project=%s, region=%s)", self.project, self.region)
        vertex_init(project=self.project, location=self.region)

    def generate_text(
        self,
        prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 256,
        system_instruction: Optional[str] = None,
    ) -> str:
        try:
            self._init()
            self.logger.debug("Creating GenerativeModel(model_id=%s)", self.model_id)
            model = GenerativeModel(self.model_id, system_instruction=system_instruction)
            config = GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
            self.logger.debug("Calling generate_content(prompt_len=%s, temperature=%s, max_tokens=%s)", len(prompt or ""), temperature, max_tokens)
            response = model.generate_content(
                [prompt],
                generation_config=config,
            )
            # Try the simple accessor first
            text = getattr(response, "text", None)
            if text:
                return text.strip()
            # Fallback: aggregate text parts
            candidates = getattr(response, "candidates", None) or []
            for c in candidates:
                content = getattr(c, "content", None)
                if not content:
                    continue
                parts = getattr(content, "parts", None) or []
                texts = [getattr(p, "text", "") for p in parts]
                joined = "".join([t for t in texts if t])
                if joined:
                    return joined.strip()
            raise VertexAIError("No text candidates returned from model")
        except (gax_exceptions.NotFound,) as e:
            # Specific handling: model not found or no access
            self.logger.exception("Vertex AI API error (NotFound)")
            raise VertexAIError(f"Vertex AI API error: {e}", status_code=404) from e
        except (gax_exceptions.GoogleAPICallError, gax_exceptions.RetryError, gax_exceptions.DeadlineExceeded) as e:
            self.logger.exception("Vertex AI API error")
            # Preserve status code when available
            code = getattr(e, "code", None)
            try:
                code = int(code.value[0]) if hasattr(code, "value") else int(code)
            except Exception:
                code = None
            raise VertexAIError(f"Vertex AI API error: {e}", status_code=code) from e
        except Exception as e:
            self.logger.exception("Vertex client unexpected error")
            raise VertexAIError(str(e)) from e
