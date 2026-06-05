import os
from typing import List, Dict, Any

from app.constants import OAUTH_PREFIX, OAUTH_CLIENT_ID_SUFFIX
from app.utils.env import is_valid_env_val


def get_enabled_oauth_providers() -> List[Dict[str, Any]]:
    """Detect enabled OAuth providers from environment variables."""
    providers = []
    
    # Well-known providers with specific colors
    well_known = [
        ("google", "Google", "#4285F4"),
        ("facebook", "Facebook", "#1877F2"),
        ("apple", "Apple", "#000000"),
        ("github", "GitHub", "#333"),
        ("azure-ad", "Microsoft", "#00a1f1"),
        ("keycloak", "Keycloak", "#f0ad4e"),
        ("okta", "Okta", "#007dc1"),
        ("auth0", "Auth0", "#eb5424"),
    ]

    for p_id, name, color in well_known:
        env_name = f"{OAUTH_PREFIX}{p_id.upper().replace('-', '_')}{OAUTH_CLIENT_ID_SUFFIX}"
        val = os.getenv(env_name)
        if is_valid_env_val(val):
            providers.append({"id": p_id, "name": name, "color": color})

    # Dynamic detection for any other OAUTH_*_CLIENT_ID
    for k in os.environ.keys():
        if k.startswith(OAUTH_PREFIX) and k.endswith(OAUTH_CLIENT_ID_SUFFIX):
            val = os.environ.get(k)
            if is_valid_env_val(val):
                # Extract provider ID: OAUTH_MY_PROV_CLIENT_ID -> my-prov
                prefix_len = len(OAUTH_PREFIX)
                suffix_len = len(OAUTH_CLIENT_ID_SUFFIX)
                p_id = k[prefix_len:-suffix_len].lower().replace("_", "-")
                if p_id not in [p["id"] for p in providers]:
                    providers.append({
                        "id": p_id, 
                        "name": p_id.capitalize(), 
                        "color": "#6c757d"
                    })

    return providers
