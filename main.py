"""Vibe Queue: queues songs that match the vibe of what you're playing on Spotify,
then asks (with a little pop-up) whether to save each one to a playlist."""

import json
import signal
import threading
import time

import requests

import config
from lastfm import LastFM
from popup import NEW_PREFIX, PopupUI
from recommender import Recommender, song_key
from spotify_api import Spotify, SpotifyError

STATE_PATH = config.DATA_DIR / "state.json"
LOG_PATH = config.DATA_DIR / "vibe_queue.log"
HISTORY_LIMIT = 5000
PLAYLIST_CACHE_SECONDS = 600
_log_file = None


def log(msg):
    global _log_file
    line = f"{time.strftime('[%H:%M:%S]')} {msg}"
    print(line, flush=True)
    try:
        if _log_file is None:
            _log_file = open(LOG_PATH, "w", encoding="utf-8")  # fresh log each run
        _log_file.write(line + "\n")
        _log_file.flush()
    except OSError:
        pass


def describe(track):
    return f"{track['name']} - {', '.join(a['name'] for a in track['artists'])}"


class History:
    """Songs already played or suggested, so picks are actually new to you. Saved between runs."""

    def __init__(self, state):
        self.state = state
        state.setdefault("seen_uris", [])
        state.setdefault("seen_keys", [])
        self.uris = set(state["seen_uris"])
        self.keys = set(state["seen_keys"])

    def seen(self, uri, key):
        return (uri is not None and uri in self.uris) or (key is not None and key in self.keys)

    def add(self, track):
        uri, key = track["uri"], song_key(track["name"], track["artists"][0]["name"])
        if uri not in self.uris:
            self.uris.add(uri)
            self.state["seen_uris"] = (self.state["seen_uris"] + [uri])[-HISTORY_LIMIT:]
        if key not in self.keys:
            self.keys.add(key)
            self.state["seen_keys"] = (self.state["seen_keys"] + [key])[-HISTORY_LIMIT:]


