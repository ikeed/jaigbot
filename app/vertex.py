from typing import Optional, Tuple, List, Dict, Any
import logging
import os
import warnings
import json

from google.api_core import exceptions as gax_exceptions
from google.cloud import aiplatform
import google.auth
from google.auth.transport.requests import AuthorizedSession
from vertexai import init as vertex_init
from vertexai.generative_models import GenerativeModel, GenerationConfig

# Configurable behavior via env vars
SUPPRESS_VERTEXAI_DEPRECATION = os.getenv("SUPPRESS_VERTEXAI_DEPRECATION", "true").lower() == "true"
# Default ON: enable auto-continue to mitigate truncated outputs unless explicitly disabled via env
AUTO_CONTINUE_ON_MAX_TOKENS = os.getenv("AUTO_CONTINUE_ON_MAX_TOKENS", "true").lower() == "true"
MAX_CONTINUATIONS = int(os.getenv("MAX_CONTINUATIONS", "2"))
# Continuation strategy tuning
CONTINUE_TAIL_CHARS = int(os.getenv("CONTINUE_TAIL_CHARS", "500"))
CONTINUE_INSTRUCTION_ENABLED = os.getenv("CONTINUE_INSTRUCTION_ENABLED", "true").lower() == "true"
MIN_CONTINUE_GROWTH = int(os.getenv("MIN_CONTINUE_GROWTH", "10"))
# Default to REST for forward-compatibility and better control over thinking/response MIME
USE_VERTEX_REST = os.getenv("USE_VERTEX_REST", "true").lower() == "true"

