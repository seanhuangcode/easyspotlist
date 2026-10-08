# Vibe Queue

By **Sean Huang** ([@seanhuangcode](https://github.com/seanhuangcode))

Vibe Queue watches what you're playing on Spotify and finds a song with a similar vibe. It adds
that song to your queue. After each song you listen to, including the ones it found, a small
pop-up asks if you want to save it to one of your playlists.

- Similar songs come from Last.fm, favoring artists you're not already listening to
- It never suggests the same song twice
- The pop-up doesn't steal focus, and it skips songs you skipped within 20 seconds
- It won't add a song twice to the same playlist
- To only be asked about the songs it found, set `"ask_about": "picks"` in `config.json`

## Setup

You'll need **Spotify Premium** and Python 3. It works on Windows and Mac.

1. **Spotify app:** at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard), click **Create app**.
   Set the Redirect URI to `http://127.0.0.1:8888/callback`, tick **Web API**, and copy the **Client ID**.
2. **Last.fm key:** at [last.fm/api/account/create](https://www.last.fm/api/account/create), copy the **API key**.
3. **Run:** paste both values when asked, then log in to Spotify in the browser.
   - **Windows:** double-click `start.bat`.
   - **Mac:** install Python from [python.org](https://www.python.org/downloads/macos/). Apple's built-in
     Python can't show the pop-up. Then open **Terminal**, type `bash ` (with a space), drag
     `start.command` into the window, and press Return. (Double-clicking `start.command` also works,
     but macOS often blocks scripts downloaded from the internet.)

Play music and leave the window open. Settings live in `config.json`, which is created on first run.
The pop-up shows up in the bottom-right corner on Windows, and the top-right corner on Mac.
