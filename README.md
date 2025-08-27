# Playlist Creation Bot
# Spotify × Last.fm Playlist Bot for Telegram

Create Spotify playlists from your Last.fm listening history directly in Telegram.

For Russian-speaking users: the bot is available at t.me/xenoonnshitbot.
DM @xenoonn to add you.

## What this bot does

- Lets you log into Spotify right from Telegram (OAuth).
- Links your Last.fm account (by username).
- Builds a Spotify playlist for a chosen period:
  - Fetches your Last.fm scrobbles between two dates.
  - Deduplicates tracks by artist + title.
  - Searches each track on Spotify and creates a private playlist named “Last.fm: YYYY-MM-DD to YYYY-MM-DD”.
  - Sends you the playlist link and a summary of added/not-found tracks.

Notes:
- The playlist is created as private by default.
- If a track can’t be found on Spotify, it’s reported in a short summary.

## Architecture

The project consists of two parts:

1) Telegram bot
- Handles commands: start, login, set Last.fm username, and create playlist.
- Stores user state and Spotify tokens in a local SQLite database (users.db).

2) Web server (Flask)
- Handles Spotify OAuth redirect at /callback.
- Exchanges the authorization code for tokens and stores them.
- Notifies the user in Telegram upon successful login.

## Try it (RU)
- Russian-speaking users can try the bot here: https://t.me/xenoonnshitbot

## Requirements

- Python 3.10+
- A Telegram bot token from BotFather
- A Spotify Developer application (Client ID/Secret + Redirect URI)
- A Last.fm API key
- A publicly reachable URL with HTTPS for the Spotify redirect (e.g., https://your.domain/callback)
- Optionally, an HTTP/HTTPS proxy (PROXY_URL) if you need to route traffic

## Environment variables

Create a .env file in the project root:

```
TELEGRAM_BOT_TOKEN=your_telegram_bot_token

SPOTIPY_CLIENT_ID=your_spotify_client_id
SPOTIPY_CLIENT_SECRET=your_spotify_client_secret
SPOTIPY_REDIRECT_URI=https://your.domain/callback

LASTFM_API_KEY=your_lastfm_api_key

# Optional proxy (applies to HTTP/HTTPS requests)
# PROXY_URL=http://user:pass@host:port
```

Important:
- SPOTIPY_REDIRECT_URI must exactly match the Redirect URI configured in your Spotify app settings.
- The repository includes a Flask route at /callback, so a typical redirect URI is https://your.domain/callback.

## Setup

1) Clone and install dependencies
```
git clone https://github.com/yourname/yourrepo.git
cd yourrepo

python -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

If you don’t have a requirements file, install the essentials:
```
pip install python-telegram-bot==20.* spotipy Flask aiosqlite python-dotenv requests
```

2) Configure Spotify app
- Go to https://developer.spotify.com/dashboard
- Create an app and add your Redirect URI: https://your.domain/callback
- Copy Client ID and Client Secret into .env

3) Configure Last.fm
- Create an API key at https://www.last.fm/api/account/create
- Put LASTFM_API_KEY into .env

4) Create Telegram bot
- Use @BotFather to create a bot, copy the token to TELEGRAM_BOT_TOKEN

5) Run the services
- Terminal 1: start the Flask web server (OAuth callback)
  ```
  python web.py
  ```
  By default it listens on port 5000. Put it behind a reverse proxy (Nginx/Caddy) with HTTPS on your domain, mapping /callback to this service.

- Terminal 2: start the Telegram bot
  ```
  python bot.py
  ```

Database
- The SQLite DB (users.db) is created automatically on first run and stores:
  - telegram_id
  - spotify_token_info (access/refresh tokens)
  - lastfm_username

## Usage

In Telegram:
1) /start
   - You’ll see whether Spotify login and Last.fm username are set.
2) Login to Spotify
   - Press the “Log in with Spotify” button, authorize, and wait for the success page.
   - The bot will notify you in Telegram when the login is successful.
3) /set_lastfm
   - Send your Last.fm username.
4) /create_playlist
   - Enter start and end dates in YYYY-MM-DD format.
   - Wait while the bot collects tracks and creates your Spotify playlist.
   - You’ll receive the playlist link and a summary.

Tips
- Use realistic date ranges (e.g., one month) to avoid API rate limits.
- Tracks are deduplicated by artist + title within the selected period.

## Minimal deployment notes

- You need a server (VPS) with a public domain and HTTPS so Spotify can redirect to your /callback endpoint.
- Open/forward port 443 (HTTPS) and proxy requests to your Flask app on port 5000.
- Keep your .env file private and never commit it.
- Use a process manager (systemd, Supervisor, pm2, tmux/screen) to run both the bot and the web server.

## Troubleshooting

- 400/invalid callback: Ensure SPOTIPY_REDIRECT_URI matches exactly the URI configured in Spotify Dashboard.
- No Telegram message after login: Check that the bot process is running and TELEGRAM_BOT_TOKEN is correct.
- Playlist is empty or few tracks: Confirm your Last.fm username is correct and that you have scrobbles in the selected date range.
- Proxy issues: If needed, set PROXY_URL and ensure the proxy allows Spotify/Last.fm traffic.

Feel free to open issues or PRs if you run into problems or want to contribute.
