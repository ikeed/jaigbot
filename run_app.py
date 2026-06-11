from app.utils.env import load_and_sanitize_env

# 1. Load and sanitize environment variables at the absolute top!
load_and_sanitize_env()

import os

import uvicorn
from chainlit.utils import mount_chainlit
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.core.module_runtime import initialize_app_module_runtime
from app.constants import (
    DEFAULT_CHAT_TARGET,
    DEFAULT_HOST,
    DIR_CHAINLIT_PUBLIC,
    DIR_PUBLIC,
    ENV_BACKEND_URL,
    ENV_CHAINLIT_AUTH_SECRET,
    ENV_CHAINLIT_URL,
    ENV_HOST,
    ENV_K_SERVICE,
    PATH_API,
    PATH_CHAT,
    PATH_PUBLIC,
)
# Import the existing backend app and modular components
from app.main import app as backend_app
from app.middleware import AuthRedirectMiddleware
from app.routes.ui import router as ui_router
from app.security.oauth import is_valid_env_val

app = FastAPI()
initialize_app_module_runtime(app)

# 1. Update BACKEND_URL for this unified process
port = settings.PORT
backend_url = f"http://localhost:{port}{PATH_API}/chat"
os.environ[ENV_BACKEND_URL] = backend_url
settings.BACKEND_URL = backend_url

# 2. Ensure Chainlit knows its public URL for OAuth redirects.
if not os.getenv(ENV_CHAINLIT_URL):
    if os.getenv(ENV_K_SERVICE):
        print(f"ERROR: {ENV_K_SERVICE} detected but {ENV_CHAINLIT_URL} is not set. SSO/OAuth will likely fail.")
    else:
        # Default for local development
        os.environ[ENV_CHAINLIT_URL] = f"http://localhost:{port}"
        print(f"DEBUG: Defaulting {ENV_CHAINLIT_URL} to {os.environ[ENV_CHAINLIT_URL]}")
else:
    url = os.environ[ENV_CHAINLIT_URL]
    # In unified mode, Chainlit is mounted at /chat via mount_chainlit.
    # We strip the /chat suffix from CHAINLIT_URL because Chainlit internally 
    # appends the mount path to the base URL when generating redirect URIs.
    # Keeping it would result in double-prefixed URLs like /chat/chat/auth/...
    if url.endswith(PATH_CHAT):
        url = url[:-len(PATH_CHAT)].rstrip("/")
        os.environ[ENV_CHAINLIT_URL] = url
        print(f"DEBUG: Stripped {PATH_CHAT} from {ENV_CHAINLIT_URL}: {url}")
    elif url.endswith(f"{PATH_CHAT}/"):
        url = url[:-len(PATH_CHAT)-1].rstrip("/")
        os.environ[ENV_CHAINLIT_URL] = url
        print(f"DEBUG: Stripped {PATH_CHAT}/ from {ENV_CHAINLIT_URL}: {url}")

    # noinspection HttpUrlsUsage
    if ".a.run.app" in url and url.startswith("http://"):
        # noinspection HttpUrlsUsage
        os.environ[ENV_CHAINLIT_URL] = url.replace("http://", "https://")
        print(f"DEBUG: Forced {ENV_CHAINLIT_URL} to HTTPS: {os.environ[ENV_CHAINLIT_URL]}")

# 3. Warn if CHAINLIT_AUTH_SECRET is missing.
if not is_valid_env_val(os.getenv(ENV_CHAINLIT_AUTH_SECRET)):
    print(f"WARNING: {ENV_CHAINLIT_AUTH_SECRET} is not set or is a placeholder. Chainlit may fail or run without authentication.")

# 4. Add Middlewares
app.add_middleware(AuthRedirectMiddleware)

# 5. Serve static assets (CSS, JS, avatars, images)
if os.path.exists(DIR_PUBLIC):
    app.mount(PATH_PUBLIC, StaticFiles(directory=DIR_PUBLIC), name="public-static")
elif os.path.exists(DIR_CHAINLIT_PUBLIC):
    app.mount(PATH_PUBLIC, StaticFiles(directory=DIR_CHAINLIT_PUBLIC), name="public-static")

# 6. Mount Sub-apps and Routes
app.mount(PATH_API, backend_app)
app.include_router(ui_router)

# 7. Mount the Chainlit app under /chat
mount_chainlit(app=app, target=DEFAULT_CHAT_TARGET, path=PATH_CHAT)

if __name__ == "__main__":
    host = os.getenv(ENV_HOST, DEFAULT_HOST)
    print(f"DEBUG: Starting uvicorn on {host}:{port}")
    print(f"DEBUG: {ENV_CHAINLIT_URL} is {os.environ.get(ENV_CHAINLIT_URL)}")
    print(f"DEBUG: {ENV_BACKEND_URL} is {os.environ.get(ENV_BACKEND_URL)}")
    uvicorn.run(app, host=host, port=int(port))
