import os
import sqlite3
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from yt_dlp import YoutubeDL

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN = '8874459874:AAE2BGv73zLVieM5rwYQNZtZ9sy8ICM5mCI'

# ThreadPoolExecutor
executor = ThreadPoolExecutor(max_workers=5)

# --- SQLite Ma'lumotlar Bazasi ---
def init_db():
    conn = sqlite3.connect('music_cache.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cache (
            video_id TEXT PRIMARY KEY,
            file_id TEXT,
            title TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_cached_file(video_id):
    conn = sqlite3.connect('music_cache.db')
    cursor = conn.cursor()
    cursor.execute('SELECT file_id, title FROM cache WHERE video_id = ?', (video_id,))
    result = cursor.fetchone()
    conn.close()
    return result

def save_to_cache(video_id, file_id, title):
    conn = sqlite3.connect('music_cache.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO cache (video_id, file_id, title) VALUES (?, ?, ?)', (video_id, file_id, title))
    conn.commit()
    conn.close()

# --- YouTube Qidiruv va Yuklab Olish ---
def search_youtube(query, max_results=5):
    """YouTube'dan Top 5 ta natijani qidirish"""
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'default_search': f'ytsearch{max_results}:',
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
        results = []
        if 'entries' in info:
            for entry in info['entries']:
                results.append({
                    'id': entry.get('id'),
                    'title': entry.get('title', 'Musiqa'),
                    'duration': entry.get('duration_string', '--:--')
                })
        return results

def download_audio_by_id(video_id):
    """Aynan tanlangan videoni yuklab olish"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': f'{video_id}.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }],
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get('title', 'Musiqa')
        filepath = f"{video_id}.mp3"
        return filepath, title

# --- Bot Handler'lari ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"Salom, {user_name}! 👋\n\n"
        f"🎶 **YangiKuylar** botiga xush kelibsiz!\n"
        f"Menga qo'shiq nomini yuboring, men sizga eng mos natijalarni topib beraman."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    status_msg = await update.message.reply_text("🔎 Qidirilmoqda...")

    loop = asyncio.get_running_loop()
    try:
        results = await loop.run_in_executor(executor, search_youtube, query)

        if not results:
            await status_msg.edit_text("❌ Hech narsa topilmadi.")
            return

        keyboard = []
        for idx, item in enumerate(results, start=1):
            btn_text = f"🎵 {idx}. {item['title'][:35]}... ({item['duration']})"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"dl_{item['id']}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await status_msg.edit_text("👇 **Kerakli musiqani tanlang:**", reply_markup=reply_markup)

    except Exception as e:
        logging.error(f"Xatolik: {e}")
        await status_msg.edit_text("❌ Qidiruvda xatolik yuz berdi.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    video_id = query.data.replace("dl_", "")

    # 1. Baza (Kesh) dan izlash
    cached = get_cached_file(video_id)
    if cached:
        file_id, title = cached
        await query.message.reply_audio(
            audio=file_id,
            title=title,
            caption="🎶 **YangiKuylar** (Tezkor yuklov)"
        )
        return

    # 2. Agar bazada bo'lmasa yuklab olish
    status_msg = await query.message.reply_text("⚡ Yuklanmoqda...")
    loop = asyncio.get_running_loop()

    try:
        filepath, title = await loop.run_in_executor(executor, download_audio_by_id, video_id)

        if filepath and os.path.exists(filepath):
            await status_msg.edit_text("📤 Yuborilmoqda...")

            with open(filepath, 'rb') as audio_file:
                sent = await query.message.reply_audio(
                    audio=audio_file,
                    title=title,
                    caption="🎶 **YangiKuylar** boti orqali yuklab olindi"
                )

            # Bazaga saqlash
            if sent.audio:
                save_to_cache(video_id, sent.audio.file_id, title)

            await status_msg.delete()
            os.remove(filepath)
        else:
            await status_msg.edit_text("❌ Faylni yuklab bo'lmadi.")

    except Exception as e:
        logging.error(f"Xatolik: {e}")
        await status_msg.edit_text("❌ Yuklashda xatolik yuz berdi.")

def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback, pattern="^dl_"))

    print("YangiKuylar Ultra boti ishga tushdi...")
    app.run_polling()

if __name__ == '__main__':
    main()