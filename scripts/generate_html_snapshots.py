import os

from fastapi.testclient import TestClient

# Mock environment variables before importing app
os.environ["CHAINLIT_AUTH_SECRET"] = "test-secret"
os.environ["PORT"] = "8080"
os.environ["PROJECT_ID"] = "test-project"

from run_app import app

client = TestClient(app)

def save_snapshot(name, html):
    os.makedirs("tests/snapshots", exist_ok=True)
    with open(f"tests/snapshots/{name}.html", "w") as f:
        f.write(html)

def test_snapshots():
    # 1. No providers
    os.environ.pop("OAUTH_GOOGLE_CLIENT_ID", None)
    os.environ.pop("OAUTH_FACEBOOK_CLIENT_ID", None)
    os.environ.pop("OAUTH_APPLE_CLIENT_ID", None)
    
    response = client.get("/")
    save_snapshot("login_no_providers", response.text)
    
    # 2. Google provider
    os.environ["OAUTH_GOOGLE_CLIENT_ID"] = "google-id"
    response = client.get("/")
    save_snapshot("login_google", response.text)
    
    # 3. Multiple providers
    os.environ["OAUTH_FACEBOOK_CLIENT_ID"] = "facebook-id"
    os.environ["OAUTH_APPLE_CLIENT_ID"] = "apple-id"
    response = client.get("/")
    save_snapshot("login_multiple", response.text)
    
    # 4. Duplicate page
    response = client.get("/duplicate")
    save_snapshot("duplicate", response.text)

if __name__ == "__main__":
    test_snapshots()
