import os
import threading
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# Biến môi trường
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

# Flask app
flask_app = Flask(__name__)
telegram_app = None  # sẽ gán sau

# Game state
players = []
current_phrase = ""
used_phrases = {}
current_player_index = 0
in_game = False
waiting_for_phrase = False
turn_timeout_task = None

def reset_game():
    global players, current_phrase, used_phrases, current_player_index, in_game, waiting_for_phrase, turn_timeout_task
    players = []
    current_phrase = ""
    used_phrases = {}
    current_player_index = 0
    in_game = False
    waiting_for_phrase = False
    if turn_timeout_task:
        turn_timeout_task.cancel()
        turn_timeout_task = None

# --- HANDLERS GAME ---

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game()
    global in_game
    in_game = True
    await update.message.reply_text(
        "🎮 Trò chơi bắt đầu!\nGõ /join để tham gia.\nGõ /begin để bắt đầu lượt đầu tiên."
    )

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players
    user = update.effective_user
    if user.id not in players:
        players.append(user.id)
        await update.message.reply_text(
            f"✅ {user.first_name} đã tham gia... (Tổng {len(players)} người)")
    else:
        await update.message.reply_text("⚠️ Bạn đã tham gia rồi!")

async def begin_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_player_index, waiting_for_phrase
    if len(players) < 2:
        await update.message.reply_text("❗ Cần ít nhất 2 người chơi để bắt đầu.")
        return
    waiting_for_phrase = True
    user_id = players[current_player_index]
    chat = await context.bot.get_chat(user_id)
    mention = f"<a href='tg://user?id={user_id}'>@{chat.username or chat.first_name}</a>"
    await update.message.reply_text(
        f"✏️ {mention}, hãy nhập cụm từ đầu tiên để bắt đầu trò chơi!",
        parse_mode="HTML")
    await start_turn_timer(context)

async def play_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_phrase, current_player_index, used_phrases, players, in_game, waiting_for_phrase, turn_timeout_task

    if not in_game:
        return

    user = update.effective_user
    text = update.message.text.strip().lower()

    if user.id != players[current_player_index]:
        return
    words = text.split()
    if len(words) != 2:
        await eliminate_player(update, context, reason="Cụm từ phải gồm đúng 2 từ")
        return
    if waiting_for_phrase:
        current_phrase = text
        used_phrases[text] = 1
        waiting_for_phrase = False
        current_player_index = (current_player_index + 1) % len(players)
        next_id = players[current_player_index]
        next_chat = await context.bot.get_chat(next_id)
        mention = f"<a href='tg://user?id={next_id}'>@{next_chat.username or next_chat.first_name}</a>"
        await update.message.reply_text(
            f"✅ Từ bắt đầu là: '{text}'. {mention}, hãy nối với từ '{words[-1]}'",
            parse_mode="HTML")
        await start_turn_timer(context)
        return
    if words[0] != current_phrase.split()[-1]:
        await eliminate_player(update, context, reason="Từ đầu không khớp với từ cuối trước đó")
        return
    if used_phrases.get(text, 0) >= 1:
        await eliminate_player(update, context, reason="Cụm từ đã bị dùng")
        return
    used_phrases[text] = used_phrases.get(text, 0) + 1
    current_phrase = text
    current_player_index = (current_player_index + 1) % len(players)
    if len(players) == 1:
        winner_id = players[0]
        chat = await context.bot.get_chat(winner_id)
        mention = f"<a href='tg://user?id={winner_id}'>@{chat.username or chat.first_name}</a>"
        await update.message.reply_text(f"🏆 {mention} GIÀNH CHIẾN THẮNG!", parse_mode="HTML")
        reset_game()
        return
    next_id = players[current_player_index]
    next_chat = await context.bot.get_chat(next_id)
    next_mention = f"<a href='tg://user?id={next_id}'>@{next_chat.username or next_chat.first_name}</a>"
    await update.message.reply_text(
        f"✅ Hợp lệ! '{words[-1]}' là từ cần nối tiếp. {next_mention}, tới lượt bạn!",
        parse_mode="HTML")
    await start_turn_timer(context)

async def eliminate_player(update, context, reason):
    global players, current_player_index
    user = update.effective_user
    await update.message.reply_text(f"❌ {user.first_name} bị loại! Lý do: {reason}")
    players.remove(user.id)
    if current_player_index >= len(players):
        current_player_index = 0
    if len(players) == 1:
        winner_id = players[0]
        chat = await context.bot.get_chat(winner_id)
        mention = f"<a href='tg://user?id={winner_id}'>@{chat.username or chat.first_name}</a>"
        await update.message.reply_text(f"🏆 {mention} GIÀNH CHIẾN THẮNG!", parse_mode="HTML")
        reset_game()
    else:
        await update.message.reply_text(f"Hiện còn lại {len(players)} người chơi.")
        await start_turn_timer(context)

async def start_turn_timer(context):
    global turn_timeout_task
    if turn_timeout_task:
        turn_timeout_task.cancel()
    turn_timeout_task = asyncio.create_task(turn_timer(context))

async def turn_timer(context):
    global players, current_player_index
    try:
        await asyncio.sleep(60)
        user_id = players[current_player_index]
        chat = await context.bot.get_chat(user_id)
        mention = f"<a href='tg://user?id={user_id}'>@{chat.username or chat.first_name}</a>"
        await context.bot.send_message(
            chat_id=chat.id,
            text=f"⏰ {mention} hết thời gian và bị loại!",
            parse_mode="HTML")
        players.remove(user_id)
        if len(players) == 1:
            winner_id = players[0]
            winner_chat = await context.bot.get_chat(winner_id)
            mention = f"<a href='tg://user?id={winner_id}'>@{winner_chat.username or winner_chat.first_name}</a>"
            await context.bot.send_message(
                chat_id=winner_chat.id,
                text=f"🏆 {mention} GIÀNH CHIẾN THẮNG!",
                parse_mode="HTML")
            reset_game()
            return
        if current_player_index >= len(players):
            current_player_index = 0
        await start_turn_timer(context)
    except asyncio.CancelledError:
        pass

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/startgame - bắt đầu trò chơi\n/join - tham gia\n/begin - người đầu tiên nhập cụm từ\n/help - hướng dẫn"
    )

# --- WEBHOOK ROUTES ---

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), telegram_app.bot)
    asyncio.run(telegram_app.process_update(update))
    return "ok"

@flask_app.route('/')
def home():
    return "Bot is alive!"

# --- RUN BOT + FLASK ---

def run_bot():
    global telegram_app
    telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()

    telegram_app.add_handler(CommandHandler("startgame", start_game))
    telegram_app.add_handler(CommandHandler("join", join_game))
    telegram_app.add_handler(CommandHandler("begin", begin_game))
    telegram_app.add_handler(CommandHandler("help", help_command))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, play_word))

    asyncio.run(telegram_app.bot.set_webhook(f"{WEBHOOK_URL}/webhook"))

if __name__ == '__main__':
    threading.Thread(target=run_bot).start()
    flask_app.run(host="0.0.0.0", port=8080)
