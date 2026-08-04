import gzip

from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.chainlit_thread_state import clear_current_thread_id, get_current_thread_id
from app.constants import PATH_CHAT, ROUTE_CHAT_LOGIN, ROUTE_CHAT_LOGIN_CALLBACK
from app.security.auth import authenticated_user_identifier


class AuthRedirectMiddleware(BaseHTTPMiddleware):
    """
    Middleware to intercept Chainlit's default login page and redirect to root,
    and to redirect chat refreshes to the current thread if one exists.
    """

    async def dispatch(self, request: Request, call_next):
        # 1. Intercept Chainlit login and redirect to our custom landing page
        if request.url.path == ROUTE_CHAT_LOGIN:
            return RedirectResponse(url="/")

        # 2. Redirect chat entry points to the current thread if it exists.
        # Chainlit's OAuth flow lands on /chat/login/callback and can initialize
        # a blank conversation client-side without requesting /chat first.
        chat_path = PATH_CHAT
        chat_slash_path = f"{PATH_CHAT}/"
        is_new_scenario_request = request.query_params.get("aims_new") == "1"
        if (
            request.method == "GET"
            and request.url.path in {chat_path, chat_slash_path}
            and is_new_scenario_request
        ):
            user_identifier = authenticated_user_identifier(request)
            clear_current_thread_id(user_identifier)

        if (
            request.method == "GET"
            and request.url.path
            in {
                chat_path,
                chat_slash_path,
                ROUTE_CHAT_LOGIN_CALLBACK,
            }
            and not is_new_scenario_request
        ):
            user_identifier = authenticated_user_identifier(request)
            thread_id = get_current_thread_id(user_identifier)
            if thread_id:
                target_url = f"{PATH_CHAT}/thread/{thread_id}"
                if (
                    request.url.path in {chat_path, chat_slash_path}
                    and request.query_params
                ):
                    target_url += f"?{request.query_params}"
                return RedirectResponse(url=target_url, status_code=307)

        return await call_next(request)


class JavaScriptRequiredMiddleware(BaseHTTPMiddleware):
    """
    Middleware to inject a <noscript> tag into HTML responses.
    This provides a rich fallback with a clickable help link for users with JS disabled.
    """

    @staticmethod
    def _response_with_body(response, body: bytes) -> Response:
        raw_headers = [
            (key, value)
            for key, value in response.raw_headers
            if key.lower() != b"content-length"
        ]
        raw_headers.append((b"content-length", str(len(body)).encode("latin-1")))
        updated_response = Response(
            content=body,
            status_code=response.status_code,
            media_type=response.media_type,
            background=response.background,
        )
        updated_response.raw_headers = raw_headers
        return updated_response

    @staticmethod
    async def _read_response_body(response: Response) -> bytes:
        body_iterator = getattr(response, "body_iterator", None)
        if body_iterator is None:
            return getattr(response, "body", b"")

        body = b""
        async for chunk in body_iterator:
            body += chunk
        return body

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Only process successful HTML GET requests for the chat app
        if (
            request.method == "GET"
            and response.status_code == 200
            and "text/html" in response.headers.get("content-type", "").lower()
            and request.url.path.startswith(PATH_CHAT)
        ):
            # Read the response body
            body = await self._read_response_body(response)

            # Handle compressed responses
            encoding = response.headers.get("content-encoding", "").lower()
            is_gzipped = "gzip" in encoding

            try:
                if is_gzipped:
                    decompressed_body = gzip.decompress(body)
                else:
                    decompressed_body = body
            except Exception:
                # If decompression fails, return original response
                return self._response_with_body(response, body)

            # Inject noscript before </body>
            # Matches the look and feel of the CSS fallback but adds a real link
            noscript_html = """
<noscript>
    <style>
        .aimsbot-noscript-overlay {
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(255, 255, 255, 0.01);
            display: flex; align-items: center; justify-content: center;
            z-index: 20000; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        .aimsbot-noscript-card {
            background: white; padding: 40px; border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.15);
            width: min(400px, 90vw); text-align: center; border: 1px solid rgba(102, 134, 180, 0.2);
        }
        .aimsbot-noscript-title { font-size: 22px; font-weight: 700; margin-bottom: 20px; color: #132238; }
        .aimsbot-noscript-body { font-size: 15px; line-height: 1.6; color: #43556f; margin-bottom: 25px; }
        .aimsbot-noscript-link { color: #007bff; text-decoration: underline; font-weight: 600; }
    </style>
    <div class="aimsbot-noscript-overlay">
        <div class="aimsbot-noscript-card">
            <div class="aimsbot-noscript-title">JavaScript Required</div>
            <div class="aimsbot-noscript-body">
                AIMSBot is a highly interactive simulation that requires JavaScript to function properly.
                Please enable JavaScript in your browser settings and reload the page to continue.
            </div>
            <a href="https://www.enable-javascript.com/" target="_blank" class="aimsbot-noscript-link">
                Help: enable-javascript.com
            </a>
        </div>
    </div>
</noscript>
"""
            new_body = decompressed_body.replace(b"</body>", noscript_html.encode("utf-8") + b"</body>")
            if new_body == decompressed_body:  # </body> not found
                new_body += noscript_html.encode("utf-8")

            # Re-compress if it was originally gzipped
            if is_gzipped:
                new_body = gzip.compress(new_body)
                # Keep content-encoding: gzip

            return self._response_with_body(response, new_body)

        return response
