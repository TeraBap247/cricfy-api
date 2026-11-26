"""
CricFY API — Vercel Serverless (Python)
Deploy: vercel --prod
Env vars in Vercel dashboard:
  API_EXPIRES_AT  = 2025-12-31T23:59:59Z
  API_SECRET      = your_secret   (optional)
"""

from datetime import datetime, timezone
import json, os, time
import requests
from http.server import BaseHTTPRequestHandler

TOKEN_URL   = "https://edge.hamyra.xyz/auth/token"
MATCHES_URL = "https://edge.hamyra.xyz/cricfy/matches"

API_EXPIRES_AT = os.environ.get("API_EXPIRES_AT", "")
API_SECRET     = os.environ.get("API_SECRET", "")

BASE_HEADERS = {
    "Host": "edge.hamyra.xyz",
    "Connection": "keep-alive",
    "sec-ch-ua-platform": '"Android"',
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14; 22071219AI Build/UP1A.231005.007)"
        " AppleWebKit/537.36 (KHTML, like Gecko) Chrome/158.0.8127.46 Mobile"
        " Safari/537.36"
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

# vercel serverless = fresh process each call, so simple module-level cache
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
    if not t: raise ValueError("token not found")
    _cache["token"], _cache["at"] = t, now
    return t

def parse_kickoff(m):
    raw = m.get("kickoffAt") or m.get("startTime") or ""
    if not raw: return datetime.max.replace(tzinfo=timezone.utc)
    try: return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except: return datetime.max.replace(tzinfo=timezone.utc)

def format_matches(raw):
    if not isinstance(raw, dict): return raw
    lst = raw.get("matches", [])
    if not isinstance(lst, list): return raw
    live, up = [], []
    for m in lst:
        if not isinstance(m, dict): continue
        item = {**m, "status": "LIVE" if m.get("live") else "upcoming"}
        (live if m.get("live") else up).append(item)
    live.sort(key=parse_kickoff); up.sort(key=parse_kickoff)
    return {**raw, "matches": live + up}

def ms_human(ms):
    if ms <= 0: return "expired"
    s = ms // 1000; m = s // 60; h = m // 60; d = h // 24
    if d: return f"{d}d {h%24}h"
    if h: return f"{h}h {m%60}m"
    if m: return f"{m}m {s%60}s"
    return f"{s}s"

def respond(handler, body, status=200):
    data = json.dumps(body, ensure_ascii=False).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Authorization")
    handler.end_headers()
    handler.wfile.write(data)

class handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass  # silence vercel logs

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        qs   = dict(p.split("=", 1) for p in
                    (self.path.split("?")[1].split("&") if "?" in self.path else [])
                    if "=" in p)

        # expiry check
        if not API_EXPIRES_AT:
            return respond(self, {"error": "API_EXPIRES_AT not set"}, 500)
        try:
            expiry = datetime.fromisoformat(API_EXPIRES_AT.replace("Z", "+00:00"))
        except ValueError:
            return respond(self, {"error": "Bad API_EXPIRES_AT format"}, 500)

        now = datetime.now(timezone.utc)

        # /status — skip expiry block so client can still check
        if path in ("/status", "/api/status"):
            remaining = max(0, int((expiry - now).total_seconds() * 1000))
            return respond(self, {
                "active": now < expiry,
                "expires_at": API_EXPIRES_AT,
                "remaining_ms": remaining,
                "remaining_human": ms_human(remaining),
            })

        if now > expiry:
            return respond(self, {
                "error": "API_EXPIRED",
                "message": "This API has expired. Contact the provider.",
                "expired_at": API_EXPIRES_AT,
            }, 410)

        # auth
        if API_SECRET:
            auth = self.headers.get("Authorization", "")
            key  = auth[7:].strip() if auth.startswith("Bearer ") else qs.get("key", "")
            if key != API_SECRET:
                return respond(self, {"error": "UNAUTHORIZED"}, 401)

        # /matches or /
        if path in ("/", "/matches", "/api", "/api/matches", "/api/index"):
            try:
                token = get_token()
                r = requests.get(MATCHES_URL, headers={
                    **BASE_HEADERS,
                    "Pragma": "no-cache",
                    "Cache-Control": "no-cache",
                    "authorization": f"Bearer {token}",
                }, timeout=15)
                r.raise_for_status()
                return respond(self, format_matches(r.json()))
            except Exception as e:
                return respond(self, {"error": "UPSTREAM_ERROR", "detail": str(e)}, 502)

        respond(self, {"error": "NOT_FOUND"}, 404)

