"""Minimal Spotify Web API client with PKCE login (no client secret needed)."""

import base64
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser

import requests

from config import DATA_DIR

API = "https://api.spotify.com/v1"
ACCOUNTS = "https://accounts.spotify.com"
TOKEN_PATH = DATA_DIR / "spotify_token.json"
SCOPES = " ".join([
    "user-read-currently-playing",
    "user-read-playback-state",
    "user-modify-playback-state",
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-public",
    "playlist-modify-private",
    "user-read-private",  # lets search use your country (market=from_token), so picks are playable for you
])


class SpotifyError(Exception):
    def __init__(self, status, message):
        super().__init__(f"Spotify {status}: {message}")
        self.status = status


class Spotify:
    def __init__(self, client_id, redirect_uri):
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.http = requests.Session()
        self._token = None
        self._lock = threading.Lock()
        self._me = None
        self._search_market = "from_token"

    # ---------- auth ----------

    def login(self):
        """Load a saved token, or open the browser to log in."""
        if TOKEN_PATH.exists():
            self._token = json.loads(TOKEN_PATH.read_text())
            if set(SCOPES.split()) - set(self._token.get("scope", "").split()):
                print("Vibe Queue needs an extra Spotify permission; logging in again.")
            else:
                try:
                    self._ensure_token()
                    return
                except (SpotifyError, KeyError):
                    print("Saved Spotify login expired; logging in again.")
        self._browser_login()

    def _browser_login(self):
        verifier = secrets.token_urlsafe(64)[:96]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "scope": SCOPES,
            "redirect_uri": self.redirect_uri,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "state": state,
        }
        code = _wait_for_redirect(self.redirect_uri, f"{ACCOUNTS}/authorize?{urllib.parse.urlencode(params)}", state)
        r = self.http.post(f"{ACCOUNTS}/api/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": verifier,
        })
        if r.status_code != 200:
            raise SystemExit(f"Spotify login failed: {r.text}")
        self._save_token(r.json())
        print("Logged in to Spotify.")

    def _save_token(self, tok):
        old = self._token or {}
        tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
        tok.setdefault("refresh_token", old.get("refresh_token"))
        tok.setdefault("scope", old.get("scope", ""))
        self._token = tok
        TOKEN_PATH.write_text(json.dumps(tok))

    def _ensure_token(self):
        with self._lock:
            if time.time() < self._token.get("expires_at", 0):
                return
            r = self.http.post(f"{ACCOUNTS}/api/token", data={
                "grant_type": "refresh_token",
                "refresh_token": self._token["refresh_token"],
                "client_id": self.client_id,
            })
            if r.status_code != 200:
                raise SpotifyError(r.status_code, f"token refresh failed: {r.text}")
            self._save_token(r.json())

    # ---------- requests ----------

    def _call(self, method, path, retry=True, **kwargs):
        try:
            self._ensure_token()
        except SpotifyError:
            # Refresh tokens expire after ~6 months; fall back to a fresh login.
            self._browser_login()
        headers = {"Authorization": f"Bearer {self._token['access_token']}"}
        r = self.http.request(method, f"{API}{path}", headers=headers, timeout=15, **kwargs)
        if r.status_code == 429 and retry:
            time.sleep(min(int(r.headers.get("Retry-After", "5")), 60))
            return self._call(method, path, retry=False, **kwargs)
        if r.status_code == 401 and retry:
            self._token["expires_at"] = 0
            return self._call(method, path, retry=False, **kwargs)
        if r.status_code >= 400:
            try:
                msg = r.json()["error"]["message"]
            except Exception:
                msg = r.text
            raise SpotifyError(r.status_code, msg)
        if r.status_code == 204 or not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return None  # e.g. add-to-queue answers 200 with a plain-text ID, not JSON

    # ---------- endpoints ----------

    def me(self):
        if self._me is None:
            self._me = self._call("GET", "/me")
        return self._me

    def currently_playing(self):
        """Returns the playing track dict, or None (nothing playing, ad, podcast...)."""
        data = self._call("GET", "/me/player/currently-playing", params={"market": "from_token"})
        if not data or data.get("currently_playing_type") != "track" or not data.get("item"):
            return None
        return data["item"]

    def queue_uris(self):
        data = self._call("GET", "/me/player/queue") or {}
        return [t["uri"] for t in data.get("queue", []) if t]

    def add_to_queue(self, uri):
        self._call("POST", "/me/player/queue", params={"uri": uri})

    def search_tracks(self, query, limit=5):
        params = {"q": query, "type": "track", "limit": limit}
        if self._search_market:
            try:
                data = self._call("GET", "/search", params={**params, "market": self._search_market})
                return data["tracks"]["items"] if data else []
            except SpotifyError as e:
                if e.status != 403:
                    raise
                self._search_market = None  # Spotify won't share your country; search without it
        data = self._call("GET", "/search", params=params)
        return data["tracks"]["items"] if data else []

    def my_playlists(self):
        """Playlists you can add songs to (ones you own or collaborate on)."""
        my_id = self.me()["id"]
        out, offset = [], 0
        while True:
            page = self._call("GET", "/me/playlists", params={"limit": 50, "offset": offset})
            for p in page["items"]:
                if p and (p["owner"]["id"] == my_id or p.get("collaborative")):
                    out.append({"id": p["id"], "name": p["name"]})
            if not page.get("next"):
                return out
            offset += 50

    def create_playlist(self, name):
        p = self._call("POST", "/me/playlists", json={
            "name": name, "public": False, "description": "Songs found by Vibe Queue",
        })
        return {"id": p["id"], "name": p["name"]}

    def playlist_has(self, playlist_id, uri, max_items=3000):
        offset = 0
        while offset < max_items:
            page = self._call("GET", f"/playlists/{playlist_id}/items", params={"limit": 50, "offset": offset})
            for entry in page.get("items", []):
                song = (entry or {}).get("item") or (entry or {}).get("track")  # "track" before Feb 2026
                if song and song.get("uri") == uri:
                    return True
            if not page.get("next"):
                return False
            offset += 50
        return False

    def add_to_playlist(self, playlist_id, uri):
        self._call("POST", f"/playlists/{playlist_id}/items", json={"uris": [uri]})


def _wait_for_redirect(redirect_uri, auth_url, expected_state):
    """Run a one-shot local web server to catch Spotify's login redirect."""
    parsed = urllib.parse.urlparse(redirect_uri)
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path != parsed.path:
                self.send_response(404)
                self.end_headers()
                return
            q = urllib.parse.parse_qs(url.query)
            result.update({k: v[0] for k, v in q.items()})
            ok = "code" in q and q.get("state", [""])[0] == expected_state
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Logged in! You can close this tab." if ok else f"Login failed: {result.get('error', 'unknown')}"
            self.wfile.write(f"<h2 style='font-family:sans-serif'>{msg}</h2>".encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer((parsed.hostname, parsed.port or 80), Handler)
    print("Opening your browser to log in to Spotify...")
    print(f"If it doesn't open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)
    while "code" not in result and "error" not in result:
        server.handle_request()
    server.server_close()
    if result.get("state") != expected_state or "code" not in result:
        raise SystemExit(f"Spotify login failed: {result.get('error', 'state mismatch')}")
    return result["code"]
