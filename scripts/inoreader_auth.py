#!/usr/bin/env python3
"""Inoreader OAuth 2.0 helper.

Exchanges authorization code for access and refresh tokens, tests API access,
and saves the credentials into scratch/inoreader_credentials.json.

Usage:
    # Option 1: Listen for OAuth redirect on http://localhost:8080/callback
    python3 scripts/inoreader_auth.py --listen

    # Option 2: Pass authorization code directly
    python3 scripts/inoreader_auth.py --code <auth_code>

    # Option 3: Pass full redirect URL
    python3 scripts/inoreader_auth.py --url "http://localhost:8080/callback?code=..."

    # Option 4: Check existing token status
    python3 scripts/inoreader_auth.py --check
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import sys
import time
import urllib.parse
from typing import Optional

import requests

TOKEN_URL = "https://www.inoreader.com/oauth2/token"
USER_INFO_URL = "https://www.inoreader.com/reader/api/0/user-info"
CREDS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scratch", "inoreader_credentials.json")


def load_creds() -> dict:
    if not os.path.exists(CREDS_FILE):
        print(f"Credentials file not found at {CREDS_FILE}", file=sys.stderr)
        sys.exit(1)
    with open(CREDS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_creds(data: dict) -> None:
    with open(CREDS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Updated credentials saved to {CREDS_FILE}")


def exchange_code(app_id: str, app_key: str, redirect_uri: str, code: str) -> dict:
    payload = {
        "client_id": app_id,
        "client_secret": app_key,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.76 Safari/537.36",
    }
    r = requests.post(TOKEN_URL, data=payload, headers=headers, timeout=30)
    if r.status_code != 200:
        print(f"Token exchange failed: HTTP {r.status_code}\n{r.text}", file=sys.stderr)
        sys.exit(1)
    return r.json()


def check_token(access_token: str) -> bool:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.7922.76 Safari/537.36",
    }
    r = requests.get(USER_INFO_URL, headers=headers, timeout=30)
    if r.status_code == 200:
        data = r.json()
        print(f"Inoreader API check SUCCESS. User: {data.get('userName', 'Unknown')} (ID: {data.get('userId', 'Unknown')})")
        return True
    print(f"Inoreader API check FAILED: HTTP {r.status_code} - {r.text}", file=sys.stderr)
    return False


def start_listener(port: int = 8080) -> Optional[str]:
    captured_code = None

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal captured_code
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            if "code" in query:
                captured_code = query["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h1>Authorization successful!</h1><p>You can close this tab now.</p>")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"No code parameter found.")

        def log_message(self, format, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), CallbackHandler)
    print(f"Listening on http://127.0.0.1:{port}/callback for authorization code...")
    server.timeout = 120
    server.handle_request()
    return captured_code


def main():
    parser = argparse.ArgumentParser(description="Inoreader OAuth helper")
    parser.add_argument("--code", help="Authorization code")
    parser.add_argument("--url", help="Full redirect URL containing code")
    parser.add_argument("--listen", action="store_true", help="Start local listener on port 8080")
    parser.add_argument("--check", action="store_true", help="Check current token validity")
    args = parser.parse_args()

    creds = load_creds()

    if args.check:
        token = creds.get("access_token")
        if not token:
            print("No access token found in credentials file.", file=sys.stderr)
            sys.exit(1)
        ok = check_token(token)
        sys.exit(0 if ok else 1)

    code = args.code
    if args.url:
        parsed = urllib.parse.urlparse(args.url)
        query = urllib.parse.parse_qs(parsed.query)
        code = query.get("code", [None])[0]

    if not code and args.listen:
        code = start_listener(port=8080)

    if not code:
        print("No authorization code provided. Use --listen, --code, or --url.", file=sys.stderr)
        sys.exit(1)

    print(f"Exchanging authorization code...")
    token_data = exchange_code(
        app_id=creds["app_id"],
        app_key=creds["app_key"],
        redirect_uri=creds.get("redirect_uri", "http://localhost:8080/callback"),
        code=code,
    )

    creds.update(token_data)
    creds["saved_at"] = int(time.time())
    save_creds(creds)

    print("Verifying token with Inoreader user-info endpoint...")
    check_token(token_data["access_token"])


if __name__ == "__main__":
    main()
