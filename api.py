"""
CricFY Flask API
run: python api.py
endpoints:
  GET /matches
  GET /status
"""

import json
import time
import os
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request, Response

app = Flask(__name__)

TOKEN_URL   = "https://edge.hamyra.xyz/auth/token"
MATCHES_URL = "https://edge.hamyra.xyz/cricfy/matches"

API_SECRET  = os.environ.get("API_SECRET", "")  # optional

BASE_HEADERS = {
    "Host": "edge.hamyra.xyz",
    "Connection": "keep-alive",
    "sec-ch-ua-platform": '"Android"',
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14; 22071219AI Build/UP1A.231005.007)"
        " AppleWebKit/537.36 (KHTML, like Gecko) Chrome/158.0.8127.46 Mobile Safari/537.36"
    ),
    "Accept": "application/json",
    "sec-ch-ua": '"Chromium";v="158", "Not.A/Brand";v="24", "Android WebView";v="158"',
    "sec-ch-ua-mobile": "?1",
    "Origin": "https://www.hamyra.xyz",
    "X-Requested-With": "mark.via.gp",
    "Sec-Fetch-Site": "same-site",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Referer": "https://www.hamyra.xyz/",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
}

# ── token cache ───────────────────────────────────────────────────────────────
_cache = {"token": None, "at": 0}

def extract_token(p):
    if isinstance(p, str): return p.strip()
    if isinstance(p, dict):
        for k in ("token", "access_token", "accessToken", "jwt"):
            v = p.get(k)
            if isinstance(v, str) and v.strip(): return v.strip()
        if "data" in p: return extract_token(p["data"])
    return None

def get_token():
    now = time.time()
    if _cache["token"] and now - _cache["at"] < 300:
        return _cache["token"]
    r = requests.get(TOKEN_URL, headers=BASE_HEADERS, timeout=15)
    r.raise_for_status()
    t = extract_token(r.json())
    if not t: raise ValueError("token not found in response")
    _cache["token"], _cache["at"] = t, now
    return t

# ── match formatting ──────────────────────────────────────────────────────────
def parse_kickoff_time(match):
    raw_time = match.get("kickoffAt") or match.get("startTime") or ""
    if not raw_time:
        return datetime.max
    try:
        return datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
    except ValueError:
        return datetime.max

def format_matches(raw_data):
    if not isinstance(raw_data, dict):
        return raw_data

    raw_matches = raw_data.get("matches", [])
    if not isinstance(raw_matches, list):
        return raw_data

    live_matches = []
    upcoming_matches = []

    for match in raw_matches:
        if not isinstance(match, dict):
            continue

        item = {}
        for k, v in match.items():
            item[k] = v
            if k == "live":
                item["status"] = "LIVE" if v is True else "upcoming"

        if "live" not in item:
            item["live"] = False
            item["status"] = "upcoming"

        if match.get("live") is True:
            live_matches.append(item)
        else:
            upcoming_matches.append(item)

    live_matches.sort(key=parse_kickoff_time)
    upcoming_matches.sort(key=parse_kickoff_time)

    formatted = dict(raw_data)
    formatted["matches"] = live_matches + upcoming_matches
    return formatted

# ── helpers ───────────────────────────────────────────────────────────────────
def api_json(data, status=200):
    resp = Response(
        json.dumps(data, ensure_ascii=False),
        status=status,
        mimetype="application/json"
    )
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization"
    return resp

def check_auth():
    if not API_SECRET: return None
    auth = request.headers.get("Authorization", "")
    key  = auth[7:].strip() if auth.startswith("Bearer ") else request.args.get("key", "")
    if key != API_SECRET:
        return api_json({"error": "UNAUTHORIZED"}, 401)
    return None

# ── routes ────────────────────────────────────────────────────────────────────
@app.after_request
def cors(resp):
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return resp

@app.route("/", methods=["GET", "OPTIONS"])
@app.route("/matches", methods=["GET", "OPTIONS"])
def matches():
    if request.method == "OPTIONS": return "", 204
    err = check_auth()
    if err: return err
    try:
        token = get_token()
        r = requests.get(MATCHES_URL, headers={
            **BASE_HEADERS,
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "authorization": f"Bearer {token}",
        }, timeout=15)
        r.raise_for_status()
        return api_json(format_matches(r.json()))  # format_matches_response logic applied
    except Exception as e:
        return api_json({"error": "UPSTREAM_ERROR", "detail": str(e)}, 502)

@app.route("/status")
def status():
    return api_json({"active": True, "message": "API is running."})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[cricfy] running on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
