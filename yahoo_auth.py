import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

CLIENT_ID    = "dj0yJmk9VDJSWHpmWmw5TWtUJmQ9WVdrOVpYVTVSelV5TW5ZbWNHbzlNQT09JnM9Y29uc3VtZXJzZWNyZXQmc3Y9MCZ4PWUx"
REDIRECT_URI = "http://localhost:8000/callback"
AUTH_URL     = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL    = "https://api.login.yahoo.com/oauth2/get_token"
PRIVATE_FILE = "secrets/private.json"

# ── PKCE ─────────────────────────────────────────────────────────────────────
code_verifier  = secrets.token_urlsafe(64)          # 86 URL-safe chars
code_challenge = base64.urlsafe_b64encode(
    hashlib.sha256(code_verifier.encode()).digest()
).rstrip(b"=").decode()                             # BASE64URL(SHA256(verifier))
state = secrets.token_urlsafe(16)

# ── Local callback server ─────────────────────────────────────────────────────
auth_code = None
done      = threading.Event()


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" in params:
            auth_code = params["code"][0]
            body = b"<h2>Authorization complete! You can close this tab.</h2>"
            self.send_response(200)
        else:
            error = params.get("error", ["unknown"])[0]
            body  = f"<h2>Error: {error}</h2>".encode()
            self.send_response(400)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)
        done.set()

    def log_message(self, format, *args):
        pass


server = HTTPServer(("localhost", 8000), CallbackHandler)
t = threading.Thread(target=server.handle_request, daemon=True)
t.start()

# ── Open browser ──────────────────────────────────────────────────────────────
auth_url = f"{AUTH_URL}?{urllib.parse.urlencode({
    'client_id':             CLIENT_ID,
    'redirect_uri':          REDIRECT_URI,
    'response_type':         'code',
    'code_challenge':        code_challenge,
    'code_challenge_method': 'S256',
    'state':                 state,
})}"

print("Opening browser for Yahoo PKCE authorization...")
print(f"\n{auth_url}\n")
webbrowser.open(auth_url)
print("Listening on http://localhost:8000/callback ...")

done.wait(timeout=120)

if not auth_code:
    print("ERROR: Timed out waiting for authorization code.")
    exit(1)

# ── Exchange code for token (no client secret — verifier proves identity) ─────
print("Code received — exchanging for token...")

resp = requests.post(
    TOKEN_URL,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    data={
        "grant_type":    "authorization_code",
        "code":          auth_code,
        "redirect_uri":  REDIRECT_URI,
        "client_id":     CLIENT_ID,
        "code_verifier": code_verifier,
    },
)

if not resp.ok:
    print(f"ERROR: Token exchange failed ({resp.status_code}):\n{resp.text}")
    exit(1)

token = resp.json()
print("Token received!")

private = {
    "consumer_key":  CLIENT_ID,
    "access_token":  token["access_token"],
    "refresh_token": token.get("refresh_token", ""),
    "token_type":    token.get("token_type", "bearer"),
    "token_time":    time.time(),
    "guid":          token.get("xoauth_yahoo_guid", ""),
}

with open(PRIVATE_FILE, "w") as f:
    json.dump(private, f, indent=4)

print(f"\nSaved to {PRIVATE_FILE} — run get_teams.py")
