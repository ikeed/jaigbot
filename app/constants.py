"""
Centralized constants for the AIMSBot application.
"""

# Environment Variable Names
ENV_CHAINLIT_URL = "CHAINLIT_URL"
ENV_BACKEND_URL = "BACKEND_URL"
ENV_CHAINLIT_AUTH_SECRET = "CHAINLIT_AUTH_SECRET"
ENV_K_SERVICE = "K_SERVICE"
ENV_HOST = "HOST"
ENV_PORT = "PORT"

# App Metadata
APP_TITLE = "AIMSBot (Gemini Enterprise)"
APP_VERSION = "0.2.0"

# Mounting Paths
PATH_API = "/api"
PATH_CHAT = "/chat"
PATH_PUBLIC = "/public"

# UI Routes (relative to root or mount point as appropriate)
ROUTE_LOGIN = "/login"
ROUTE_LOGOUT = "/logout"
ROUTE_DUPLICATE = "/duplicate"
ROUTE_CHAT_LOGIN = f"{PATH_CHAT}{ROUTE_LOGIN}"
ROUTE_CHAT_LOGOUT = f"{PATH_CHAT}{ROUTE_LOGOUT}"

# Templates
TEMPLATE_LOGIN = "login.html"
TEMPLATE_DUPLICATE = "duplicate.html"

# Defaults
DEFAULT_HOST = "localhost"
DEFAULT_CHAT_TARGET = "chainlit_app.py"
DEFAULT_REGION = "us-west4"
DEFAULT_MODEL_ID = "gemini-2.5-pro"
DEFAULT_APP_ENV = "local"
DEFAULT_PORT = 8080
DEFAULT_MEMORY_TTL = 3600
DEFAULT_MAX_TURNS = 8
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 2048

# Static directories
DIR_PUBLIC = "public"
DIR_CHAINLIT_PUBLIC = ".chainlit/public"
DIR_CHAINLIT = ".chainlit"

# Filenames
FILE_SESSION_ID = "session_id"

# OAuth and Environment placeholders
OAUTH_PREFIX = "OAUTH_"
OAUTH_CLIENT_ID_SUFFIX = "_CLIENT_ID"
OAUTH_PLACEHOLDERS = ["REPLACE_WITH", "your-auth-secret", "your-id"]

# Redis / Memory Store Keys
PREFIX_AIMS = "aims"
PREFIX_SESSION = "session"
PREFIX_CHAINLIT = "chainlit"
KEY_THREAD_ID = "thread_id"
KEY_UPDATED = "updated"
PREFIX_CURRENT_THREAD = "current_thread"
PREFIX_THREAD = "thread"

# Chainlit Session Keys
SESSION_USER = "user"
SESSION_ID = "session_id"
SESSION_HISTORY = "history"
SESSION_PERSONA = "persona"
SESSION_SCENARIO_CARD = "scenario_card"
SESSION_INTRO_SEEN = "intro_seen"

# OAuth Providers
PROVIDER_GOOGLE = "google"
PROVIDER_FACEBOOK = "facebook"
PROVIDER_APPLE = "apple"
PROVIDER_GITHUB = "github"
PROVIDER_AZURE_AD = "azure-ad"
