from typing import Optional

from google.api_core import exceptions as gax_exceptions
from google.cloud import aiplatform
from vertexai import init as vertex_init
from vertexai.generative_models import GenerativeModel, GenerationConfig


class VertexAIError(Exception):
    pass


class VertexClient:
    def __init__(self, project: str, region: str, model_id: str):
        self.project = project
        self.region = region
        self.model_id = model_id

    def _init(self):
        # Initialize only when needed (each request) to be safe in serverless envs
        vertex_init(project=self.project, location=self.region)

    def generate_text(
        self,
        prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        system_instruction: Optional[str] = None,
    ) -> str:
        try:
            self._init()
            model = GenerativeModel(self.model_id, system_instruction=system_instruction)
            config = GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
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
        except (gax_exceptions.GoogleAPICallError, gax_exceptions.RetryError, gax_exceptions.DeadlineExceeded) as e:
            raise VertexAIError(f"Vertex AI API error: {e}") from e
        except Exception as e:
            raise VertexAIError(str(e)) from e
