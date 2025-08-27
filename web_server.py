# web_server.py
import os
import json
import logging
import asyncio
import aiosqlite
from flask import Flask, request, redirect

import spotipy
from spotipy.oauth2 import SpotifyOAuth
import telegram
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIPY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")
SCOPE = 'playlist-modify-public playlist-modify-private'
DB_FILE = "users.db"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

async def update_user_token(telegram_id, spotify_token_info):
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT 1 FROM users WHERE telegram_id = ?", (telegram_id,))
        exists = await cursor.fetchone()
        if exists:
            await db.execute("UPDATE users SET spotify_token_info = ? WHERE telegram_id = ?", (json.dumps(spotify_token_info), telegram_id))
        else:
            await db.execute("INSERT INTO users (telegram_id, spotify_token_info) VALUES (?, ?)", (telegram_id, json.dumps(spotify_token_info)))
        await db.commit()

@app.route('/callback')
def callback():
    code = request.args.get('code')
    state = request.args.get('state') 
    error = request.args.get('error')

    if error or not state or not code:
        logger.error(f"Authorization error or missing parameters: error={error}, state={state}")
        return "An authorization error occurred. Please try again from Telegram.", 400

    try:
        telegram_id = int(state)
    except (ValueError, TypeError):
        logger.error(f"Invalid state, not a number: {state}")
        return "Error: Invalid session identifier.", 400

    auth_manager = SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope=SCOPE,
        state=state
    )
    
    try:
        token_info = auth_manager.get_access_token(code, as_dict=True, check_cache=False)
        
        asyncio.run(update_user_token(telegram_id, token_info))
        
        bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        message_text = ("✅ Great! You've successfully signed in to Spotify.\n\n"
                        "Now specify your nickname using the /set_lastfm command if you haven't done so already.")
        asyncio.run(bot.send_message(chat_id=telegram_id, text=message_text))

        return """
        <html>
            <head><title>Success!</title></head>
            <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
                <h1>Authorization successful!</h1>
                <p>Now you can return to Telegram and continue working with the bot.</p>
            </body>
        </html>
        """
    except Exception as e:
        logger.error(f"Failed to get token for user {telegram_id}: {e}")
        return "A critical error occurred while retrieving the token.", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
