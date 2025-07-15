import threading
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import requests
import base64
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from dotenv import load_dotenv

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

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TASTEDIVE_API_KEY = os.getenv("TASTEDIVE_API_KEY")

# === File per salvare gusti utenti ===
DATA_FILE = "user_preferences.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# === Bot Commands ===
def start(update: Update, context: CallbackContext):
    msg = (
        "👋 Benvenuto!\n\n"
        "Usa questi comandi:\n"
        "/set <titolo/artista> – Imposta i tuoi gusti\n"
        "/recommend <tipo> – Ricevi consigli (music, movies, books)\n\n"
        "Esempi:\n"
        "/set Nirvana\n"
        "/recommend music\n"
        "/recommend movies"
    )
    update.message.reply_text(msg)

def set_preference(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    query = " ".join(context.args).strip()

    if not query:
        update.message.reply_text("❗ Usa: /set <titolo/artista/film>")
        return

    data = load_data()
    data[user_id] = query
    save_data(data)
    update.message.reply_text(f"✅ Preferenza salvata: *{query}*", parse_mode="Markdown")

def recommend(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    content_type = " ".join(context.args).strip().lower()

    if content_type not in ["music", "movies", "books"]:
        update.message.reply_text("❗ Tipo non valido. Usa: music, movies o books\nEsempio: /recommend music")
        return

    data = load_data()
    if user_id not in data:
        update.message.reply_text("❗ Non hai ancora impostato gusti. Usa /set prima.")
        return

    user_query = data[user_id]

    try:
        url = "https://tastedive.com/api/similar"
        params = {
            "q": user_query,
            "type": content_type,
            "limit": 5,
            "info": 1,
            "k": TASTEDIVE_API_KEY
        }

        response = requests.get(url, params=params)
        print("TasteDive URL:", response.url)  # Debug URL
        print("Risposta JSON:", response.json())  # Debug contenuto
        result = response.json()

        suggestions = result.get("Similar", {}).get("Results", [])
        if not suggestions:
            update.message.reply_text("⚠️ Nessun suggerimento trovato.")
            return

        message = f"🎯 *Suggerimenti per* _{user_query}_:\n\n"
        for item in suggestions:
            name = item.get("Name")
            teaser = item.get("wTeaser", "")
            link = item.get("wUrl", "")
            message += f"🎬 *{name}*\n{teaser}\n🔗 {link}\n\n"

        update.message.reply_text(message.strip(), parse_mode="Markdown", disable_web_page_preview=True)

    except Exception as e:
        update.message.reply_text(f"Errore: {e}")

# === Avvio Bot ===
def main():
    updater = Updater(TELEGRAM_TOKEN)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("set", set_preference))
    dp.add_handler(CommandHandler("recommend", recommend))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
