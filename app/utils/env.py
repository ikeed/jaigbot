import os

from dotenv import find_dotenv, load_dotenv

from app.constants import OAUTH_PLACEHOLDERS


def load_and_sanitize_env():
    """
    Load environment variables from .env and sanitize os.environ by stripping
    whitespace and quotes from keys and values.
    """
    env_path = find_dotenv()
    if env_path:
        load_dotenv(env_path, override=True)
    else:
        load_dotenv()

    for k, v in list(os.environ.items()):
        if not k or not isinstance(v, str):
            continue

        stripped_k = k.strip()
        stripped_v = v.strip()

        # Remove wrapping quotes
        if len(stripped_v) >= 2 and (
            (stripped_v[0] == '"' and stripped_v[-1] == '"')
            or (stripped_v[0] == "'" and stripped_v[-1] == "'")
        ):
            stripped_v = stripped_v[1:-1].strip()

        if stripped_k != k or stripped_v != v:
            if k != stripped_k:
                del os.environ[k]
            os.environ[stripped_k] = stripped_v

            # Log sanitization for sensitive keys (without revealing values)
            k_upper = stripped_k.upper()
            if any(x in k_upper for x in ["OAUTH", "SECRET", "KEY", "PASSWORD", "AUTH", "TOKEN"]):
                print(f"DEBUG: Sanitized environment variable: '{k}' -> '{stripped_k}'")

def is_valid_env_val(val: str | None) -> bool:
    """Check if an environment variable value is a real value and not a placeholder."""
    if not val:
        return False
    val = val.strip()
    if not val:
        return False
    return not any(p in val for p in OAUTH_PLACEHOLDERS)
