#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List


TPDB_API_BASE = "https://api.theporndb.net"
TPDB_STASH_ENDPOINT = "https://theporndb.net/graphql"
STASH_BOXES_QUERY = """
query PerformerDbImagesConfig {
  configuration {
    general {
      stashBoxes {
        endpoint
        api_key
      }
    }
  }
}
"""


def read_input() -> Dict[str, Any]:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


def tpdb_exact_images(input_data: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    entry = args.get("entry") or {}
    stash_id = str(entry.get("stashId") or "").strip()
    source_name = str(entry.get("sourceName") or "theporndb").strip() or "theporndb"

    if not stash_id:
        return {"success": False, "images": [], "error": "theporndb: missing stash id"}

    api_key = find_tpdb_api_key(input_data)
    if not api_key:
        return {
            "success": False,
            "images": [],
            "error": f"theporndb: no api key configured for {TPDB_STASH_ENDPOINT}",
        }

    try:
        return {
            "success": True,
            "images": fetch_tpdb_performer_site_images(stash_id, source_name, api_key),
            "error": None,
        }
    except urllib.error.HTTPError as exc:
        return {"success": False, "images": [], "error": f"theporndb api: HTTP {exc.code} @ {exc.url}"}
    except urllib.error.URLError as exc:
        return {"success": False, "images": [], "error": f"theporndb api: {exc.reason}"}
    except Exception as exc:
        return {"success": False, "images": [], "error": f"theporndb api: {exc}"}


def find_tpdb_api_key(input_data: Dict[str, Any]) -> str:
    target_endpoint = normalize_url(TPDB_STASH_ENDPOINT).lower()

    for box in get_configured_stash_boxes(input_data):
        box_endpoint = normalize_url(box.get("endpoint"))
        if not box_endpoint:
            continue
        if box_endpoint.lower() == target_endpoint:
            return str(box.get("api_key") or "").strip()

    return ""


def get_configured_stash_boxes(input_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    connection = input_data.get("server_connection") or {}
    host = str(connection.get("Host") or "localhost").strip()
    if host == "0.0.0.0":
        host = "localhost"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    cookie = connection.get("SessionCookie") or {}
    cookie_name = str(cookie.get("Name") or cookie.get("name") or "").strip()
    cookie_value = str(cookie.get("Value") or cookie.get("value") or "").strip()
    if cookie_name and cookie_value:
        headers["Cookie"] = f"{cookie_name}={cookie_value}"

    try:
        result = request_json(
            f"{str(connection.get('Scheme') or 'http').strip()}://{host}:{connection.get('Port') or 9999}/graphql",
            "POST",
            headers,
            {"query": STASH_BOXES_QUERY, "variables": {}},
        )
    except Exception:
        return []

    if result.get("errors"):
        return []

    return (((result.get("data") or {}).get("configuration") or {}).get("general") or {}).get("stashBoxes") or []


def fetch_tpdb_performer_site_images(stash_id: str, source_name: str, api_key: str) -> List[Dict[str, Any]]:
    if not stash_id or not api_key:
        return []

    try:
        response = request_json(
            f"{TPDB_API_BASE}/performer-sites/{urllib.parse.quote(stash_id)}",
            "GET",
            {
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise

    image_url = str(((response.get("data") or {}).get("image")) or "").strip()
    if not image_url:
        return []

    return [{"url": image_url, "width": 0, "height": 0, "source": source_name}]


def request_json(url: str, method: str, headers: Dict[str, str], payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_url(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def main() -> None:
    input_data = read_input()
    args = input_data.get("args", {}) or {}
    mode = str(args.get("mode") or "").strip()

    output = (
        tpdb_exact_images(input_data, args)
        if mode == "tpdbExactImages"
        else {"success": False, "images": [], "error": f"unsupported mode: {mode or 'empty'}"}
    )
    print(json.dumps({"output": output}))


if __name__ == "__main__":
    main()
