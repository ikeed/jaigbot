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
    print("DEBUG: No .env file found by python-dotenv")
    load_dotenv() # Fallback to standard loading

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
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
os.environ["BACKEND_URL"] = f"http://localhost:{port}/api/chat"

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

    # Prioritize Google, Facebook, Apple
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
                padding: 12px 20px;
                border-radius: 6px;
                margin-bottom: 10px;
                font-weight: 600;
                text-align: center;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                transition: transform 0.1s, box-shadow 0.1s;
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
            <form action="/chat">
                <button type="submit" id="continue-btn" style="
                    width: 100%;
                    background: #007bff;
                    color: white;
                    border: none;
                    padding: 12px 20px;
                    border-radius: 6px;
                    cursor: pointer;
                    font-size: 16px;
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
                .card {{ background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-align: center; width: 320px; }}
                button {{ color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; font-size: 16px; transition: opacity 0.2s; }}
                button:hover {{ opacity: 0.8; }}
                h1 {{ margin-bottom: 0.5rem; color: #333; }}
                p {{ color: #666; margin-bottom: 1.5rem; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>AIMSBot</h1>
                <p>Welcome! Please sign in.</p>
                <div style="margin-top: 1rem; display: flex; flex-direction: column;">
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

# Mount the Chainlit app under /chat
# Note: This will use chainlit_app.py as the target
mount_chainlit(app=app, target="chainlit_app.py", path="/chat")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(port))
