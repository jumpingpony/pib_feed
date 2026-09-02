#!/usr/bin/env python3
"""Inoreader 1-to-1 subscription migration CLI with strict quota management."""
from __future__ import annotations

import argparse
import enum
import json
import os
import sys
import time
from typing import Optional

import requests

BASE_API = "https://www.inoreader.com/reader/api/0"
CREDS_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scratch", "inoreader_credentials.json"))
STATE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scratch", "inoreader_migration_state.json"))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.7922.76 Safari/537.36"
)

CIRCUIT_BREAKER_LIMIT = 180
REQUEST_DELAY_SECONDS = 2.0
HTTP_TIMEOUT_SECONDS = 30
MAX_BACKOFF_TRIES = 3


class RunMode(enum.Enum):
    DRY_RUN = 1
    EXECUTE = 2


def load_credentials() -> dict:
    """Load OAuth credentials from local scratch file."""
    if not os.path.exists(CREDS_FILE):
        print(f"Credentials not found at {CREDS_FILE}", file=sys.stderr)
        sys.exit(1)

    with open(CREDS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state() -> dict:
    """Load migration progress state from local file."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    return {
        "requests_made": 0,
        "subscribed": {},
        "configured": [],
        "unsubscribed": [],
    }


def save_state(state: dict) -> None:
    """Persist migration state after each completed step."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def api_request(
    method: str,
    endpoint: str,
    token: str,
    state: dict,
    mode: RunMode,
    params: Optional[dict] = None,
    data: Optional[dict] = None,
) -> tuple[int, dict | str]:
    """Execute API call with circuit breaker and exponential backoff."""
    if state["requests_made"] >= CIRCUIT_BREAKER_LIMIT:
        print(
            f"Circuit breaker reached: {state['requests_made']}/{CIRCUIT_BREAKER_LIMIT} requests. Halting.",
            file=sys.stderr,
        )
        sys.exit(1)

    url = f"{BASE_API}/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
    }

    if mode == RunMode.DRY_RUN and method != "GET":
        print(f"  [dry-run] {method} {url} params={params} data={data}")
        return 200, "OK"

    delay = 2.0
    for attempt in range(1, MAX_BACKOFF_TRIES + 1):
        try:
            r = requests.request(
                method,
                url,
                headers=headers,
                params=params,
                data=data,
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            state["requests_made"] += 1
            save_state(state)
            time.sleep(REQUEST_DELAY_SECONDS)

            if r.status_code == 200:
                try:
                    return 200, r.json()
                except ValueError:
                    return 200, r.text

            if r.status_code in (429, 503):
                print(f"  Rate limited / temporary server error (HTTP {r.status_code}). Backing off {delay}s...")
                time.sleep(delay)
                delay *= 2
                continue

            print(f"  API Error HTTP {r.status_code}: {r.text}", file=sys.stderr)
            return r.status_code, r.text

        except requests.RequestException as e:
            print(f"  Network error on attempt {attempt}: {e}", file=sys.stderr)
            time.sleep(delay)
            delay *= 2

    return 500, "Max backoff exceeded"


def fetch_subscriptions(token: str, state: dict, mode: RunMode) -> list[dict]:
    """Retrieve full list of active user subscriptions."""
    code, resp = api_request("GET", "subscription/list", token, state, mode, params={"output": "json"})
    if isinstance(resp, dict):
        return resp.get("subscriptions", [])

    return []


def plan_migration(subscriptions: list[dict]) -> tuple[list[dict], list[str]]:
    """Map legacy nappingcats subscriptions to new jumpingpony feeds."""
    to_migrate: list[dict] = []
    to_unsubscribe: list[str] = []

    # Map feeds
    has_noa = False
    for sub in subscriptions:
        url = sub.get("url", "")
        if "nappingcats.github.io/pib_feed" not in url:
            continue

        to_unsubscribe.append(sub["id"])
        key = url.split("pib_feed/")[1].split("/feed.xml")[0]
        folder = sub.get("categories", [{}])[0].get("label", "Uncategorized")
        title = sub.get("title", key)

        if key in ("parikrama", "bulletin_evening", "bulletin_midday", "bulletin_morning"):
            has_noa = True
            continue

        to_migrate.append({
            "key": key,
            "new_url": f"https://jumpingpony.github.io/pib_feed/{key}/feed.xml",
            "title": title,
            "folder": folder,
            "old_stream": sub["id"],
        })

    # Always ensure consolidated News On AIR feed is included
    to_migrate.append({
        "key": "newsonair",
        "new_url": "https://jumpingpony.github.io/pib_feed/newsonair/feed.xml",
        "title": "News On AIR - All India Radio",
        "folder": "Tier - 2 Op-Ed",
        "old_stream": None,
    })

    return to_migrate, to_unsubscribe


def run_migration(mode: RunMode) -> None:
    """Execute 1-to-1 subscription migration."""
    creds = load_credentials()
    token = creds["access_token"]
    state = load_state()

    print(f"Loaded migration state: {state['requests_made']} requests made previously")
    subs = fetch_subscriptions(token, state, mode)

    to_migrate, to_unsub = plan_migration(subs)
    print(f"Feeds to migrate: {len(to_migrate)}")
    print(f"Legacy subscriptions to unsubscribe: {len(to_unsub)}")

    # Step 1: QuickAdd new feeds
    print("\n--- Phase 1: QuickAdd New Feeds ---")
    for item in to_migrate:
        new_url = item["new_url"]
        if new_url in state["subscribed"]:
            continue

        print(f"Adding feed: {item['title']} ({new_url})...")
        code, resp = api_request("POST", "subscription/quickadd", token, state, mode, params={"quickadd": new_url})
        if code == 200 and mode != RunMode.DRY_RUN:
            stream_id = resp.get("streamId") if isinstance(resp, dict) else f"feed/{new_url}"
            state["subscribed"][new_url] = stream_id or f"feed/{new_url}"
            save_state(state)

    # Step 2: Edit title and assign folder
    print("\n--- Phase 2: Set Title and Folder ---")
    for item in to_migrate:
        new_url = item["new_url"]
        stream_id = state["subscribed"].get(new_url, f"feed/{new_url}")

        if stream_id in state["configured"]:
            continue

        print(f"Configuring feed: {item['title']} -> [{item['folder']}]...")
        payload = {
            "ac": "edit",
            "s": stream_id,
            "t": item["title"],
            "a": f"user/-/label/{item['folder']}",
        }
        code, resp = api_request("POST", "subscription/edit", token, state, mode, data=payload)
        if code == 200 and mode != RunMode.DRY_RUN:
            state["configured"].append(stream_id)
            save_state(state)

    # Step 3: Unsubscribe legacy subscriptions
    print("\n--- Phase 3: Unsubscribe Legacy Feeds ---")
    for old_stream in to_unsub:
        if old_stream in state["unsubscribed"]:
            continue

        print(f"Unsubscribing legacy stream: {old_stream}...")
        payload = {
            "ac": "unsubscribe",
            "s": old_stream,
        }
        code, resp = api_request("POST", "subscription/edit", token, state, mode, data=payload)
        if code == 200 and mode != RunMode.DRY_RUN:
            state["unsubscribed"].append(old_stream)
            save_state(state)

    print("\nMigration run complete!")
    print(f"Total API requests made: {state['requests_made']}/{CIRCUIT_BREAKER_LIMIT}")


def main():
    parser = argparse.ArgumentParser(description="Inoreader subscription migration CLI")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without calling write endpoints")
    args = parser.parse_args()

    mode = RunMode.DRY_RUN if args.dry_run else RunMode.EXECUTE
    run_migration(mode)


if __name__ == "__main__":
    main()
