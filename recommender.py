"""Picks a song with a similar vibe to the one you're playing and finds it on Spotify."""

import random
import re
import unicodedata

MAX_SPOTIFY_LOOKUPS = 8


def clean_title(title):
    """'Song (feat. X) - Remastered 2011' -> 'Song', so Last.fm and Spotify agree on names."""
    t = re.sub(r"\s+-\s+.*$", "", title)
    t = re.sub(r"\s*[(\[][^)\]]*(feat\.|ft\.|with |remaster|version|edit|live)[^)\]]*[)\]]", "", t, flags=re.I)
    return t.strip() or title


def norm(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = re.sub(r"[^\w ]+", " ", s)
    s = re.sub(r"^the\s+", "", s.strip())
    return re.sub(r"\s+", " ", s).strip()


def song_key(title, artist):
    return f"{norm(artist)}|{norm(clean_title(title))}"


def _weighted_shuffle(items, weight):
    """Better matches tend to come first, but not always, so you don't get the same pick every time."""
    return sorted(items, key=lambda it: random.random() ** (1.0 / max(weight(it), 0.01)), reverse=True)


class Recommender:
    def __init__(self, spotify, lastfm, history, prefer_new_artists=True):
        self.sp = spotify
        self.fm = lastfm
        self.history = history  # has .seen(uri, key) -> bool
        self.prefer_new_artists = prefer_new_artists

    def pick(self, seed):
        """seed: a Spotify track dict. Returns a Spotify track dict, or None."""
        title = seed["name"]
        artist = seed["artists"][0]["name"]
        seed_artists = {norm(a["name"]) for a in seed["artists"]}

        similar = self.fm.similar_tracks(artist, clean_title(title))
        if not similar and clean_title(title) != title:
            similar = self.fm.similar_tracks(artist, title)
        similar = [c for c in similar if not self.history.seen(None, song_key(c[0], c[1]))]

        new_artist = [c for c in similar if norm(c[1]) not in seed_artists]
        via_artists = lambda: self._via_similar_artists(artist)  # only hit Last.fm if needed
        if self.prefer_new_artists:
            pools = [lambda: new_artist, via_artists, lambda: similar]
        else:
            pools = [lambda: similar, via_artists]

        tried = set()
        lookups = 0
        for pool in pools:
            for name, by in self._ranked(pool()):
                key = song_key(name, by)
                if key in tried:
                    continue
                tried.add(key)
                lookups += 1
                track = self.find_on_spotify(name, by)
                if track and track["uri"] != seed["uri"] and not self.history.seen(track["uri"], key):
                    return track
                if lookups >= MAX_SPOTIFY_LOOKUPS:
                    return None
        return None

    def _ranked(self, pool):
        if pool and len(pool[0]) == 3:  # (title, artist, match) from track.getSimilar
            top = sorted(pool, key=lambda c: c[2], reverse=True)[:20]
            return [(c[0], c[1]) for c in _weighted_shuffle(top, lambda c: c[2] + 0.05)]
        return pool

    def _via_similar_artists(self, artist):
        """Fallback when Last.fm has no similar-song data: popular songs by similar artists."""
        artists = _weighted_shuffle(self.fm.similar_artists(artist)[:15], lambda a: a[1] + 0.05)
        out = []
        for name, _ in artists[:3]:
            tracks = [t for t in self.fm.top_tracks(name) if not self.history.seen(None, song_key(*t))]
            random.shuffle(tracks)
            out.extend(tracks[:3])
        return out

    def find_on_spotify(self, title, artist):
        want_title, want_artist = norm(clean_title(title)), norm(artist)
        queries = [f'track:"{clean_title(title)}" artist:"{artist}"', f"{clean_title(title)} {artist}"]
        for q in queries:
            for t in self.sp.search_tracks(q, limit=5):
                if t.get("is_playable") is False:
                    continue
                if not any(norm(a["name"]) == want_artist for a in t["artists"]):
                    continue
                got_title = norm(clean_title(t["name"]))
                if got_title == want_title or (
                    got_title and want_title and (got_title.startswith(want_title) or want_title.startswith(got_title))
                ):
                    return t
        return None
