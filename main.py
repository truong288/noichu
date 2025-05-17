from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from stay_alive import keep_alive
import asyncio
import re
import json
import os

keep_alive()

# Game state
players = []
current_phrase = ""
used_phrases = {}
current_player_index = 0
in_game = False
waiting_for_phrase = False
turn_timeout_task = None

# Banned words
BANNED_WORDS = {"đần", "bần", "ngu", "ngốc", "bò", "dốt", "nát", "chó", "địt", "mẹ", "mày", "má"}

# Stats
STATS_FILE = "winners.json"
def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_stats(data):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

stats = load_stats()

def reset_game_state():
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

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game_state()
    global stats
    stats = {}
    save_stats(stats)
    await update.message.reply_text("✅ Trò chơi và bảng xếp hạng đã được reset!")

def is_vietnamese(text):
    text = text.strip().lower()
    if len(text.split()) != 2:
        return False
    if re.search(r'[0-9]', text):
        return False
    if re.search(r'[a-zA-Z]', text) and not re.search(r'[à-ỹ]', text):
        return False
    return True

def contains_banned_words(text):
    words = text.lower().split()
    return any(word in BANNED_WORDS for word in words)

def get_player_name(user):
    """Lấy tên hiển thị của người chơi (first_name + last_name nếu có)"""
    if user.last_name:
        return f"{user.first_name} {user.last_name}"
    return user.first_name

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game_state()
    global in_game
    in_game = True
    await update.message.reply_text("🎮 Trò chơi bắt đầu!\n"
                                   "👉 Gõ /join để tham gia.\n"
                                   "👉 Gõ /begin để bắt đầu chơi.")

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players
    user = update.effective_user
    if user.id not in players:
        players.append(user.id)
        await update.message.reply_text(f"✅ {get_player_name(user)} đã tham gia... (Tổng {len(players)})")
    else:
        await update.message.reply_text("⚠️ Bạn đã tham gia rồi!")

async def begin_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global waiting_for_phrase
    if len(players) < 2:
        await update.message.reply_text("❗ Cần ít nhất 2 người chơi để bắt đầu.")
        return
    waiting_for_phrase = True
    user_id = players[current_player_index]
    user = await context.bot.get_chat(user_id)
    await update.message.reply_text(f"✏️ {get_player_name(user)}, hãy nhập cụm từ đầu tiên (gồm 2 từ tiếng Việt)")
    await start_turn_timer(context)

async def play_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_phrase, current_player_index, used_phrases, players, in_game, waiting_for_phrase, turn_timeout_task
    if not in_game:
        return

    user = update.effective_user
    text = update.message.text.strip().lower()

    if user.id != players[current_player_index]:
        return

    if not is_vietnamese(text):
        await eliminate_player(update, context, "Phải nhập đúng 2 từ tiếng Việt (không số/tiếng Anh)")
        return

    if contains_banned_words(text):
        await eliminate_player(update, context, "Sử dụng từ không phù hợp")
        return

    if waiting_for_phrase:
        current_phrase = text
        used_phrases[text] = 1
        waiting_for_phrase = False
        current_player_index = (current_player_index + 1) % len(players)
        current_word = current_phrase.split()[-1]
        next_user = await context.bot.get_chat(players[current_player_index])
        await update.message.reply_text(
            f"✅ Từ bắt đầu là: '{text}'\n\n"
            f"🔄 Lượt chơi tiếp theo\n"
            f"👉 Từ cần nói: 『{current_word}』\n"
            f"👤 Người chơi: {get_player_name(next_user)}\n"
            f"⏳ Thời gian: 60 giây"
        )
        await start_turn_timer(context)
        return

    if text.split()[0] != current_phrase.split()[-1]:
        await eliminate_player(update, context, f"Từ đầu phải là: {current_phrase.split()[-1]}")
        return

    if used_phrases.get(text, 0) >= 1:
        await eliminate_player(update, context, "Cụm từ đã được dùng")
        return

    used_phrases[text] = 1
    current_phrase = text
    current_player_index = (current_player_index + 1) % len(players)

    if len(players) == 1:
        await announce_winner(update, context)
        return

    current_word = current_phrase.split()[-1]
    next_user = await context.bot.get_chat(players[current_player_index])
    await update.message.reply_text(
        f"✅ Hợp lệ!\n\n"
        f"🔄 Lượt chơi tiếp theo\n"
        f"👉 Từ cần nói: 『{current_word}』\n"
        f"👤 Người chơi: {get_player_name(next_user)}\n"
        f"⏳ Thời gian: 60 giây"
    )
    await start_turn_timer(context)