class VibeQueue:
    def __init__(self, cfg):
        self.cfg = cfg
        self.state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
        self._state_lock = threading.Lock()
        self.history = History(self.state)
        self.sp = Spotify(cfg["spotify_client_id"], cfg["redirect_uri"])
        self.fm = LastFM(cfg["lastfm_api_key"])
        self.rec = Recommender(self.sp, self.fm, self.history, cfg["prefer_new_artists"])
        self.ui = None
        self.last_uri = None
        self.pending = self.state.get("pending")  # the pick we queued that hasn't played yet
        self.current = None  # (song, time it started, is it a vibe pick) for the song playing now
        self.songs_since_pick = cfg["suggest_every_n_songs"]  # so the first song gets a pick
        self._playlists = None
        self._playlists_at = 0

    def save_state(self):
        with self._state_lock:
            self.state["pending"] = self.pending  # so a restart doesn't forget a queued pick
            tmp = STATE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state))
            tmp.replace(STATE_PATH)

    def check_setup(self):
        self.sp.login()
        log(f"Spotify account: {self.sp.me().get('display_name') or self.sp.me()['id']}")
        try:
            self.fm.similar_artists("Radiohead", limit=1)
        except RuntimeError as e:
            raise SystemExit(f"Last.fm API key problem: {e}\nCheck lastfm_api_key in config.json.")

    # ---------- main loop (background thread) ----------

    def loop(self):
        while True:
            delay = self.cfg["poll_seconds"]
            try:
                self.tick()
            except SpotifyError as e:
                log(str(e))
                delay = 15
            except requests.RequestException as e:
                log(f"Network problem: {e}")
                delay = 15
            except RuntimeError as e:  # Last.fm errors
                log(str(e))
                delay = 15
            except Exception as e:
                log(f"Unexpected error: {e!r}")
                delay = 15
            time.sleep(delay)

    def tick(self):
        track = self.sp.currently_playing()
        if not track or track["uri"] == self.last_uri:
            return
        self.last_uri = track["uri"]
        log(f"Now playing: {describe(track)}")
        self.ui.post(lambda uri=track["uri"]: self.ui.close_unless(uri))

        every_song = self.cfg["ask_about"] == "every_song"
        is_pick = bool(self.pending and self._same_song(track, self.pending))
        song = self.pending if is_pick else track  # the pick dict remembers which song it was based on
        previous, self.current = self.current, (song, time.time(), is_pick)

        # The previous song just ended: ask about it now that you've heard it.
        if previous and self.cfg["popup_when"] == "finished":
            prev_song, started, prev_is_pick = previous
            if prev_is_pick or every_song:
                if time.time() - started >= self.cfg["min_listen_seconds"]:
                    self.show_popup(prev_song, just_played=True, is_pick=prev_is_pick)
                else:
                    log(f"  You skipped {prev_song['name']} quickly, so not asking about it.")

        if self.cfg["popup_when"] == "playing" and (is_pick or every_song):
            self.show_popup(song, is_pick=is_pick)

        if is_pick:
            self.pending = None
            if self.cfg["popup_when"] == "finished":
                log("  ^ This is the vibe pick. The pop-up will ask about it when the next song starts.")
            return

        self.history.add(track)
        self.songs_since_pick += 1
        if self.songs_since_pick < self.cfg["suggest_every_n_songs"]:
            return
        if self.pending:
            if self.pending["uri"] in self.sp.queue_uris():
                return  # the last pick is still waiting in the queue
            self.pending = None  # it got skipped or removed

        pick = self.rec.pick(track)
        if not pick:
            log("  Couldn't find a similar song for this one.")
            self.save_state()
            return
        self.sp.add_to_queue(pick["uri"])
        pick["vibe_seed"] = describe(track)
        self.pending = pick
        self.songs_since_pick = 0
        self.history.add(pick)
        self.save_state()
        log(f"  Queued next: {describe(pick)}")
        if self.cfg["popup_when"] == "finished":
            log("    (once it's played, a pop-up will ask if you want to keep it)")
        if self.cfg["popup_when"] == "queued":
            self.show_popup(pick)

    @staticmethod
    def _same_song(a, b):
        return a["uri"] == b["uri"] or (
            song_key(a["name"], a["artists"][0]["name"]) == song_key(b["name"], b["artists"][0]["name"])
        )

    # ---------- pop-up ----------

    def playlists(self):
        if self._playlists is None or time.time() - self._playlists_at > PLAYLIST_CACHE_SECONDS:
            self._playlists = self.sp.my_playlists()
            self._playlists_at = time.time()
        return self._playlists

    def show_popup(self, pick, just_played=False, is_pick=True):
        try:
            playlists = self.playlists()
        except (SpotifyError, requests.RequestException) as e:
            log(f"Couldn't load your playlists: {e}")
            playlists = []

        # Dropdown label -> playlist (None = create a new one). Duplicate names get a number.
        options = {}
        for p in playlists:
            label, n = p["name"], 2
            while label in options:
                label, n = f"{p['name']} ({n})", n + 1
            options[label] = p
        default_name = self.cfg["default_playlist_name"]
        if not any(p["name"] == default_name for p in playlists):
            options = {NEW_PREFIX + default_name: None, **options}
        last_id = self.state.get("last_playlist_id")
        selected = (
            next((label for label, p in options.items() if p and p["id"] == last_id), None)
            or next((label for label, p in options.items() if p and p["name"] == default_name), None)
            or next(iter(options))
        )

        image = None
        images = pick.get("album", {}).get("images") or []
        if images:
            try:
                url = images[-2]["url"] if len(images) > 1 else images[0]["url"]  # ~300px
                image = requests.get(url, timeout=10).content
            except requests.RequestException:
                pass

        data = {
            "uri": pick["uri"],
            "title": pick["name"],
            "artist": ", ".join(a["name"] for a in pick["artists"]),
            "reason": f"picked because you played {pick.get('vibe_seed', 'a similar song')}" if is_pick else "",
            "image": image,
            "header": "  ·  ".join((["VIBE PICK"] if is_pick else []) + (["JUST PLAYED"] if just_played else []))
                      or "NOW PLAYING",
        }
        on_add = lambda label: self.add_to_playlist(pick, options, label)
        self.ui.post(lambda: self.ui.show(data, list(options), selected, on_add, self.cfg["popup_timeout_seconds"]))

    def add_to_playlist(self, pick, options, label):
        """Called from the pop-up's background thread when you click Yes. Returns the message to show."""
        playlist = options.get(label)
        if playlist is None:
            playlist = self.sp.create_playlist(label[len(NEW_PREFIX):])
            log(f"Created playlist: {playlist['name']}")
            if self._playlists is not None:
                self._playlists.insert(0, playlist)
        elif self.sp.playlist_has(playlist["id"], pick["uri"]):
            log(f"{describe(pick)} is already in {playlist['name']}")
            return f"Already in {playlist['name']}"
        self.sp.add_to_playlist(playlist["id"], pick["uri"])
        self.state["last_playlist_id"] = playlist["id"]
        self.save_state()
        log(f"Added {describe(pick)} to {playlist['name']}")
        return f"✓  Added to {playlist['name']}"


def main():
    cfg = config.load()
    app = VibeQueue(cfg)
    app.check_setup()
    app.ui = PopupUI()
    signal.signal(signal.SIGINT, lambda *_: app.ui.post(app.ui.quit))
    threading.Thread(target=app.loop, daemon=True).start()
    log("Vibe Queue is running. Play something on Spotify. Press Ctrl+C (or close this window) to quit.")
    which = "every song you listen to" if cfg["ask_about"] == "every_song" else "only the vibe picks"
    when = {"finished": "when it ends", "playing": "when it starts", "queued": "as soon as a pick is queued"}
    log(f"Pop-ups: asking about {which}, {when.get(cfg['popup_when'], cfg['popup_when'])}.")
    app.ui.run()
    app.save_state()


if __name__ == "__main__":
    main()