# Optionally suppress the Vertex SDK deprecation warning noise
if SUPPRESS_VERTEXAI_DEPRECATION:
    warnings.filterwarnings(
        "ignore",
        message="This feature is deprecated as of",
        category=UserWarning,
        module="vertexai.generative_models._generative_models",
    )


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

    @staticmethod
    def _sanitize_response_schema(schema: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Return a copy of the schema with any $-prefixed meta-keys removed.
        Vertex AI responseSchema does not accept "$schema" or other $-draft keys.
        """
        if not schema:
            return None

        def _clean(obj):
            if isinstance(obj, dict):
                out: Dict[str, Any] = {}
                for k, v in obj.items():
                    if isinstance(k, str) and k.startswith("$"):
                        continue
                    out[k] = _clean(v)
                return out
            if isinstance(obj, list):
                return [_clean(x) for x in obj]
            return obj

        cleaned = _clean(schema)
        # If cleaning removed everything, treat as absent
        return cleaned if isinstance(cleaned, dict) and len(cleaned) > 0 else None

    @staticmethod
    def _merge_with_overlap(base: str, addition: str, max_overlap: int = 200) -> str:
        """
        Merge addition onto base by trimming any overlapping prefix of `addition`
        that already appears as a suffix of `base`. Additionally, normalize the
        boundary so words don't smash together when the model continues mid-word
        or mid-sentence. We only touch the join boundary; we do not alter inner
        whitespace.
        """
        if not base:
            return (addition or "").strip()
        if not addition:
            return base.strip()

        # Normalize ends, but keep one side's spacing so we can reason about the boundary.
        base_s = base.rstrip()  # keep left without trailing spaces
        add_s = addition.lstrip()  # keep right without leading spaces

        # Strip a leading wrapper like <<<...>>> if the model echoed our continuation hint
        if add_s.startswith("<<<") and ">>>" in add_s:
            add_s = add_s.split(">>>", 1)[-1].lstrip()

        # Only search overlap up to max_overlap or length of strings
        max_k = min(len(base_s), len(add_s), max_overlap)
        overlap = 0
        for k in range(max_k, 0, -1):
            if base_s.endswith(add_s[:k]):
                overlap = k
                break

        right_tail = add_s[overlap:]
        if not right_tail:
            return base_s.strip()

        # Decide if we need to insert a single space at the join boundary.
        left_ch = base_s[-1] if base_s else ""
        right_ch = right_tail[0] if right_tail else ""

        def is_word(c: str) -> bool:
            return c.isalnum()

        # Characters that should NOT have a space before them (closing or punctuation)
        no_space_before = set(",.;:!?)]}\u2019\u201d")  # include curly quotes
        # Characters that typically do NOT get a space after them (opening brackets/quotes)
        no_space_after = set("([\{\u2018\u201c\"")

        need_space = False
        if left_ch and right_ch and (not left_ch.isspace()) and (not right_ch.isspace()):
            if left_ch in no_space_after:
                need_space = False
            elif right_ch in no_space_before:
                need_space = False
            elif is_word(left_ch) and is_word(right_ch):
                # word-to-word boundary → insert a single space
                need_space = True
            elif left_ch in ".!?;:" and is_word(right_ch):
                # sentence boundary without a space
                need_space = True

        if need_space:
            joined = base_s + " " + right_tail
        else:
            joined = base_s + right_tail

        return joined.strip()

    def _init(self):
        # Initialize only when needed (each request) to be safe in serverless envs
        self.logger.debug("vertex_init(project=%s, region=%s)", self.project, self.region)
        vertex_init(project=self.project, location=self.region)

    def generate_text(
        self,
        prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        system_instruction: Optional[str] = None,
        response_mime_type: Optional[str] = None,
        response_schema: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, dict]:
        """
        Generate text and return both the text and useful metadata for logging.
        If the model halts with finishReason == MAX_TOKENS and AUTO_CONTINUE_ON_MAX_TOKENS
        is enabled, this method will automatically send up to MAX_CONTINUATIONS
        "continue" turns and concatenate the results.
        The return shape is (text, meta_dict).
        """
        if USE_VERTEX_REST:
            return self._generate_text_rest(prompt, temperature, max_tokens, system_instruction, response_mime_type, response_schema)
        return self._generate_text_sdk(prompt, temperature, max_tokens, system_instruction, response_mime_type, response_schema)

    def _generate_text_sdk(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
        system_instruction: Optional[str],
        response_mime_type: Optional[str],
        response_schema: Optional[Dict[str, Any]],
    ) -> tuple[str, dict]:
        try:
            self._init()
            self.logger.debug("Creating GenerativeModel(model_id=%s)", self.model_id)
            model = GenerativeModel(self.model_id, system_instruction=system_instruction)
            # Build GenerationConfig with optional JSON mode/schema
            _resp_mime = response_mime_type or "text/plain"
            try:
                _san_schema = self._sanitize_response_schema(response_schema) if _resp_mime == "application/json" else None
                config = GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    response_mime_type=_resp_mime,
                    response_schema=_san_schema,
                )
            except TypeError:
                # Older SDK may not support response_schema; retry without it
                config = GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    response_mime_type=_resp_mime,
                )

            # Use a chat session so we can preserve context across continuations
            # Disable SDK response validation so we can handle finish reasons/safety ourselves
            chat = model.start_chat(response_validation=False)

            self.logger.debug(
                "Calling send_message(prompt_len=%s, temperature=%s, max_tokens=%s)",
                len(prompt or ""),
                temperature,
                max_tokens,
            )
            response = chat.send_message(prompt, generation_config=config)

            # Helper to extract text/meta from a response
            def _extract(resp):
                # Accessing resp.text can raise ValueError if the candidate has no parts.
                # Guard it so we can fallback to inspecting candidate parts.
                txt = None
                try:
                    txt = resp.text  # may raise if response has no parts
                except Exception:
                    txt = None
                cands = getattr(resp, "candidates", None) or []
                if not txt:
                    for c in cands:
                        content = getattr(c, "content", None)
                        if not content:
                            continue
                        parts = getattr(content, "parts", None) or []
                        texts = [getattr(p, "text", "") for p in parts]
                        joined = "".join([t for t in texts if t])
                        if joined:
                            txt = joined
                            break
                usage_md = getattr(resp, "usage_metadata", None)
                if cands:
                    first = cands[0]
                    fr = getattr(first, "finish_reason", None)
                    safety = getattr(first, "safety_ratings", None) or []
                    safety_summary = [
                        {"category": getattr(s, "category", None), "prob": getattr(s, "probability", None), "blocked": getattr(s, "blocked", None)}
                        for s in safety
                    ]
                else:
                    fr = None
                    safety_summary = []
                fr_name = getattr(fr, "name", None) if hasattr(fr, "name") else fr
                meta_local = {
                    "finishReason": fr_name,
                    "promptTokens": getattr(usage_md, "prompt_token_count", None) if usage_md else None,
                    "candidatesTokens": getattr(usage_md, "candidates_token_count", None) if usage_md else None,
                    "totalTokens": getattr(usage_md, "total_token_count", None) if usage_md else None,
                    "thoughtsTokens": getattr(usage_md, "thoughts_token_count", None) if usage_md else None,
                    "safety": safety_summary,
                    "textLen": len((txt or "").strip()),
                }
                return (txt or "").strip(), meta_local

            text, meta_local = _extract(response)

            # Allow auto-continue even if the initial turn has no text (e.g., empty candidate parts or safety redaction).
            continuation_count = 0
            no_progress_break = False
            # Auto-continue loop if hitting output cap
            while (
                AUTO_CONTINUE_ON_MAX_TOKENS
                and meta_local.get("finishReason") in ("MAX_TOKENS", "MAX_TOKEN", "MAX_OUTPUT_TOKENS")
                and continuation_count < MAX_CONTINUATIONS
            ):
                continuation_count += 1
                tail = (text or "")[-CONTINUE_TAIL_CHARS:]
                if CONTINUE_INSTRUCTION_ENABLED:
                    cont_prompt = (
                        "Please continue exactly where you left off without repeating previous text.\n"
                        "Tail context follows. Continue seamlessly after it:\n" + tail + "\n(End of tail)"
                    )
                else:
                    cont_prompt = "continue"
                self.logger.debug("Auto-continue #%s (tail_chars=%s, instr=%s)", continuation_count, len(tail), CONTINUE_INSTRUCTION_ENABLED)
                next_resp = chat.send_message(cont_prompt, generation_config=config)
                next_text, next_meta = _extract(next_resp)
                prev_len = len(text)
                if next_text:
                    # Merge with overlap to avoid repeated intros across chunks
                    merged = self._merge_with_overlap(text, next_text)
                    text = merged
                # Update finish reason and rough token counts to the latest
                meta_local.update({
                    "finishReason": next_meta.get("finishReason"),
                    "promptTokens": next_meta.get("promptTokens"),
                    "candidatesTokens": next_meta.get("candidatesTokens"),
                    "totalTokens": next_meta.get("totalTokens"),
                    "textLen": len(text),
                })
                # Break on no progress to avoid loops
                if len(text) - prev_len < MIN_CONTINUE_GROWTH:
                    no_progress_break = True
                    break
                # If the new turn is not capped, break
                if next_meta.get("finishReason") not in ("MAX_TOKENS", "MAX_TOKEN", "MAX_OUTPUT_TOKENS"):
                    break

            # If after continuations we still have no text, surface a clearer error
            if not text:
                raise VertexAIError("No text candidates returned from model (possibly safety blocked)")

            # Build final metadata
            meta = {
                "model": self.model_id,
                **meta_local,
                "continuationCount": continuation_count,
                "transport": "sdk",
                "noProgressBreak": no_progress_break,
                "continueTailChars": CONTINUE_TAIL_CHARS,
                "continuationInstructionEnabled": CONTINUE_INSTRUCTION_ENABLED,
            }

            return text, meta
        except (gax_exceptions.NotFound,) as e:
            self.logger.exception("Vertex AI API error (NotFound)")
            raise VertexAIError(f"Vertex AI API error: {e}", status_code=404) from e
        except (
            gax_exceptions.GoogleAPICallError,
            gax_exceptions.RetryError,
            gax_exceptions.DeadlineExceeded,
        ) as e:
            self.logger.exception("Vertex AI API error")
            code = getattr(e, "code", None)
            try:
                code = int(code.value[0]) if hasattr(code, "value") else int(code)
            except Exception:
                code = None
            raise VertexAIError(f"Vertex AI API error: {e}", status_code=code) from e
        except Exception as e:
            self.logger.exception("Vertex client unexpected error")
            raise VertexAIError(str(e)) from e

    def _generate_text_rest(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
        system_instruction: Optional[str],
        response_mime_type: Optional[str],
        response_schema: Optional[Dict[str, Any]],
    ) -> tuple[str, dict]:
        """Generate using REST generateContent to avoid deprecated SDK surface."""
        try:
            creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            session = AuthorizedSession(creds)
            # Choose API version: Gemini 2.x models are currently exposed under v1beta; others can use v1
            api_version = "v1beta" if str(self.model_id).startswith("gemini-2") else "v1"
            loc = self.region
            host = "aiplatform.googleapis.com" if str(loc).lower() == "global" else f"{loc}-aiplatform.googleapis.com"
            base_url = f"https://{host}/{api_version}/projects/{self.project}/locations/{loc}/publishers/google/models/{self.model_id}:generateContent"
            try:
                self.logger.info(json.dumps({
                    "event": "vertex_rest_generate",
                    "apiVersion": api_version,
                    "baseUrl": base_url,
                    "location": loc,
                    "project": self.project,
                    "modelId": self.model_id,
                }))
            except Exception:
                self.logger.info("vertex_rest_generate %s", base_url)

            def call(contents: List[Dict[str, Any]]):
                _resp_mime = response_mime_type or "text/plain"
                body: Dict[str, Any] = {
                    "contents": contents,
                    "generationConfig": {
                        "temperature": temperature,
                        "maxOutputTokens": max_tokens,
                        "responseMimeType": _resp_mime
                    },
                }
                if response_schema and _resp_mime == "application/json":
                    _san_schema = self._sanitize_response_schema(response_schema)
                    if _san_schema:
                        body["generationConfig"]["responseSchema"] = _san_schema
                if system_instruction:
                    body["systemInstruction"] = {"role": "system", "parts": [{"text": system_instruction}]}
                r = session.post(base_url, json=body)
                if r.status_code == 404:
                    # Fallback across API versions on 404 (both directions)
                    alt_url = None
                    if "/v1/" in base_url:
                        alt_url = base_url.replace("/v1/", "/v1beta/", 1)
                    elif "/v1beta/" in base_url:
                        alt_url = base_url.replace("/v1beta/", "/v1/", 1)
                    if alt_url:
                        r2 = session.post(alt_url, json=body)
                        try:
                            self.logger.info(json.dumps({
                                "event": "vertex_rest_generate_fallback",
                                "from": base_url,
                                "to": alt_url,
                                "status": r2.status_code,
                            }))
                        except Exception:
                            pass
                        if r2.status_code < 400:
                            return r2.json()
                        # If the alt call also failed, propagate its status (only keep 404 if both are 404)
                        if r2.status_code == 404:
                            raise VertexAIError("Model not found: HTTP 404", status_code=404)
                        raise VertexAIError(f"Vertex REST error HTTP {r2.status_code}: {r2.text}", status_code=r2.status_code)
                    # No alt URL derivable; keep 404
                    raise VertexAIError("Model not found: HTTP 404", status_code=404)
                if r.status_code >= 400:
                    raise VertexAIError(f"Vertex REST error HTTP {r.status_code}: {r.text}", status_code=r.status_code)
                return r.json()

            # Initial request
            contents: List[Dict[str, Any]] = [
                {"role": "user", "parts": [{"text": prompt}]}
            ]
            data = call(contents)

            def extract_from_json(d: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
                cands = d.get("candidates", [])
                txt = ""
                if cands:
                    content = cands[0].get("content") or {}
                    parts = content.get("parts") or []
                    for p in parts:
                        t = p.get("text")
                        if t:
                            txt += t
                usage = d.get("usageMetadata") or {}
                fr = (cands[0].get("finishReason") if cands else None)
                safety = cands[0].get("safetyRatings", []) if cands else []
                safety_summary = [
                    {"category": s.get("category"), "prob": s.get("probability"), "blocked": s.get("blocked")}
                    for s in safety
                ]
                meta_local = {
                    "finishReason": fr,
                    "promptTokens": usage.get("promptTokenCount"),
                    "candidatesTokens": usage.get("candidatesTokenCount"),
                    "totalTokens": usage.get("totalTokenCount"),
                    "thoughtsTokens": usage.get("thoughtsTokenCount"),
                    "safety": safety_summary,
                    "textLen": len(txt.strip()),
                }
                return txt.strip(), meta_local

            text, meta_local = extract_from_json(data)

            # Allow auto-continue even if the initial turn has no text.
            continuation_count = 0
            no_progress_break = False
            last_assistant_text = text  # Track only the last assistant chunk for chat history
            while (
                AUTO_CONTINUE_ON_MAX_TOKENS
                and meta_local.get("finishReason") in ("MAX_TOKENS", "MAX_TOKEN", "MAX_OUTPUT_TOKENS")
                and continuation_count < MAX_CONTINUATIONS
            ):
                continuation_count += 1
                # Append only the last assistant chunk, not the cumulative text
                if last_assistant_text:
                    contents.append({"role": "model", "parts": [{"text": last_assistant_text}]})
                # Build a more explicit continuation instruction with tail context
                tail = (text or "")[-CONTINUE_TAIL_CHARS:]
                if CONTINUE_INSTRUCTION_ENABLED:
                    cont_prompt = (
                        "Please continue exactly where you left off without repeating previous text.\n"
                        "Tail context follows. Continue seamlessly after it:\n" + tail + "\n(End of tail)"
                    )
                else:
                    cont_prompt = "continue"
                contents.append({"role": "user", "parts": [{"text": cont_prompt}]})
                data = call(contents)
                next_text, next_meta = extract_from_json(data)
                prev_len = len(text)
                if next_text:
                    merged = self._merge_with_overlap(text, next_text)
                    text = merged
                    last_assistant_text = next_text
                else:
                    last_assistant_text = ""
                meta_local.update({
                    "finishReason": next_meta.get("finishReason"),
                    "promptTokens": next_meta.get("promptTokens"),
                    "candidatesTokens": next_meta.get("candidatesTokens"),
                    "totalTokens": next_meta.get("totalTokens"),
                    "textLen": len(text),
                })
                # Break on no progress to avoid loops
                if len(text) - prev_len < MIN_CONTINUE_GROWTH:
                    no_progress_break = True
                    break
                if next_meta.get("finishReason") not in ("MAX_TOKENS", "MAX_TOKEN", "MAX_OUTPUT_TOKENS"):
                    break

            meta = {
                "model": self.model_id,
                **meta_local,
                "continuationCount": continuation_count,
                "transport": "rest",
                "noProgressBreak": no_progress_break,
                "continueTailChars": CONTINUE_TAIL_CHARS,
                "continuationInstructionEnabled": CONTINUE_INSTRUCTION_ENABLED,
            }
            return text, meta
        except VertexAIError:
            raise
        except Exception as e:
            self.logger.exception("Vertex REST unexpected error")
            raise VertexAIError(str(e)) from e
