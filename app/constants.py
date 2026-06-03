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
APP_VERSION = "0.3.0"

# Mounting Paths
PATH_API = "/api"
PATH_CHAT = "/chat"
PATH_PUBLIC = "/public"

# UI Routes (relative to root or mount point as appropriate)
ROUTE_ROOT = "/"
ROUTE_LOGIN = "/login"
ROUTE_LOGOUT = "/logout"
ROUTE_DUPLICATE = "/duplicate"
ROUTE_CHAT_LOGIN = f"{PATH_CHAT}{ROUTE_LOGIN}"
ROUTE_CHAT_LOGIN_CALLBACK = f"{ROUTE_CHAT_LOGIN}/callback"
ROUTE_CHAT_LOGOUT = f"{PATH_CHAT}{ROUTE_LOGOUT}"
ROUTE_OAUTH_CALLBACK = "/auth/oauth/{provider}/callback"

# API Endpoints
ENDPOINT_HEALTHZ = "/healthz"
ENDPOINT_HISTORY = "/history"
ENDPOINT_CONFIG = "/config"
ENDPOINT_MODELCHECK = "/modelcheck"
ENDPOINT_DIAGNOSTICS = "/diagnostics"
ENDPOINT_MODELS = "/models"
ENDPOINT_SESSION = "/session"
ENDPOINT_DEREGISTER = f"{ENDPOINT_SESSION}/deregister"
ENDPOINT_SUMMARY = "/summary"
ENDPOINT_CHAT = "/chat"
ENDPOINT_REPORT = "/report"

# Templates
TEMPLATE_LOGIN = "login.html"
TEMPLATE_DUPLICATE = "duplicate.html"

# Defaults
DEFAULT_HOST = "localhost"
DEFAULT_CHAT_TARGET = "chainlit_app.py"
DEFAULT_REGION = "us-west4"
DEFAULT_MODEL_ID = "gemini-2.5-pro"
DEFAULT_MODEL_FLASH = "gemini-2.5-flash"
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

# AIMS State Keys
KEY_AIMS_STATE = "aims_state"
KEY_AIMS_METRICS = "aims"
KEY_FULL_HISTORY = "full_history"
KEY_COACH_POST = "coach_post"
KEY_GAME_OVER = "game_over"

# AIMS Phases
PHASE_PRE_ANNOUNCE = "PreAnnounce"
PHASE_INQUIRE_MIRROR = "InquireMirror"
PHASE_SECURE = "Secure"

# AIMS Steps
STEP_ANNOUNCE = "Announce"
STEP_INQUIRE = "Inquire"
STEP_MIRROR = "Mirror"
STEP_SECURE = "Secure"

# Compound AIMS Steps
STEP_ANNOUNCE_INQUIRE = "Announce+Inquire"
STEP_MIRROR_INQUIRE = "Mirror+Inquire"
STEP_MIRROR_SECURE = "Mirror+Secure"
STEP_SECURE_INQUIRE = "Secure+Inquire"
STEP_MIRROR_SECURE_INQUIRE = "Mirror+Secure+Inquire"

# Chainlit Session Keys
SESSION_USER = "user"
SESSION_ID = "session_id"
SESSION_HISTORY = "history"
SESSION_PERSONA = "persona"
SESSION_SCENARIO_CARD = "scenario_card"
SESSION_INTRO_SEEN = "intro_seen"
SESSION_CHARACTER = "character"
SESSION_SCENE = "scene"
SESSION_SESSION_ENDED = "session_ended"
SESSION_INTRO_PENDING = "aims_intro_pending"
SESSION_CONNECTION_ID = "connection_id"
SESSION_QUERY_PARAMS = "query_params"

# Window Message Types
MSG_INTRO_REQUIRED = "aims_intro_required"
MSG_DUPLICATE_TAB = "on_duplicate_tab"
MSG_LOGOUT = "on_logout"
MSG_REPORT_ISSUE = "report_issue"
MSG_NEW_CHAT = "new_chat"
MSG_INTRO_CONTINUE = "aims_intro_continue"
MSG_RESUME_THREAD = "aims_resume_thread"

# OAuth Providers
PROVIDER_GOOGLE = "google"
PROVIDER_FACEBOOK = "facebook"
PROVIDER_APPLE = "apple"
PROVIDER_GITHUB = "github"
PROVIDER_AZURE_AD = "azure-ad"
