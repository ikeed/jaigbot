import os
import uvicorn
from dotenv import load_dotenv

# Load environment variables early
print(f"DEBUG: Current working directory: {os.getcwd()}")
from dotenv import find_dotenv
env_path = find_dotenv()

if env_path:
    print(f"DEBUG: Found .env file at {env_path}")
    # Use override=True so that .env values take precedence over 
    # placeholder values in PyCharm run configurations.
    load_dotenv(env_path, override=True)
else:
    # Only print if we are not in a container (Cloud Run sets K_SERVICE)
    if not os.getenv("K_SERVICE"):
        print("DEBUG: No .env file found by python-dotenv")
    load_dotenv() # Fallback to standard loading

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from chainlit.utils import mount_chainlit
from chainlit.auth import clear_auth_cookie, get_token_from_cookies, decode_jwt

# Import the existing backend app
from app.main import app as backend_app
from app.chainlit_thread_state import clear_current_thread_id, get_current_thread_id

app = FastAPI()

from app.config import settings

# Include backend routes (healthz, chat, etc.)
# We mount the backend app under the same FastAPI instance
app.mount("/api", backend_app)
# Alternatively, we can just use the backend_app as the base and mount chainlit on it
# But to keep the custom landing page at root, we'll keep this structure 
# and update BACKEND_URL to point to /api/chat

# Update BACKEND_URL for this unified process
port = settings.PORT
backend_url = f"http://localhost:{port}/api/chat"
os.environ["BACKEND_URL"] = backend_url
settings.BACKEND_URL = backend_url

# Ensure Chainlit knows its public URL for OAuth redirects.
# If CHAINLIT_URL is not set, we default to localhost ONLY if NOT running in Cloud Run.
# In Cloud Run (detected by K_SERVICE), we avoid setting a default localhost URL 
# to prevent incorrect OAuth redirects.
if not os.getenv("CHAINLIT_URL"):
    if os.getenv("K_SERVICE"):
        # CRITICAL: In Cloud Run, we MUST have CHAINLIT_URL for OAuth to work.
        print("ERROR: K_SERVICE detected but CHAINLIT_URL is not set. SSO/OAuth will likely fail because it will default to an internal or incorrect URL.")
    else:
        # Default to localhost for local development as it's most common in OAuth configs
        os.environ["CHAINLIT_URL"] = f"http://localhost:{port}"
        print(f"DEBUG: Defaulting CHAINLIT_URL to {os.environ['CHAINLIT_URL']}")
else:
    # Ensure CHAINLIT_URL uses https if it's a cloud run URL but currently uses http
    url = os.environ["CHAINLIT_URL"]
    if ".a.run.app" in url and url.startswith("http://"):
        os.environ["CHAINLIT_URL"] = url.replace("http://", "https://")
        print(f"DEBUG: Forced CHAINLIT_URL to HTTPS: {os.environ['CHAINLIT_URL']}")

# Ensure CHAINLIT_AUTH_SECRET is set for cookie signing, especially for local OAuth state.
if not os.getenv("CHAINLIT_AUTH_SECRET"):
    os.environ["CHAINLIT_AUTH_SECRET"] = "local-dev-secret-12345"
    print("DEBUG: Using default CHAINLIT_AUTH_SECRET for local development.")


def _clear_persistent_session_id(user_identifier: str | None = None) -> None:
    clear_current_thread_id(user_identifier)
    try:
        filenames = ["session_id"]
        if user_identifier:
            safe_name = "".join([c if c.isalnum() else "_" for c in user_identifier])
            filenames.insert(0, f"session_id_{safe_name}")
        for filename in filenames:
            path = os.path.join(".chainlit", filename)
            if os.path.exists(path):
                os.remove(path)
    except Exception:
        pass


def _authenticated_user_identifier(request: Request) -> str | None:
    token = get_token_from_cookies(request.cookies)
    if not token:
        return None
    try:
        user = decode_jwt(token)
    except Exception:
        return None
    return user.identifier if user else None

