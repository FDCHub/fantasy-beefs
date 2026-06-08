import base64
import json
import secrets
import time
import urllib.parse
import webbrowser

import requests

# ── Credentials ───────────────────────────────────────────────────────────────
with open("secrets/yahoo_oauth.json") as _f:
    _creds          = json.load(_f)
    CONSUMER_KEY    = _creds["consumer_key"]
    CONSUMER_SECRET = _creds["consumer_secret"]

AUTH_URL     = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL    = "https://api.login.yahoo.com/oauth2/get_token"
REDIRECT_URI = "https://localhost:8000/callback"
PRIVATE_FILE = "secrets/private.json"

# ── Step 1: open browser ──────────────────────────────────────────────────────
state    = secrets.token_urlsafe(16)
auth_url = f"{AUTH_URL}?{urllib.parse.urlencode({
    'client_id':     CONSUMER_KEY,
    'redirect_uri':  REDIRECT_URI,
    'response_type': 'code',
    'state':         state,
})}"

print("Opening browser for Yahoo authorization...")
webbrowser.open(auth_url)
print(f"If the browser did not open, visit:\n{auth_url}")

# ── Step 2: user pastes the redirected URL ────────────────────────────────────
print("\nAfter clicking Agree, Yahoo redirects to https://localhost:8000/callback")
print("The page will fail to load — that is expected.")
redirected = input("Paste the full URL from your browser address bar: ").strip()

params    = urllib.parse.parse_qs(urllib.parse.urlparse(redirected).query)
if params.get("state", [None])[0] != state:
    print("ERROR: state mismatch — possible CSRF. Aborting.")
    exit(1)

auth_code = params.get("code", [None])[0]
if not auth_code:
    print("ERROR: no 'code' parameter found in the pasted URL.")
    exit(1)

# ── Step 3: exchange code for token ───────────────────────────────────────────
_basic = base64.b64encode(f"{CONSUMER_KEY}:{CONSUMER_SECRET}".encode()).decode()

resp = requests.post(
    TOKEN_URL,
    headers={
        "Authorization": f"Basic {_basic}",
        "Content-Type":  "application/x-www-form-urlencoded",
    },
    data={
        "grant_type":   "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code":         auth_code,
    },
)

if not resp.ok:
    print(f"ERROR: Token exchange failed ({resp.status_code}):\n{resp.text}")
    exit(1)

token = resp.json()
print("Token received!")

# ── Step 4: persist ───────────────────────────────────────────────────────────
private = {
    "consumer_key":  CONSUMER_KEY,
    "access_token":  token["access_token"],
    "refresh_token": token.get("refresh_token", ""),
    "token_type":    token.get("token_type", "bearer"),
    "token_time":    time.time(),
    "guid":          token.get("xoauth_yahoo_guid", ""),
}

with open(PRIVATE_FILE, "w") as f:
    json.dump(private, f, indent=4)

print(f"\nSaved to {PRIVATE_FILE} — run get_teams.py")
