import threading
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import requests
import base64
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# === Dummy web server per Render ===
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Spotify-Telegram attivo!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))  # Render fornisce la porta come env var
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    server.serve_forever()

# Avvia il server in un thread separato
threading.Thread(target=run_dummy_server, daemon=True).start()

# === Configurazione Bot Telegram + Spotify ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
TOKEN_GITHUB = os.getenv("TOKEN_GITHUB")
REPO_GITHUB = os.getenv("REPO_GITHUB")  # es: username/repo
FILE_PATH_GITHUB = os.getenv("FILE_PATH_GITHUB")
BRANCH_GITHUB = os.getenv("BRANCH_GITHUB")

client_credentials_manager = SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
)
sp = spotipy.Spotify(client_credentials_manager=client_credentials_manager)

# --- GitHub interaction functions ---
def github_get_file_sha():
    url = f"https://api.github.com/repos/{REPO_GITHUB}/contents/{FILE_PATH_GITHUB}"
    headers = {"Authorization": f"token {TOKEN_GITHUB}"}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return r.json().get("sha")
    return None

def github_commit_file(content_json):
    content_bytes = json.dumps(content_json, indent=2).encode("utf-8")
    content_b64 = base64.b64encode(content_bytes).decode("utf-8")
    sha = github_get_file_sha()

    url = f"https://api.github.com/repos/{REPO_GITHUB}/contents/{FILE_PATH_GITHUB}"
    headers = {
        "Authorization": f"token {TOKEN_GITHUB}",
        "Accept": "application/vnd.github+json"
    }

    payload = {
        "message": "Aggiornamento artisti preferiti",
        "content": content_b64,
        "branch": BRANCH_GITHUB
    }

    if sha:
        payload["sha"] = sha

    response = requests.put(url, headers=headers, json=payload)
    return response.status_code in [200, 201]

# --- Gestione file utenti ---
def load_user_artists():
    if not os.path.exists("user_artists.json"):
        return {}

    with open("user_artists.json", "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_user_artists(data):
    with open("user_artists.json", "w") as f:
        json.dump(data, f, indent=2)
    github_commit_file(data)








# --- Comandi bot ---
def start(update: Update, context: CallbackContext):
    msg = (
        "🎵 Benvenuto! Ecco cosa puoi fare:\n\n"
        "/search <brano> – Cerca una canzone su Spotify\n"
        "/setartist <nome artista 1> <nome artista 2> – Aggiungi artisti ai tuoi preferiti\n"
        "/listartists – Mostra i tuoi artisti preferiti\n"
        "/recommend – Ottieni consigli basati sui tuoi gusti\n\n"
        "Esempio: /setartist Dua Lipa Eminem\n"
        "Esempio: /search Blinding Lights"
    )
    update.message.reply_text(msg)

def search_song(update: Update, context: CallbackContext):
    query = " ".join(context.args)
    if not query:
        update.message.reply_text("❗ Usa /search seguito dal nome della canzone.")
        return
    results = sp.search(q=query, limit=1, type='track')
    if results['tracks']['items']:
        track = results['tracks']['items'][0]
        update.message.reply_text(
            f"🎶 {track['name']} - {track['artists'][0]['name']}\n{track['external_urls']['spotify']}"
        )
    else:
        update.message.reply_text("❌ Nessuna canzone trovata.")

def setartist(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    artist_name = " ".join(context.args).strip()

    if not artist_name:
        update.message.reply_text("Devi scrivere il nome di un artista, es: /setartist Vasco Rossi")
        return

    data = load_user_artists()
    user_artists = data.get(user_id, [])

    if artist_name not in user_artists:
        user_artists.append(artist_name)
        data[user_id] = user_artists
        save_user_artists(data)
        update.message.reply_text(f"Artista aggiunto: {artist_name}")
    else:
        update.message.reply_text(f"Hai già aggiunto {artist_name}")


def listartists(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    user_artists = load_user_artists()

    if user_id not in user_artists or not user_artists[user_id]:
        update.message.reply_text("📭 Non hai ancora artisti preferiti.")
        return

    artists = "\n".join(f"- {a}" for a in user_artists[user_id])
    update.message.reply_text(f"🎨 I tuoi artisti:\n{artists}")


def recommend(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    data = load_user_artists()
    artists = data.get(user_id, [])
    
    if not artists:
        update.message.reply_text("Non hai ancora aggiunto artisti preferiti. Usa /add_artist NomeArtista.")
        return
    
    try:
        # Cerca gli artisti su Spotify per ottenere generi
        genres = set()
        for artist_name in artists:
            result = sp.search(q=artist_name, type='artist', limit=1)
            if result['artists']['items']:
                genres.update(result['artists']['items'][0]['genres'])
        
        if not genres:
            update.message.reply_text("Non ho trovato generi per i tuoi artisti preferiti.")
            return

        seed_genres = list(genres)[:2]  # Max 5 generi
        recs = sp.recommendations(seed_genres=seed_genres, limit=5)
        
        messages = [f"🎧 {t['name']} di {t['artists'][0]['name']} - {t['external_urls']['spotify']}" for t in recs['tracks']]
        update.message.reply_text("\n".join(messages))

    except Exception as e:
        update.message.reply_text(f"Errore durante il recupero dei suggerimenti: {e}")



# --- Avvio bot ---
def main():
    updater = Updater(TELEGRAM_TOKEN)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("search", search_song))
    dp.add_handler(CommandHandler("setartist", setartist))
    dp.add_handler(CommandHandler("listartists", listartists))
    dp.add_handler(CommandHandler("recommend", recommend))
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
