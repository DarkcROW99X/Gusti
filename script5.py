import threading
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
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
print("TasteDive API key:", TASTEDIVE_API_KEY)


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


def escape_markdown_v2(text: str) -> str:
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', text)


# === Bot Commands ===
def start(update: Update, context: CallbackContext):
    msg = (
        "👋 Benvenuto!\n\n"
        "Usa questi comandi:\n"
        "/set <titolo/artista> – Imposta i tuoi gusti\n"
        "/list  vedi i tuoi artisti preferiti \n"
        "/remove <titolo/artista> rimuovi 1 preferenza\n"
         "/clear pulisci tutte le preferenze \n"
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
    if user_id not in data:
        data[user_id] = []

    if query in data[user_id]:
        update.message.reply_text("⚠️ Preferenza già presente.")
        return

    data[user_id].append(query)
    save_data(data)
    update.message.reply_text(
        f"✅ Preferenza aggiunta: *{escape_markdown_v2(query)}*",
        parse_mode="MarkdownV2"
    )


def clear_preferences(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("✅ Conferma eliminazione", callback_data="confirm_clear")],
        [InlineKeyboardButton("❌ Annulla", callback_data="cancel_clear")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("⚠️ Sei sicuro di voler eliminare **tutte** le preferenze?", 
                              reply_markup=reply_markup, parse_mode="MarkdownV2")






def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = str(query.from_user.id)
    query.answer()

    data = load_data()

    if query.data == "confirm_clear":
        if user_id in data:
            data[user_id] = []
            save_data(data)
            query.edit_message_text("🗑️ Tutte le preferenze sono state eliminate.")
        else:
            query.edit_message_text("ℹ️ Nessuna preferenza da eliminare.")
    elif query.data == "cancel_clear":
        query.edit_message_text("❎ Operazione annullata.")



def list_preferences(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    data = load_data()

    if user_id not in data or not data[user_id]:
        update.message.reply_text("📭 Non hai ancora aggiunto preferenze. Usa /set per iniziare.")
        return

    prefs = data[user_id]
    message = "🎨 *Le tue preferenze attuali:*\n\n"
    message += "\n".join(f"- {escape_markdown_v2(p)}" for p in prefs)

    try:
        update.message.reply_text(message, parse_mode="MarkdownV2")
    except Exception as e:
        update.message.reply_text(f"Errore nella visualizzazione delle preferenze:\n{str(e)}")

def remove_preference(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    query = " ".join(context.args).strip()

    if not query:
        update.message.reply_text("❗ Usa: /remove <titolo/artista/film>")
        return

    data = load_data()

    if user_id not in data or query not in data[user_id]:
        update.message.reply_text("⚠️ Preferenza non trovata.")
        return

    data[user_id].remove(query)
    save_data(data)
    update.message.reply_text(
        f"🗑️ Preferenza rimossa: *{escape_markdown_v2(query)}*",
        parse_mode="MarkdownV2"
    )



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

    user_query = ",".join(data[user_id])


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
        result = response.json()

        suggestions = result.get("similar", {}).get("results", [])
        if not suggestions:
            update.message.reply_text("⚠️ Nessun suggerimento trovato.")
            return

        message = f"🎯 *Suggerimenti per* _{escape_markdown_v2(user_query)}_:\n\n"
        for item in suggestions:
            name = escape_markdown_v2(item.get("name", ""))
            teaser = escape_markdown_v2(item.get("description") or "Nessuna descrizione disponibile.")
            link = escape_markdown_v2(item.get("wUrl", ""))
            message += f"🎬 *{name}*\n{teaser}\n🔗 {link}\n\n"

        update.message.reply_text(message.strip(), parse_mode="MarkdownV2", disable_web_page_preview=True)

    except Exception as e:
        update.message.reply_text(f"Errore: {escape_markdown_v2(str(e))}", parse_mode="MarkdownV2")








# === Avvio Bot ===
def main():
    updater = Updater(TELEGRAM_TOKEN)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("set", set_preference))
    dp.add_handler(CommandHandler("recommend", recommend))
    dp.add_handler(CommandHandler("clear", clear_preferences))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(CommandHandler("list", list_preferences))
    dp.add_handler(CommandHandler("remove", remove_preference))
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
