"""Loads config.json, and walks you through creating it on first run."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
DATA_DIR = ROOT / "data"

DEFAULTS = {
    "spotify_client_id": "",
    "lastfm_api_key": "",
    # Must match the Redirect URI in your Spotify app settings exactly.
    "redirect_uri": "http://127.0.0.1:8888/callback",
    # Queue a vibe pick after every N songs you play yourself (1 = after every song).
    "suggest_every_n_songs": 1,
    # Skip candidates by the same artist as the song you're on, so picks are actually new.
    "prefer_new_artists": True,
    # "finished" = pop-up asks about the pick when the next song starts (you've heard all of it).
    # "playing"  = pop-up appears as soon as the pick starts playing.
    # "queued"   = pop-up appears as soon as it's added to the queue.
    "popup_when": "finished",
    # "every_song" = the pop-up asks about every song you listen to.
    # "picks"      = only ask about the songs Vibe Queue found and queued.
    "ask_about": "every_song",
    # Don't ask about a song you skipped within this many seconds.
    "min_listen_seconds": 20,
    # Close an unanswered pop-up after this many seconds (0 = keep it until the song changes).
    "popup_timeout_seconds": 0,
    # Playlist to pre-select in the pop-up the first time (created if it doesn't exist).
    "default_playlist_name": "Vibe Finds",
    "poll_seconds": 3,
}


def load():
    if not CONFIG_PATH.exists():
        _first_run_setup()
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = {**DEFAULTS, **json.load(f)}
    missing = [k for k in ("spotify_client_id", "lastfm_api_key") if not cfg[k].strip()]
    if missing:
        raise SystemExit(f"config.json is missing: {', '.join(missing)}. See README.md.")
    DATA_DIR.mkdir(exist_ok=True)
    return cfg


def _first_run_setup():
    print("First-time setup (see README.md for where to get these).\n")
    client_id = input("Spotify Client ID: ").strip()
    lastfm_key = input("Last.fm API key:   ").strip()
    cfg = {**DEFAULTS, "spotify_client_id": client_id, "lastfm_api_key": lastfm_key}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    print(f"\nSaved to {CONFIG_PATH.name}. You can change other settings there later.\n")
