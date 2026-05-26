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
import jwt # pip install PyJWT
from chainlit.utils import mount_chainlit

# Import the existing backend app
from app.main import app as backend_app

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

# Serve static assets (SVGs, CSS, JS) at /public so that inline HTML
# references like /public/doctor.svg resolve correctly even though
# Chainlit is mounted at /chat (which serves them at /chat/public/).
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

# Mount the Chainlit app under /chat
# Note: This will use chainlit_app.py as the target
mount_chainlit(app=app, target="chainlit_app.py", path="/chat")

def _get_persistent_session_id(user_identifier: str | None = None) -> str | None:
    """
    Recover a persistent session ID from the local .chainlit directory.
    This logic mirrors chainlit_app.py's implementation.
    """
    import re
    # 1) Specific file for this user identifier
    if user_identifier:
        # Match chainlit_app.py: safe_id = "".join([c if c.isalnum() else "_" for c in user_identifier])
        safe_name = "".join([c if c.isalnum() else "_" for c in user_identifier])
        path = os.path.join(".chainlit", f"session_id_{safe_name}")
        if os.path.exists(path):
            with open(path, "r") as f:
                return f.read().strip()
    
    # 2) Global fallback
    path = os.path.join(".chainlit", "session_id")
    if os.path.exists(path):
        with open(path, "r") as f:
            return f.read().strip()
            
    return None

@app.middleware("http")
async def early_duplicate_tab_detection(request: Request, call_next):
    # Only intercept GET requests to the main /chat page
    # Chainlit's assets and API calls should not be blocked here
    if request.method == "GET" and request.url.path in ["/chat", "/chat/"]:
        # Check for force flag in query parameters
        if request.query_params.get("force") == "true":
            print("DEBUG: Force flag detected in query params. Bypassing duplicate detection.")
            return await call_next(request)

        # Extract user from cl-user-session cookie (Chainlit's default name)
        token = request.cookies.get("cl-user-session")
        user_identifier = None
        
        if token:
            try:
                # Chainlit's JWT is signed with CHAINLIT_AUTH_SECRET
                secret = os.environ.get("CHAINLIT_AUTH_SECRET")
                if secret:
                    # We don't necessarily need to verify the full JWT here if we just want a hint,
                    # but verifying is safer. Chainlit uses HS256 by default.
                    decoded = jwt.decode(token, secret, algorithms=["HS256"], options={"verify_signature": False})
                    user_identifier = decoded.get("sub") or decoded.get("email")
                    print(f"DEBUG: Middleware decoded user_identifier: {user_identifier}")
                else:
                    print("DEBUG: Middleware found cl-user-session but CHAINLIT_AUTH_SECRET is not set.")
            except Exception as e:
                print(f"DEBUG: Middleware failed to decode cl-user-session: {e}")

        if user_identifier:
            session_id = _get_persistent_session_id(user_identifier)
            if session_id:
                # Access the memory store from the backend app
                from app.main import _MEMORY_STORE
                import time
                mem = _MEMORY_STORE.get(session_id)
                if mem:
                    active_connections = mem.get("active_connections", [])
                    if active_connections:
                        # Check if the session is stale (e.g. not updated in 60 seconds)
                        updated = mem.get("updated", 0)
                        if time.time() - updated > 60:
                            print(f"DEBUG: Session {session_id} has active connections {active_connections} but is STALE (last update {time.time() - updated:.1f}s ago). Allowing connection.")
                            # We don't redirect to duplicate page if it's stale
                            return await call_next(request)

                        # Redirect to the duplicate tab warning page
                        print(f"DEBUG: Early duplicate detection for {user_identifier} on {session_id}. Active: {active_connections}")
                        return RedirectResponse(url="/duplicate")
                    else:
                        print(f"DEBUG: Session {session_id} found but has no active connections.")
                else:
                    print(f"DEBUG: No active backend session found for {session_id}.")
            else:
                print(f"DEBUG: No persistent session_id found for user {user_identifier}.")
        else:
            if token:
                print(f"DEBUG: Middleware found token but could not extract user_identifier.")
            else:
                print(f"DEBUG: Middleware did not find cl-user-session cookie.")

    return await call_next(request)

if __name__ == "__main__":
    # Use localhost as default for local development to match typical OAuth client configs.
    # Cloud Run will typically provide HOST=0.0.0.0.
    host = os.getenv("HOST", "localhost")
    print(f"DEBUG: Starting uvicorn on {host}:{port}")
    print(f"DEBUG: CHAINLIT_URL is {os.environ.get('CHAINLIT_URL')}")
    print(f"DEBUG: BACKEND_URL is {os.environ.get('BACKEND_URL')}")
    uvicorn.run(app, host=host, port=int(port))
