# AIMSBot SSO Setup Guide

This guide provides a step-by-step walkthrough for configuring Single Sign-On (SSO) for your AIMSBot application. We focus on non-technical, user-friendly providers: **Google**, **Facebook**, and **Apple**.

---

## General Prerequisites

1.  **Public URL**: OAuth providers require a public redirect URI. If testing locally, you can use `http://localhost:8080`.
2.  **`CHAINLIT_AUTH_SECRET`**: You must have an authentication secret set. 
    - Generate one: `chainlit create-secret`
    - Add it to your `.env` file: `CHAINLIT_AUTH_SECRET=your-generated-secret`
3.  **Unified Runner**: Always use `python run_app.py` or the **AIMSBot (Unified)** PyCharm configuration to see the custom landing page.

---

## 1. Google SSO Setup

Google is the most common provider and is natively supported by Chainlit.

### Step A: Create Credentials in Google Cloud Console
1.  Go to the [Google Cloud Console](https://console.cloud.google.com/).
2.  **Select a project**: Click the project dropdown (next to "Google Cloud") at the top left and select your project. **This is required to see the full menu.**
3.  **Find Credentials**:
    - Click the **Navigation Menu** (the three horizontal lines ☰ at the very top left).
    - Scroll down and click **APIs & Services**.
    - In the sidebar that appears, click **Credentials**.
    - *Tip: You can also just type "Credentials" into the search bar at the top of the page.*
4.  Click **Configure Consent Screen** (if you haven't yet). 
    - Choose **External**.
    - Fill in the App Name (e.g., "AIMSBot") and support email.
    - Add the `.../auth/userinfo.email` and `.../auth/userinfo.profile` scopes.
5.  Go back to **Credentials**, click **Create Credentials > OAuth client ID**.
6.  Select **Web application**.
7.  **Authorized Redirect URIs**: 
    - Add `http://localhost:8080/chat/auth/oauth/google/callback`
    - **Important**: Ensure the URL starts with `localhost`, not `0.0.0.0`.
    - (For production, add `https://your-domain.com/chat/auth/oauth/google/callback`)
8.  Click **Create** and copy your **Client ID** and **Client Secret**.

### Step B: Configure AIMSBot
Add the following to your `.env` file:
```env
OAUTH_GOOGLE_CLIENT_ID=your-google-client-id
OAUTH_GOOGLE_CLIENT_SECRET=your-google-client-secret
```

---

## 2. Facebook SSO Setup

Facebook is popular for non-technical users.

### Step A: Create Credentials in Meta for Developers
1.  Go to [Meta for Developers](https://developers.facebook.com/).
2.  Click **My Apps > Create App**.
3.  Select **Allow people to log in with their Facebook account**.
4.  Navigate to **App Settings > Basic** to find your **App ID** and **App Secret**.
5.  In the left sidebar, click **Add Product** and find **Facebook Login**. Click **Set Up**.
6.  Select **Web**.
7.  Navigate to **Facebook Login > Settings**.
8.  **Valid OAuth Redirect URIs**:
    - Add `http://localhost:8080/chat/auth/oauth/facebook/callback`
9.  Save Changes.

### Step B: Configure AIMSBot
Add the following to your `.env` file:
```env
OAUTH_FACEBOOK_CLIENT_ID=your-facebook-app-id
OAUTH_FACEBOOK_CLIENT_SECRET=your-facebook-app-secret
```

---

## 3. Apple SSO Setup

Apple Sign-In is highly valued for privacy.

### Step A: Create Credentials in Apple Developer Portal
1.  Go to the [Apple Developer Portal](https://developer.apple.com/).
2.  Navigate to **Certificates, Identifiers & Profiles**.
3.  **Identifiers**: Create a new **App ID** (if you don't have one) with the "Sign In with Apple" capability.
4.  **Identifiers**: Create a new **Services ID**.
    - Identifier: e.g., `com.yourname.aimsbot.sid`
    - Enable **Sign In with Apple** and click **Configure**.
    - **Primary App ID**: Select your App ID.
    - **Domains and Subdomains**: `localhost` (for local) or your production domain.
    - **Return URLs**: `http://localhost:8080/chat/auth/oauth/apple/callback`
5.  **Keys**: Create a new key.
    - Name: e.g., "AIMSBot Auth Key"
    - Enable **Sign In with Apple** and click **Configure**.
    - Select your App ID.
    - Download the `.p8` key file.

### Step B: Configure AIMSBot
Apple requires the Private Key content in the Secret field.
Add the following to your `.env` file:
```env
OAUTH_APPLE_CLIENT_ID=your-services-id-identifier
OAUTH_APPLE_CLIENT_SECRET="-----BEGIN PRIVATE KEY-----\nMII... (contents of your .p8 file) ...\n-----END PRIVATE KEY-----"
```

---

## How it works (The Technical Part)

When you run AIMSBot with these variables:
1.  `run_app.py` detects the variables and adds "Sign in with..." buttons to the landing page at `http://localhost:8080`.
2.  When a user clicks a button, they are sent to the provider's login screen.
3.  After successful login, the provider sends them back to AIMSBot with a token.
4.  `chainlit_app.py` receives the data in `oauth_callback` and maps the provider's unique fields (email, name, id) to a standard `AIMSBot User` object.
5.  The backend then uses this identity for all logging and session tracking.
