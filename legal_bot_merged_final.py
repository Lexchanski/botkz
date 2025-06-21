# -*- coding: utf-8 -*-
# Полный Telegram-бот: команды, OpenAI, PDF, admin-панель, кодексы

import logging, openai, time, re, requests, sqlite3, csv, pymorphy2, tempfile
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, CallbackQueryHandler, ConversationHandler, filters
)
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from asyncio import create_task

# === Настройки ===
TELEGRAM_BOT_TOKEN = "8091332261:AAFHAcrDfqRRXLVTzUbyjOYhBZ1bSPKCS1A"
OPENAI_API_KEY = "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"
ASSISTANT_ID = "asst_gu9QvMHLC5qPOAkZZpkjxm4b"
ADMIN_USERNAME = "@lexchanski"
openai.api_key = OPENAI_API_KEY
logging.basicConfig(level=logging.INFO)
DB_PATH = "kodeks.db"

morph = pymorphy2.MorphAnalyzer()
def normalize(text):
    words = re.findall(r"\w+", text.lower())
    return set(morph.parse(w)[0].normal_form for w in words)

def load_crime_keywords(file_path="crime_keywords.csv"):
    mapping = {}
    try:
        with open(file_path, newline="", encoding="utf-8") as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                if len(row) >= 3:
                    phrases = [p.strip().lower() for p in row[0].split(';')]
                    kodeks, article = row[1].strip(), row[2].strip()
                    for phrase in phrases:
                        norm = normalize(phrase)
                        if norm: mapping[frozenset(norm)] = (kodeks, article)
    except Exception as e:
        logging.warning(f"Ключевые слова: {e}")
    return mapping
crime_map = load_crime_keywords()

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS kodeks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kodeks_name TEXT, article_num TEXT,
            article_title TEXT, article_text TEXT,
            last_update TIMESTAMP)''')
        conn.commit()

CODEKS_SOURCES = {
    "УК РК": "https://adilet.zan.kz/rus/docs/K1400000226"
}

def fetch_all_kodeks():
    total = 0
    for name, url in CODEKS_SOURCES.items():
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            text = resp.text[:2000]
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute('''INSERT OR REPLACE INTO kodeks 
                    (kodeks_name, article_num, article_title, article_text, last_update)
                    VALUES (?, ?, ?, ?, ?)''', (name, "0", name + " (обновлено)", text, datetime.now()))
                conn.commit()
            total += 1
        except Exception as e:
            logging.error(f"Ошибка {name}: {e}")
    return total

async def sync_kodeks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Синхронизация...")
    count = fetch_all_kodeks()
    await update.message.reply_text(f"✅ Загружено: {count}")

LAST_SYNC = None
SYNC_INTERVAL = timedelta(days=1)
async def kodeks_autosync(context=None):
    global LAST_SYNC
    now = datetime.now()
    if LAST_SYNC and (now - LAST_SYNC < SYNC_INTERVAL): return
    try:
        logging.info("⏳ Автообновление...")
        fetch_all_kodeks()
        LAST_SYNC = now
    except Exception as e:
        logging.error(f"❌ Ошибка: {e}")


from telegram import ReplyKeyboardMarkup

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["📚 Кодексы", "📝 Документы"],
        ["🆘 Помощь", "💬 Связаться"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "👋 Добро пожаловать в Юридический Бот РК!"
        "Выберите действие с помощью кнопок или отправьте вопрос в свободной форме.",
        reply_markup=reply_markup
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 *Бот может:*\n\n"
        "📘 Найти статьи кодексов\n"
        "📄 Выдать шаблоны документов\n"
        "🌐 Сменить язык\n"
        "📞 Показать контакты")

async def templates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📄 Шаблоны пока в разработке.")

async def language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🇷🇺 Русский / 🇰🇿 Қазақ тілі")

async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📬 Telegram: @lexchanski\nEmail: tleulov04@mail.ru")

def generate_pdf(text: str, filename_hint="document") -> tuple[str, str]:
    filename = f"{filename_hint}.pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
        c = canvas.Canvas(tmp_pdf.name, pagesize=A4)
        y = A4[1] - 50
        for line in text.split("\n"):
            if y < 50: c.showPage(); y = A4[1] - 50
            c.drawString(50, y, line)
            y -= 15
        c.save()
    return tmp_pdf.name, filename

def detect_doc_type(text: str) -> str:
    text = text.lower()
    if text.startswith("исковое заявление"): return "isk"
    elif text.startswith("жалоба"): return "zhaloba"
    return "document"

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "get_pdf":
        text = context.user_data.get("last_reply", "")
        doc_type = context.user_data.get("pdf_type", "document")
        pdf_path, file_name = generate_pdf(text, filename_hint=doc_type)
        await query.message.reply_document(InputFile(pdf_path), filename=file_name)
    elif query.data == "cancel_pdf":
        await query.message.reply_text("❌ PDF отменён.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    norm_msg = normalize(msg)
    for key_norm, (kodeks, art) in crime_map.items():
        if key_norm.issubset(norm_msg):
            await update.message.reply_text(f"По запросу: {kodeks}, статья {art}")
            return
    try:
        thread_id = context.user_data.get("thread_id")
        if not thread_id:
            thread = openai.beta.threads.create()
            context.user_data["thread_id"] = thread.id
        else:
            thread = openai.beta.threads.retrieve(thread_id)
        openai.beta.threads.messages.create(thread_id=thread.id, role="user", content=msg)
        run = openai.beta.threads.runs.create(thread_id=thread.id, assistant_id=ASSISTANT_ID)
        while True:
            status = openai.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
            if status.status == "completed": break
            time.sleep(0.5)
        reply = openai.beta.threads.messages.list(thread_id=thread.id).data[0].content[0].text.value
        await update.message.reply_text(reply)
        if any(reply.lower().startswith(x) for x in ["исковое заявление", "жалоба"]):
            context.user_data["last_reply"] = reply
            context.user_data["pdf_type"] = detect_doc_type(reply)
            buttons = [[InlineKeyboardButton("📄 Получить PDF", callback_data="get_pdf"),
                        InlineKeyboardButton("❌ Не нужно", callback_data="cancel_pdf")]]
            await update.message.reply_text("Хотите PDF?", reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        logging.error(f"OpenAI: {e}")
        await update.message.reply_text("⚠️ Ошибка OpenAI")

# === Заглушки admin-панели ===
ADD_PHRASE, DELETE_PHRASE = range(2)
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔧 Пока admin-панель заглушка.")

async def admin_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass
async def receive_new_phrase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass
async def receive_delete_phrase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass
async def kodeks_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Поиск по кодексам пока не реализован.")
async def handle_language_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = query.data
    if lang == "lang_ru":
        await query.edit_message_text("✅ Язык установлен: Русский 🇷🇺")
    elif lang == "lang_kz":
        await query.edit_message_text("✅ Тіл таңдалды: Қазақ тілі 🇰🇿")
def main():
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("templates", templates))
    app.add_handler(CommandHandler("language", language))
    app.add_handler(CommandHandler("contact", contact))
    app.add_handler(CommandHandler("kodeks", kodeks_handler))
    app.add_handler(CommandHandler("sync_kodeks", sync_kodeks_cmd))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(CallbackQueryHandler(admin_button_handler))
    app.add_handler(ConversationHandler(
        entry_points=[],
        states={
            ADD_PHRASE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_phrase)],
            DELETE_PHRASE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_delete_phrase)],
        },
        fallbacks=[], allow_reentry=True
    ))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.job_queue.run_repeating(kodeks_autosync, interval=3600, first=5)
    app.run_polling()
    
if __name__ == "__main__":
    main()