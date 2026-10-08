"""Last.fm lookups for "sounds like this" data (Spotify removed its own recommendations API)."""

import requests

API = "https://ws.audioscrobbler.com/2.0/"


class LastFM:
    def __init__(self, api_key):
        self.api_key = api_key
        self.http = requests.Session()

    def _get(self, method, **params):
        r = self.http.get(API, timeout=15, params={
            "method": method, "api_key": self.api_key, "format": "json", "autocorrect": 1, **params,
        })
        try:
            data = r.json()
        except ValueError:
            raise RuntimeError(f"Last.fm sent an unexpected reply (HTTP {r.status_code}); will retry next song")
        if "error" in data:
            # Error 6 = "not found", which just means no data for this song/artist.
            if data["error"] == 6:
                return {}
            raise RuntimeError(f"Last.fm error {data['error']}: {data.get('message')}")
        return data

    def similar_tracks(self, artist, track, limit=50):
        """[(title, artist, match 0-1), ...] best match first."""
        data = self._get("track.getsimilar", artist=artist, track=track, limit=limit)
        tracks = data.get("similartracks", {}).get("track", [])
        return [(t["name"], t["artist"]["name"], float(t.get("match", 0))) for t in tracks]

    def similar_artists(self, artist, limit=20):
        data = self._get("artist.getsimilar", artist=artist, limit=limit)
        return [(a["name"], float(a.get("match", 0))) for a in data.get("similarartists", {}).get("artist", [])]

    def top_tracks(self, artist, limit=10):
        data = self._get("artist.gettoptracks", artist=artist, limit=limit)
        return [(t["name"], t["artist"]["name"]) for t in data.get("toptracks", {}).get("track", [])]