async def eliminate_player(update, context, reason):
    global players, current_player_index
    user = update.effective_user
    await update.message.reply_text(f"❌ {get_player_name(user)} bị loại: {reason}")
    players.remove(user.id)
    if current_player_index >= len(players):
        current_player_index = 0
    if len(players) == 1:
        await announce_winner(update, context)
    else:
        current_word = current_phrase.split()[-1]
        next_user = await context.bot.get_chat(players[current_player_index])
        await update.message.reply_text(
            f"🔄 Lượt chơi tiếp theo\n"
            f"👉 Từ cần nối: 『{current_word}』\n"
            f"👤 Người chơi: {get_player_name(next_user)}\n"
            f"⏳ Thời gian: 59 giây"
        )
        await start_turn_timer(context)

async def announce_winner(update, context):
    winner_id = players[0]
    winner = await context.bot.get_chat(winner_id)
    winner_name = get_player_name(winner)
    stats[winner_name] = stats.get(winner_name, 0) + 1
    save_stats(stats)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🏆 {winner_name} Vô Địch Nối CHỮ! 🏆\n"
             f"📊 Thắng: {stats[winner_name]} lần"
    )
    reset_game_state()

async def start_turn_timer(context):
    global turn_timeout_task
    if turn_timeout_task:
        turn_timeout_task.cancel()
    turn_timeout_task = asyncio.create_task(turn_timer(context))

async def turn_timer(context):
    global players, current_player_index
    try:
        await asyncio.sleep(59)
        user_id = players[current_player_index]
        user = await context.bot.get_chat(user_id)
        await context.bot.send_message(
            chat_id=context._chat_id,
            text=f"⏰ {get_player_name(user)} hết thời gian và bị loại!"
        )
        players.remove(user_id)
        if len(players) == 1:
            await announce_winner(None, context)
        else:
            if current_player_index >= len(players):
                current_player_index = 0
            current_word = current_phrase.split()[-1]
            next_user = await context.bot.get_chat(players[current_player_index])
            await context.bot.send_message(
                chat_id=context._chat_id,
                text=f"🔄 Lượt chơi tiếp theo\n"
                     f"👉 Từ cần nối: 『{current_word}』\n"
                     f"👤 Người chơi: {get_player_name(next_user)}\n"
                     f"⏳ Thời gian: 59 giây"
            )
            await start_turn_timer(context)
    except asyncio.CancelledError:
        pass

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/startgame - bắt đầu trò chơi\n"
        "/join - tham gia\n"
        "/begin - người đầu tiên nhập cụm từ\n"
        "/win - xem thống kê người thắng\n"
        "/reset - reset trò chơi và bảng xếp hạng\n"
        "/help - hướng dẫn\n\n"
        "📌 Luật chơi:\n"
        "- Cụm từ phải gồm 2 từ tiếng Việt\n"
        "- Từ đầu phải nối đúng từ cuối cụm trước\n"
        "- Không lặp lại\n"
        "- Không dùng số, tiếng Anh hay từ cấm\n"
        "- Mỗi lượt có 59 giây"
    )

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not stats:
        await update.message.reply_text("Chưa có ai thắng cả!")
        return
    ranking = sorted(stats.items(), key=lambda x: x[1], reverse=True)
    message = "🏅 Bảng xếp hạng chiến thắng:\n"
    for i, (name, count) in enumerate(ranking, 1):
        message += f"{i}. {name}: {count} lần\n"
    await update.message.reply_text(message)

if __name__ == '__main__':
    TOKEN = "7670306744:AAHIKDeed6h3prNCmkFhFydwrHkxJB5HM6g"  # Thay bằng token thật
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("startgame", start_game))
    app.add_handler(CommandHandler("join", join_game))
    app.add_handler(CommandHandler("begin", begin_game))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("win", show_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, play_word))
    
    app.run_polling()
