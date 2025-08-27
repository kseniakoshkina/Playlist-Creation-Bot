import os
import logging
import json
import datetime
import aiosqlite
import asyncio

import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity

from dotenv import load_dotenv

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    ConversationHandler,
    filters,
)
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup

import spotipy
from spotipy.oauth2 import SpotifyOAuth
import requests

LOGIN_BUTTON = "Login Spotify"
SET_LASTFM_BUTTON = "Specify nickname on Last.fm"
CREATE_PLAYLIST_BUTTON = "Create a playlist"

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIPY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI") 
LASTFM_API_KEY = os.getenv("LASTFM_API_KEY")
SCOPE = 'playlist-modify-public playlist-modify-private'

PROXY_URL = os.getenv("PROXY_URL")

PROXIES = {'http': PROXY_URL, 'https': PROXY_URL} if PROXY_URL else None


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)
DB_FILE = "users.db"

def get_main_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [LOGIN_BUTTON, SET_LASTFM_BUTTON],
        [CREATE_PLAYLIST_BUTTON]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def initialize_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                spotify_token_info TEXT,
                lastfm_username TEXT
            )
        """)
        await db.commit()

async def get_user(telegram_id):
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT spotify_token_info, lastfm_username FROM users WHERE telegram_id = ?", (telegram_id,))
        row = await cursor.fetchone()
        if row:
            return {
                "spotify_token_info": json.loads(row[0]) if row[0] else None,
                "lastfm_username": row[1]
            }
        return None

async def update_user(telegram_id, spotify_token_info=None, lastfm_username=None):
    async with aiosqlite.connect(DB_FILE) as db:
        user = await get_user(telegram_id)
        if user:
            if spotify_token_info:
                await db.execute("UPDATE users SET spotify_token_info = ? WHERE telegram_id = ?", (json.dumps(spotify_token_info), telegram_id))
            if lastfm_username:
                await db.execute("UPDATE users SET lastfm_username = ? WHERE telegram_id = ?", (lastfm_username, telegram_id))
        else:
            await db.execute("INSERT INTO users (telegram_id, spotify_token_info, lastfm_username) VALUES (?, ?, ?)",
                             (telegram_id, json.dumps(spotify_token_info) if spotify_token_info else None, lastfm_username))
        await db.commit()


# SPOTIFY and LAST.FM logic

def get_spotify_auth_manager(token_info=None):
    return SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope=SCOPE,
        # cache_handler=spotipy.MemoryCacheHandler(token_info=token_info) # Не используем кэш, т.к. храним в БД
    )
    
async def core_logic_create_playlist(telegram_id, start_date_str, end_date_str):
    user_data = await get_user(telegram_id)
    if not user_data or not user_data.get('spotify_token_info') or not user_data.get('lastfm_username'):
        return "Error: Spotify and Last.fm Data can't be found. Please, check /login and /set_lastfm."

    auth_manager = get_spotify_auth_manager()
    token_info = auth_manager.refresh_access_token(user_data['spotify_token_info']['refresh_token'])
    await update_user(telegram_id, spotify_token_info=token_info)

    sp = spotipy.Spotify(auth=token_info['access_token'], proxies=PROXIES, requests_timeout=60)
    
    try:
        start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        start_ts = int(start_date.timestamp())
        end_ts = int(end_date.timestamp())
    except ValueError:
        return "Error: Invalid Date Format."

    unique_tracks = set()
    page = 1
    total_pages = 1 
    while page <= total_pages:
        params = {
            'method': 'user.getrecenttracks',
            'user': user_data['lastfm_username'],
            'api_key': LASTFM_API_KEY,
            'format': 'json',
            'from': start_ts,
            'to': end_ts,
            'limit': 200,
            'page': page
        }
        try:
            response = requests.get("http://ws.audioscrobbler.com/2.0/", params=params, proxies=PROXIES, timeout=60)
            response.raise_for_status()
            data = response.json()
            if 'error' in data:
                return f"Ошибка от API Last.fm: {data['message']}"
            
            if page == 1:
                total_pages = int(data['recenttracks']['@attr']['totalPages'])
                if total_pages == 0:
                    return "No plays found on Last.fm for the specified period."

            tracks_on_page = data.get('recenttracks', {}).get('track', [])
            for track in tracks_on_page:
                unique_tracks.add((track['artist']['#text'], track['name']))
            
            page += 1
            await asyncio.sleep(0.2)
        except requests.RequestException as e:
            return f"Error while requesting Last.fm: {e}"

    if not unique_tracks:
        return "No unique tracks found to create a playlist."
    track_uris = []
    not_found = []
    for artist, name in unique_tracks:
        query = f"track:{name} artist:{artist}"
        results = sp.search(q=query, type='track', limit=1)
        if results['tracks']['items']:
            track_uris.append(results['tracks']['items'][0]['uri'])
        else:
            not_found.append(f"{artist} - {name}")
        await asyncio.sleep(0.1)
    
    if not track_uris:
        return "None of the tracks were found on Spotify."

    user_id = sp.current_user()['id']
    playlist_name = f"Last.fm: {start_date_str} to {end_date_str}"
    playlist = sp.user_playlist_create(user=user_id, name=playlist_name, public=False, description=f"All tracks from Last.fm for the specified period. Generated by bot.")
    
    for i in range(0, len(track_uris), 100):
        sp.playlist_add_items(playlist['id'], track_uris[i:i+100])

    result_message = (
        f"✅ Playlist '{playlist_name}' successfully created!\n"
        f"Link: {playlist['external_urls']['spotify']}.\n"
        f"Found and added: {len(track_uris)} tracks.\n"
        f"Not found on Spotify: {len(not_found)} tracks."
    )
    return result_message

(LOGIN_URL, LASTFM_NICK,
 CREATE_START_DATE, CREATE_END_DATE) = range(4)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user(user_id)

    line1 = escape_markdown("Hi! I'm a bot that creates Spotify playlists from your Last.fm history.", version=2)
    line_spotify_ok = escape_markdown("✅ You are logged in to Spotify.", version=2)
    line_spotify_fail = escape_markdown("❌ You are not logged into Spotify. Click the button '" + LOGIN_BUTTON + "'.", version=2)
    line_lastfm_fail = escape_markdown("❌ Your Last.fm nickname is not specified. Click the button '" + SET_LASTFM_BUTTON + "'.", version=2)
    
    text = f"{line1}\n\n"
    
    if user_data and user_data.get('spotify_token_info'):
        text += f"{line_spotify_ok}\n"
    else:
        text += f"{line_spotify_fail}\n"

    if user_data and user_data.get('lastfm_username'):
        escaped_username = escape_markdown(user_data['lastfm_username'], version=2)
        line_lastfm_ok = escape_markdown("✅ Your nickname Last.fm: ", version=2)
        line_lastfm_edit = escape_markdown(". To change, click '" + SET_LASTFM_BUTTON + "'.", version=2)
        text += f"{line_lastfm_ok}`{escaped_username}`{line_lastfm_edit}\n"
    else:
        text += f"{line_lastfm_fail}\n"

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=get_main_keyboard()
    )

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    auth_manager = get_spotify_auth_manager()
    auth_url = auth_manager.get_authorize_url(state=str(telegram_id))
    
    await update.message.reply_text(
        "To sign in to Spotify, please follow the personal link below and allow access.\n\n"
        "After that you will be redirected to the confirmation page and I will notify you of success here.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Log in with Spotify", url=auth_url)]
        ])
    )

async def set_lastfm_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Please, specify your nickname on Last.fm:")
    return LASTFM_NICK


async def lastfm_nick_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lastfm_username = update.message.text.strip()
    user_id = update.effective_user.id
    await update_user(user_id, lastfm_username=lastfm_username)
    
    escaped_username = escape_markdown(lastfm_username, version=2)
    
    part1 = escape_markdown("Your nickname on Last.fm is saved: ", version=2)
    part2 = escape_markdown(". Now you can create a playlist using /create_playlist.", version=2)
    text = f"{part1}`{escaped_username}`{part2}"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
    return ConversationHandler.END

async def create_playlist_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = await get_user(user_id)
    if not user_data or not user_data.get('spotify_token_info') or not user_data.get('lastfm_username'):
        await update.message.reply_text(
            "First you need to log in and specify a nickname.\n"
            "Use /login and /set_lastfm.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END
    
    await update.message.reply_text("Enter the start date in YYYY-MM-DD format:")
    return CREATE_START_DATE

async def create_start_date_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['start_date'] = update.message.text.strip()
    await update.message.reply_text("Great. Now enter the end date in YYYY-MM-DD format:")
    return CREATE_END_DATE

async def create_end_date_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['end_date'] = update.message.text.strip()
    start_date = context.user_data['start_date']
    end_date = context.user_data['end_date']
    
    await update.message.reply_text(
        f"Accepted! I'll start collecting tracks from {start_date} to {end_date}. "
        "This may take a few minutes. I will send you a message when everything is ready.",
        reply_markup=ReplyKeyboardRemove(),
    )
    
    chat_id = update.effective_message.chat_id
    context.application.create_task(run_playlist_creation(chat_id, context.bot, start_date, end_date))

    return ConversationHandler.END

async def run_playlist_creation(chat_id, bot, start_date, end_date):
    telegram_id = chat_id # В нашем случае chat_id = user_id
    result = await core_logic_create_playlist(telegram_id, start_date, end_date)
    await bot.send_message(chat_id=chat_id, text=result)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def main():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(initialize_db())

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    
    lastfm_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("set_lastfm", set_lastfm_start),
            MessageHandler(filters.TEXT & filters.Regex(f'^{SET_LASTFM_BUTTON}$'), set_lastfm_start)
        ],
        states={
            LASTFM_NICK: [MessageHandler(filters.TEXT & ~filters.COMMAND, lastfm_nick_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    create_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("create_playlist", create_playlist_start),
            MessageHandler(filters.TEXT & filters.Regex(f'^{CREATE_PLAYLIST_BUTTON}$'), create_playlist_start)
        ],
        states={
            CREATE_START_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_start_date_received)],
            CREATE_END_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_end_date_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(f'^{LOGIN_BUTTON}$'), login))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("login", login))
    application.add_handler(CommandHandler("compare_taste", compare_taste_start))
    
    application.add_handler(lastfm_conv_handler)
    application.add_handler(create_conv_handler) 
    application.run_polling()

if __name__ == "__main__":
    main()
