import json
import logging
import threading
from typing import Any

from google import genai
from google.genai import types
from google.genai.errors import APIError

# Continuation behaviour now comes from app.config.Settings, resolved per call. It used to
# be read here with os.getenv at import time, which meant /config and /diagnostics reported
# settings.* while this module used whatever the environment held when it was first
# imported — and under `uvicorn app.main:app` those disagree, because only run_app.py and
# chainlit_app.py push .env into os.environ.
MAX_TOKEN_FINISH_REASONS = frozenset({"MAX_TOKENS", "MAX_TOKEN", "MAX_OUTPUT_TOKENS"})

# Gen AI clients, shared per (project, location). A GeminiClient is constructed per LLM
# call — two to four times per coaching turn — and each one used to build its own
# genai.Client, which means its own google.auth.default() resolution and access-token
# fetch, plus its own TLS setup. The model id is deliberately NOT part of the key: it is a
# per-request argument to generate_content, never client state, so one client serves every
# model and the model-fallback loop costs nothing extra.
#
# The factory object is part of the key, and that detail is load-bearing. Tests
# monkeypatch app.gemini_client.genai.Client with a fresh fake class per test; keying on
# (project, location) alone hands one test's fake to the next test, which breaks 6 of the
# 15 tests in tests/unit/test_gemini_client_unit.py. Keying on the factory makes cross-test bleed
# impossible by construction, since monkeypatch installs a new class object each time.
#
# KNOWN TRADE-OFF, worth reading before debugging a mysterious stall: sharing a client
# also shares its aiohttp connection pool, so requests now reuse keep-alive connections.
# When the server closes one first, google-genai raises ServerDisconnectedError (or
# ClientOSError) and retries once after `1 + random.randint(0, 9)` seconds
# (google/genai/_api_client.py, non-streaming path). Building a fresh client per call made
# that essentially unhittable because every request opened a new connection. The same
# applies inside GeminiGateway's model-fallback loop, which no longer gets a fresh
# transport per attempt. Measured turn latency still improved sharply (mean 19.1s -> 13.4s,
# max 31.6s -> 14.8s over 9 live turns), so this is worth it — but a sporadic multi-second
# stall under the AIMS_CLASSIFY_BUDGET_S budget would point here first.
_CLIENT_CACHE: dict[tuple[Any, ...], Any] = {}
_CLIENT_CACHE_LOCK = threading.Lock()


def reset_genai_client_cache() -> None:
    """Drop every cached Gen AI client.

    Mainly for tests and long-running scripts: the SDK keeps a per-event-loop aiohttp
    session and auth lock on each client and never prunes them, so a client reused across
    many loops (``asyncio.run`` per iteration, or pytest's per-test loop under
    ``asyncio_mode = auto``) retains every loop it has seen. Production runs a single loop
    and does not need this.
    """
    with _CLIENT_CACHE_LOCK:
        _CLIENT_CACHE.clear()


class GeminiError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def extract_status_code(e: APIError) -> int | None:
    """Pull an integer HTTP status code from a google.genai.errors.APIError."""
    for attr in ("code", "status_code", "status"):
        raw = getattr(e, attr, None)
        if raw is not None:
            try:
                return int(raw)
            except (TypeError, ValueError):
                pass
    return None


def get_usage_count(usage: Any, *names: str) -> int | None:
    for name in names:
        value = getattr(usage, name, None) if usage else None
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None

