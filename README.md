# Vibe Queue

By **Sean Huang** ([@seanhuangcode](https://github.com/seanhuangcode))

Vibe Queue watches what you're playing on Spotify and finds a song with a similar vibe. It adds
that song to your queue. When the song has played, a small pop-up asks if you want to save it to
one of your playlists.

- Similar songs come from Last.fm, favoring artists you're not already listening to
- It never suggests the same song twice
- The pop-up doesn't steal focus, and it skips songs you skipped within 20 seconds

## Setup

You'll need **Spotify Premium** and Python 3.

1. **Spotify app:** at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard), click **Create app**.
   Set the Redirect URI to `http://127.0.0.1:8888/callback`, tick **Web API**, and copy the **Client ID**.
2. **Last.fm key:** at [last.fm/api/account/create](https://www.last.fm/api/account/create), copy the **API key**.
3. **Run:** double-click `start.bat`. Paste both values when asked, then log in to Spotify in the browser.

Play music and leave the window open. Settings live in `config.json`, which is created on first run.