# A simple custom login page that shows SSO buttons
@app.get("/", response_class=HTMLResponse)
async def custom_login_page(request: Request):
    # Debug logging to stdout (visible in PyCharm console)
    print("DEBUG: Checking for OAuth providers in environment...")
    
    # Detect enabled OAuth providers
    providers = []
    
    # Helper to check for a provider
    def is_valid_env_val(val: str | None) -> bool:
        if not val:
            return False
        placeholders = ["REPLACE_WITH", "your-auth-secret", "your-id"]
        return not any(p in val for p in placeholders)

    def add_if_exists(p_id, name, color):
        env_name = f"OAUTH_{p_id.upper().replace('-', '_')}_CLIENT_ID"
        val = os.getenv(env_name)
        if is_valid_env_val(val):
            providers.append({"id": p_id, "name": name, "color": color})
            print(f"DEBUG: Found provider {p_id} via {env_name}")

    add_if_exists("google", "Google", "#4285F4")
    add_if_exists("facebook", "Facebook", "#1877F2")
    add_if_exists("apple", "Apple", "#000000")
    add_if_exists("github", "GitHub", "#333")
    add_if_exists("azure-ad", "Microsoft", "#00a1f1")
    add_if_exists("keycloak", "Keycloak", "#f0ad4e")
    add_if_exists("okta", "Okta", "#007dc1")
    add_if_exists("auth0", "Auth0", "#eb5424")

    # Dynamic detection for anything else
    for k in os.environ.keys():
        if k.startswith("OAUTH_") and k.endswith("_CLIENT_ID"):
            val = os.environ.get(k)
            if is_valid_env_val(val):
                p_id = k[6:-10].lower().replace("_", "-")
                if p_id not in [p["id"] for p in providers]:
                    providers.append({"id": p_id, "name": p_id.capitalize(), "color": "#6c757d"})
                    print(f"DEBUG: Found dynamic provider {p_id} via {k}")

    buttons_html = ""
    for p in providers:
        # Style as a block link (button-like)
        buttons_html += f"""
            <a href="/chat/auth/oauth/{p['id']}" class="sso-button" style="
                display: block;
                text-decoration: none;
                background: {p['color']};
                color: white;
                padding: 16px 25px;
                border-radius: 8px;
                margin-bottom: 12px;
                font-size: 18px;
                font-weight: 600;
                text-align: center;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                transition: transform 0.1s, box-shadow 0.1s;
                width: 50%;
            " onmousedown="this.style.transform='translateY(1px)';this.style.boxShadow='none';" 
              onmouseup="this.style.transform='translateY(0)';this.style.boxShadow='0 2px 4px rgba(0,0,0,0.1)';"
              onmouseleave="this.style.transform='translateY(0)';this.style.boxShadow='0 2px 4px rgba(0,0,0,0.1)';"
            >Sign in with {p['name']}</a>
        """

    # If no providers, just show the continue button
    if not buttons_html:
        has_auth = is_valid_env_val(settings.CHAINLIT_AUTH_SECRET)
        warning = ""
        if has_auth:
            warning = f"""
                <div style="color: #a94442; background-color: #f2dede; border: 1px solid #ebccd1; padding: 10px; border-radius: 4px; margin-bottom: 20px; font-size: 14px; text-align: left;">
                    <strong>Configuration Warning:</strong><br>
                    SSO providers were not detected in the environment. 
                    Authentication secret is set, but no OAUTH_*_CLIENT_ID variables found.
                </div>
            """
        
        buttons_html = f"""
            {warning}
            <form action="/chat" style="width: 50%;">
                <button type="submit" id="continue-btn" style="
                    width: 100%;
                    background: #007bff;
                    color: white;
                    border: none;
                    padding: 16px 25px;
                    border-radius: 8px;
                    cursor: pointer;
                    font-size: 20px;
                    font-weight: 600;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                ">Continue to Chat</button>
            </form>
            <script>
                // Ensure button is enabled
                document.getElementById('continue-btn').disabled = false;
            </script>
        """
    
    html_content = f"""
    <html>
        <head>
            <title>AIMSBot Login</title>
            <style>
                body {{ font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; background: #f0f2f5; }}
                .card {{ background: white; padding: 4rem; border-radius: 12px; box-shadow: 0 8px 16px rgba(0,0,0,0.1); text-align: center; width: 640px; }}
                button {{ color: white; border: none; padding: 15px 30px; border-radius: 6px; cursor: pointer; font-size: 18px; transition: opacity 0.2s; }}
                button:hover {{ opacity: 0.8; }}
                h1 {{ margin-bottom: 1rem; color: #333; font-size: 2.5rem; }}
                p {{ color: #666; margin-bottom: 2rem; font-size: 1.2rem; }}
            </style>
            <script>
                window.addEventListener('message', (event) => {{
                    if (event.data === 'on_logout') {{
                        window.location.href = '/';
                    }} else if (event.data === 'on_duplicate_tab' || (event.data && event.data.type === 'on_duplicate_tab')) {{
                        window.location.href = '/duplicate';
                    }}
                }});
            </script>
        </head>
        <body>
            <div class="card">
                <img src="/public/aimsbot.png" alt="AIMSBot" style="width: 512px; height: 512px; margin: 0 auto 1rem; display: block;" />
                <!-- <h1>AIMSBot</h1> -->
                <p>Welcome! Please sign in.</p>
                <div style="margin-top: 1rem; display: flex; flex-direction: column; align-items: center;">
                    {buttons_html}
                    <p style="font-size: 11px; color: #999; margin-top: 10px;">
                        Secure SSO authentication enforced.
                    </p>
                </div>
            </div>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/duplicate", response_class=HTMLResponse)
async def duplicate_tab_page(request: Request):
    html_content = f"""
    <html>
        <head>
            <title>AIMSBot - Duplicate Tab</title>
            <style>
                body {{ font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; background: #f0f2f5; margin: 0; }}
                .card {{ background: white; padding: 3rem; border-radius: 12px; box-shadow: 0 8px 16px rgba(0,0,0,0.1); text-align: center; width: 500px; }}
                h2 {{ color: #856404; margin-top: 1rem; }}
                p {{ color: #666; line-height: 1.6; margin: 1.5rem 0; }}
                .btn {{ 
                    display: inline-block;
                    background: #007bff;
                    color: white;
                    text-decoration: none;
                    padding: 12px 24px;
                    border-radius: 6px;
                    font-weight: 600;
                    transition: background 0.2s;
                    cursor: pointer;
                    border: none;
                }}
                .btn:hover {{ background: #0056b3; }}
                .icon {{ font-size: 48px; margin-bottom: 1rem; }}
            </style>
        </head>
        <body>
            <div class="card">
                <img src="/public/aimsbot.png" alt="AIMSBot" style="width: 256px; height: 256px; margin: 0 auto 1rem; display: block;" />
                <div class="icon">⚠️</div>
                <h2>Duplicate Tab Detected</h2>
                <p>
                    It looks like you've got another tab open already. 
                    To ensure the accuracy of the simulation, only one active tab is allowed at a time.
                </p>
                <p style="font-size: 0.9em; color: #888;">
                    Please use your other open tab, or close it and click the button below to resume here.
                </p>
                <button onclick="window.location.href='/chat?force=true'" class="btn">Refresh This Tab</button>
            </div>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# Serve static assets (CSS, JS, avatars, images) at /public so references
# resolve correctly even though Chainlit is mounted at /chat.
if os.path.exists("public"):
    app.mount("/public", StaticFiles(directory="public"), name="public-static")
elif os.path.exists(".chainlit/public"):
    app.mount("/public", StaticFiles(directory=".chainlit/public"), name="public-static")

@app.middleware("http")
async def intercept_chainlit_login(request: Request, call_next):
    if request.url.path == "/chat/login":
        return RedirectResponse(url="/")
    return await call_next(request)

@app.get("/chat/login", response_class=RedirectResponse)
async def redirect_chainlit_login_to_root():
    return RedirectResponse(url="/")


@app.middleware("http")
async def redirect_chat_refresh_to_current_thread(request: Request, call_next):
    if (
        request.method == "GET"
        and request.url.path in {"/chat", "/chat/"}
        and request.query_params.get("aims_new") != "1"
    ):
        user_identifier = _authenticated_user_identifier(request)
        thread_id = get_current_thread_id(user_identifier)
        if thread_id:
            return RedirectResponse(url=f"/chat/thread/{thread_id}", status_code=307)
    return await call_next(request)


@app.api_route("/chat/logout", methods=["GET", "POST"], response_class=RedirectResponse)
async def unified_logout(request: Request):
    """
    Handle logout at the FastAPI layer so both GET and POST logout flows clear
    the auth cookie and return the browser to the SSO page.
    """
    response = RedirectResponse(url="/", status_code=303)
    clear_auth_cookie(request, response)

    token = get_token_from_cookies(request.cookies)
    if token:
        try:
            user = decode_jwt(token)
            if user and user.identifier:
                _clear_persistent_session_id(user.identifier)
        except Exception:
            pass

    return response

# Mount the Chainlit app under /chat
# Note: This will use chainlit_app.py as the target
mount_chainlit(app=app, target="chainlit_app.py", path="/chat")

if __name__ == "__main__":
    # Use localhost as default for local development to match typical OAuth client configs.
    # Cloud Run will typically provide HOST=0.0.0.0.
    host = os.getenv("HOST", "localhost")
    print(f"DEBUG: Starting uvicorn on {host}:{port}")
    print(f"DEBUG: CHAINLIT_URL is {os.environ.get('CHAINLIT_URL')}")
    print(f"DEBUG: BACKEND_URL is {os.environ.get('BACKEND_URL')}")
    uvicorn.run(app, host=host, port=int(port))