class GeminiClient:
    def __init__(self, project: str, region: str, model_id: str):
        self.logger = logging.getLogger("app.gemini_client")
        self.project = project
        self.region = region
        self.model_id = model_id
        self._client: genai.Client | None = None

    def _get_client(self) -> genai.Client:
        """Return a Gen AI client for this project/location, shared across instances.

        The per-instance memo below only ever helped when the same GeminiClient was
        reused, which never happens: callers build a fresh one per LLM call. The shared
        cache is what actually avoids re-resolving credentials and re-establishing TLS on
        every request.
        """
        if self._client is not None:
            return self._client

        # Resolved at call time, never at import and never as a default argument, so that
        # monkeypatching app.gemini_client.genai.Client is effective.
        factory = genai.Client
        key = (self.project, self.region, factory)

        client = _CLIENT_CACHE.get(key)
        if client is None:
            with _CLIENT_CACHE_LOCK:
                client = _CLIENT_CACHE.get(key)
                if client is None:
                    client = factory(
                        vertexai=True,
                        project=self.project,
                        location=self.region,
                        http_options=types.HttpOptions(api_version="v1"),
                    )
                    _CLIENT_CACHE[key] = client

        self._client = client
        return client

    @staticmethod
    def _sanitize_response_schema(schema: dict[str, Any] | None) -> dict[str, Any] | None:
        """Return a copy of the schema with any $-prefixed meta-keys removed.
        Vertex AI responseSchema does not accept "$schema" or other $-draft keys.
        """
        if not schema:
            return None

        def _clean(obj):
            if isinstance(obj, dict):
                out: dict[str, Any] = {}
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
    def _normalize_thinking_level(value: str | None) -> types.ThinkingLevel | None:
        if not value:
            return None
        normalized = str(value).strip().upper()
        if not normalized:
            return None
        return types.ThinkingLevel(normalized)

    @staticmethod
    def merge_with_overlap(base: str, addition: str, max_overlap: int = 200) -> str:
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
        no_space_before = set(",.;:!?)]}’”")  # include curly quotes
        # Characters that typically do NOT get a space after them (opening brackets/quotes)
        no_space_after = set("([{‘“\"")

        need_space = False
        if left_ch and right_ch and (not left_ch.isspace()) and (not right_ch.isspace()):
            if left_ch in no_space_after or right_ch in no_space_before:
                need_space = False
            elif is_word(left_ch) and is_word(right_ch):
                # word-to-word boundary → insert a single space
                need_space = True
            elif left_ch in ".!?;:" and is_word(right_ch):
                # sentence boundary without a space
                need_space = True

        joined = base_s + " " + right_tail if need_space else base_s + right_tail

        return joined.strip()

    def _build_config(
        self,
        temperature: float,
        max_tokens: int,
        system_instruction: str | None,
        response_mime_type: str | None,
        response_schema: dict[str, Any] | None,
        thinking_budget: int | None = None,
        thinking_level: str | None = None,
    ) -> types.GenerateContentConfig:
        """Build a GenerateContentConfig for the Gen AI SDK."""
        _resp_mime = response_mime_type or "text/plain"
        _san_schema = (
            self._sanitize_response_schema(response_schema)
            if _resp_mime == "application/json"
            else None
        )

        config_kwargs: dict[str, Any] = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "response_mime_type": _resp_mime,
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if _san_schema:
            config_kwargs["response_schema"] = _san_schema
        if thinking_level:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=self._normalize_thinking_level(thinking_level)
            )
        elif thinking_budget is not None:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_budget=thinking_budget
            )

        return types.GenerateContentConfig(**config_kwargs)

    @staticmethod
    def _extract_response(response) -> tuple[str, dict[str, Any]]:
        """Extract text and metadata from a Gen AI SDK response.

        Filters out thinking parts (thought=True) so they don't contaminate
        the response text — they would corrupt JSON output and inflate token counts.
        """
        txt = ""
        thought_txt = ""
        parts_count = 0
        fr = None
        safety_summary: list[dict[str, Any]] = []

        candidates = getattr(response, "candidates", None) or []
        if candidates:
            candidate = candidates[0]
            content = getattr(candidate, "content", None)
            if content:
                parts = getattr(content, "parts", None) or []
                parts_count = len(parts)
                for part in parts:
                    t = getattr(part, "text", None)
                    if not t:
                        continue
                    if getattr(part, "thought", False):
                        thought_txt += t
                    else:
                        txt += t

            # Finish reason — may be an enum or a string
            raw_fr = getattr(candidate, "finish_reason", None)
            if raw_fr is not None:
                fr = raw_fr.value if hasattr(raw_fr, "value") else str(raw_fr)

            # Safety ratings
            ratings = getattr(candidate, "safety_ratings", None) or []
            safety_summary = [
                {
                    "category": str(getattr(s, "category", None)),
                    "prob": str(getattr(s, "probability", None)),
                    "blocked": getattr(s, "blocked", None),
                }
                for s in ratings
            ]

        # Usage metadata
        usage = getattr(response, "usage_metadata", None)
        meta: dict[str, Any] = {
            "finishReason": fr,
            "promptTokens": getattr(usage, "prompt_token_count", None) if usage else None,
            "candidatesTokens": getattr(usage, "candidates_token_count", None) if usage else None,
            "totalTokens": getattr(usage, "total_token_count", None) if usage else None,
            "thoughtsTokens": getattr(usage, "thoughts_token_count", None) if usage else None,
            "cachedContentTokens": get_usage_count(
                usage,
                "cached_content_token_count",
                "cachedContentTokenCount",
            ),
            "safety": safety_summary,
            "textLen": len(txt.strip()),
            "thoughtLen": len(thought_txt.strip()),
            "partsCount": parts_count,
        }

        return txt.strip(), meta

    async def generate_text_async(
        self,
        prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        system_instruction: str | None = None,
        response_mime_type: str | None = None,
        response_schema: dict[str, Any] | None = None,
        thinking_budget: int | None = None,
        thinking_level: str | None = None,
    ) -> str:
        """Native async generation using the Gen AI SDK.

        Returns text only (no metadata) — used by ClassifierService and other
        async callers that only need the response body.
        """
        try:
            client = self._get_client()
            config = self._build_config(
                temperature, max_tokens, system_instruction,
                response_mime_type, response_schema, thinking_budget, thinking_level,
            )

            response = await client.aio.models.generate_content(
                model=self.model_id,
                contents=prompt,
                config=config,
            )

            text, meta = self._extract_response(response)

            self.logger.info(json.dumps({
                "event": "genai_async_response",
                "modelId": self.model_id,
                "finishReason": meta.get("finishReason"),
                "textLen": meta.get("textLen"),
                "thoughtLen": meta.get("thoughtLen", 0),
                "candidatesTokens": meta.get("candidatesTokens"),
                "thoughtsTokens": meta.get("thoughtsTokens"),
                "cachedContentTokens": meta.get("cachedContentTokens"),
                "hasText": bool(text),
            }))

            if not text:
                raise GeminiError(
                    "No text candidates returned from model (possibly safety blocked)"
                )
            if (
                response_mime_type == "application/json"
                and meta.get("finishReason") in MAX_TOKEN_FINISH_REASONS
            ):
                self.logger.warning(json.dumps({
                    "event": "genai_async_json_max_tokens",
                    "modelId": self.model_id,
                    "textLen": meta.get("textLen"),
                    "candidatesTokens": meta.get("candidatesTokens"),
                    "thoughtsTokens": meta.get("thoughtsTokens"),
                }))
                raise GeminiError(
                    "Model stopped at max tokens before completing JSON response"
                )
            return text

        except GeminiError:
            raise
        except APIError as e:
            self.logger.exception("Gemini API error (async)")
            raise GeminiError(
                f"Gemini API error: {e}",
                status_code=extract_status_code(e),
            ) from e
        except Exception as e:
            self.logger.exception("Gen AI async unexpected error")
            raise GeminiError(str(e)) from e

    def generate_text(
        self,
        prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        system_instruction: str | None = None,
        response_mime_type: str | None = None,
        response_schema: dict[str, Any] | None = None,
        thinking_budget: int | None = None,
        thinking_level: str | None = None,
    ) -> tuple[str, dict]:
        """Generate text and return both the text and useful metadata for logging.

        If the model halts with finishReason == MAX_TOKENS and
        settings.AUTO_CONTINUE_ON_MAX_TOKENS is enabled, this method will automatically
        send up to settings.MAX_CONTINUATIONS "continue" turns and concatenate the
        results.

        The return shape is (text, meta_dict).
        """
        # Imported here rather than at module scope: app.config builds Settings() on
        # import, whose PROJECT_ID validator calls google.auth.default(). Importing
        # app.gemini_client must stay free of that network/credential side effect.
        from app.config import settings

        auto_continue = settings.AUTO_CONTINUE_ON_MAX_TOKENS
        max_continuations = settings.MAX_CONTINUATIONS
        continue_tail_chars = settings.CONTINUE_TAIL_CHARS
        continue_instruction_enabled = settings.CONTINUE_INSTRUCTION_ENABLED
        min_continue_growth = settings.MIN_CONTINUE_GROWTH

        try:
            client = self._get_client()
            config = self._build_config(
                temperature, max_tokens, system_instruction,
                response_mime_type, response_schema, thinking_budget, thinking_level,
            )

            self.logger.debug(
                "Calling generate_content(model=%s, prompt_len=%s, temperature=%s, max_tokens=%s)",
                self.model_id, len(prompt or ""), temperature, max_tokens,
            )

            # Use a chat session to preserve context across auto-continuations
            chat = client.chats.create(model=self.model_id, config=config)
            response = chat.send_message(prompt)

            text, meta_local = self._extract_response(response)

            # Diagnostic logging
            self.logger.info(json.dumps({
                "event": "genai_response",
                "modelId": self.model_id,
                "finishReason": meta_local.get("finishReason"),
                "textLen": meta_local.get("textLen"),
                "thoughtLen": meta_local.get("thoughtLen", 0),
                "partsCount": meta_local.get("partsCount", 0),
                "promptTokens": meta_local.get("promptTokens"),
                "candidatesTokens": meta_local.get("candidatesTokens"),
                "thoughtsTokens": meta_local.get("thoughtsTokens"),
                "cachedContentTokens": meta_local.get("cachedContentTokens"),
                "hasText": bool(text),
                "textPreview": (text[:120] + "...") if len(text) > 120 else text,
            }))

            # Auto-continue loop if hitting output cap
            continuation_count = 0
            no_progress_break = False
            while (
                auto_continue
                and meta_local.get("finishReason") in MAX_TOKEN_FINISH_REASONS
                and continuation_count < max_continuations
            ):
                continuation_count += 1
                tail = (text or "")[-continue_tail_chars:]
                if continue_instruction_enabled:
                    cont_prompt = (
                        "Please continue exactly where you left off without repeating previous text.\n"
                        "Tail context follows. Continue seamlessly after it:\n" + tail + "\n(End of tail)"
                    )
                else:
                    cont_prompt = "continue"

                self.logger.debug(
                    "Auto-continue #%s (tail_chars=%s, instr=%s)",
                    continuation_count, len(tail), continue_instruction_enabled,
                )
                next_resp = chat.send_message(cont_prompt)
                next_text, next_meta = self._extract_response(next_resp)

                prev_len = len(text)
                if next_text:
                    text = self.merge_with_overlap(text, next_text)

                meta_local.update({
                    "finishReason": next_meta.get("finishReason"),
                    "promptTokens": next_meta.get("promptTokens"),
                    "candidatesTokens": next_meta.get("candidatesTokens"),
                    "totalTokens": next_meta.get("totalTokens"),
                    "cachedContentTokens": next_meta.get("cachedContentTokens"),
                    "textLen": len(text),
                })

                if len(text) - prev_len < min_continue_growth:
                    no_progress_break = True
                    break
                if next_meta.get("finishReason") not in MAX_TOKEN_FINISH_REASONS:
                    break

            # Guard: raise if no text after all attempts
            if not text:
                self.logger.warning(json.dumps({
                    "event": "genai_empty_response",
                    "modelId": self.model_id,
                    "finishReason": meta_local.get("finishReason"),
                    "thoughtLen": meta_local.get("thoughtLen", 0),
                    "partsCount": meta_local.get("partsCount", 0),
                    "safety": meta_local.get("safety"),
                }))
                raise GeminiError(
                    f"No text in response (finishReason={meta_local.get('finishReason')}, "
                    f"thoughtLen={meta_local.get('thoughtLen', 0)}, "
                    f"parts={meta_local.get('partsCount', 0)})"
                )

            meta = {
                "model": self.model_id,
                **meta_local,
                "continuationCount": continuation_count,
                "transport": "genai_sdk",
                "noProgressBreak": no_progress_break,
                "continueTailChars": continue_tail_chars,
                "continuationInstructionEnabled": continue_instruction_enabled,
            }

            return text, meta

        except GeminiError:
            raise
        except APIError as e:
            self.logger.exception("Gemini API error")
            raise GeminiError(
                f"Gemini API error: {e}",
                status_code=extract_status_code(e),
            ) from e
        except Exception as e:
            self.logger.exception("Gen AI client unexpected error")
            raise GeminiError(str(e)) from e
