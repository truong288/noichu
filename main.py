import asyncio
import os
import re
from telegram import Update
from telegram.ext import Application
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ==== TRẠNG THÁI GAME ====
players = []
current_phrase = ""
used_phrases = {}
current_player_index = 0
in_game = False
waiting_for_phrase = False
turn_timeout_task = None
win_counts = {}

BAD_WORDS = {"đần", "bần", "ngu", "ngốc", "bò", "dốt", "nát", "chó","địt","mẹ","mày", "má"}

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

def is_vietnamese(text):
    return bool(re.search(r'[àáạảãâầấậẩẫăắặẳẵêèéẹẻẽềếệểễìíịỉĩòóọỏõôồốộổỗơớợởỡùúụủũưứựửữỳýỵỷỹđ]', text))

def contains_bad_word(phrase):
    return any(bad in phrase.split() for bad in BAD_WORDS)

# ==== LỆNH ====
async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game()
    global in_game
    in_game = True
    await update.message.reply_text("🎮 Bắt đầu trò chơi!\n👉 /join để tham gia\n👉 /begin để khởi động")

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players
    user = update.effective_user
    if user.id not in players:
        players.append(user.id)
        await update.message.reply_text(f"✅ {user.first_name} đã tham gia (Tổng: {len(players)})")
    else:
        await update.message.reply_text("⚠️ Bạn đã tham gia rồi!")

async def begin_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_player_index, waiting_for_phrase
    if len(players) < 2:
        await update.message.reply_text("❗ Cần ít nhất 2 người chơi.")
        return

    waiting_for_phrase = True
    user_id = players[current_player_index]
    chat = await context.bot.get_chat(user_id)
    mention = f"<a href='tg://user?id={user_id}'>@{chat.username or chat.first_name}</a>"
    await update.message.reply_text(
        f"✏️ {mention}, hãy nhập cụm từ đầu tiên để bắt đầu!",
        parse_mode="HTML")
    await start_turn_timer(context)

async def play_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_phrase, current_player_index, used_phrases, players, in_game, waiting_for_phrase

    if not in_game:
        return

    user = update.effective_user
    text = update.message.text.strip().lower()

    if user.id != players[current_player_index]:
        return

    if not is_vietnamese(text):
        await eliminate_player(update, context, "Không dùng tiếng Việt.")
        return

    words = text.split()
    if len(words) != 2:
        await eliminate_player(update, context, "Phải gồm đúng 2 từ.")
        return

    if contains_bad_word(text):
        await eliminate_player(update, context, "Từ ngữ không phù hợp.")
        return

    if used_phrases.get(text):
        await eliminate_player(update, context, "Cụm từ đã dùng.")
        return

    if not waiting_for_phrase and words[0] != current_phrase.split()[-1]:
        await eliminate_player(update, context, "Không đúng từ nối.")
        return

    used_phrases[text] = 1
    current_phrase = text
    waiting_for_phrase = False
    current_player_index = (current_player_index + 1) % len(players)

    if len(players) == 1:
        await declare_winner(context, players[0])
        return

    next_id = players[current_player_index]
    next_chat = await context.bot.get_chat(next_id)
    mention = f"<a href='tg://user?id={next_id}'>@{next_chat.username or next_chat.first_name}</a>"
    await update.message.reply_text(
        f"✅ Hợp lệ!\n➡️ Từ tiếp theo bắt đầu bằng: '{current_phrase.split()[-1]}'\nTới lượt {mention}",
        parse_mode="HTML")
    await start_turn_timer(context)

async def eliminate_player(update, context, reason):
    global players, current_player_index
    user = update.effective_user
    await update.message.reply_text(f"❌ {user.first_name} bị loại! Lý do: {reason}")
    eliminated_index = players.index(user.id)
    players.remove(user.id)

    if eliminated_index < current_player_index:
        current_player_index -= 1
    elif eliminated_index == current_player_index and current_player_index >= len(players):
        current_player_index = 0

    if len(players) == 1:
        await declare_winner(context, players[0])
    else:
        next_id = players[current_player_index]
        next_chat = await context.bot.get_chat(next_id)
        mention = f"<a href='tg://user?id={next_id}'>@{next_chat.username or next_chat.first_name}</a>"
        await update.message.reply_text(f"✏️ {mention}, tiếp tục nối từ: '{current_phrase.split()[-1]}'", parse_mode="HTML")
        await start_turn_timer(context)

async def declare_winner(context, winner_id):
    win_counts[winner_id] = win_counts.get(winner_id, 0) + 1
    chat = await context.bot.get_chat(winner_id)
    mention = f"<a href='tg://user?id={winner_id}'>@{chat.username or chat.first_name}</a>"
    await context.bot.send_message(chat_id=chat.id, text=f"🏆 {mention} VÔ ĐỊCH NỐI CHỮ! Tổng thắng: {win_counts[winner_id]}", parse_mode="HTML")
    reset_game()

async def turn_timer(context):
    await asyncio.sleep(59)
    user_id = players[current_player_index]
    chat = await context.bot.get_chat(user_id)
    mention = f"<a href='tg://user?id={user_id}'>@{chat.username or chat.first_name}</a>"
    await context.bot.send_message(chat_id=chat.id, text=f"⏰ {mention} hết giờ và bị loại!", parse_mode="HTML")
    players.remove(user_id)
    if len(players) == 1:
        await declare_winner(context, players[0])
    else:
        await start_turn_timer(context)

async def start_turn_timer(context):
    global turn_timeout_task
    if turn_timeout_task:
        turn_timeout_task.cancel()
    turn_timeout_task = asyncio.create_task(turn_timer(context))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/startgame - Bắt đầu trò chơi\n"
        "/join - Tham gia\n"
        "/begin - Khởi động\n"
        "/win - Bảng xếp hạng\n"
        "/help - Trợ giúp")

async def win_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not win_counts:
        await update.message.reply_text("Chưa có ai chiến thắng.")
        return

    sorted_winners = sorted(win_counts.items(), key=lambda x: x[1], reverse=True)
    result = "🏆 BẢNG XẾP HẠNG:\n"
    for i, (uid, count) in enumerate(sorted_winners, 1):
        chat = await context.bot.get_chat(uid)
        result += f"{i}. {chat.username or chat.first_name}: {count} lần\n"

    await update.message.reply_text(result)

# ==== CHẠY WEBHOOK ====

if __name__ == "__main__":
    import asyncio

    TOKEN = os.environ.get("BOT_TOKEN")
    DOMAIN = "https://noichu-bucw.onrender.com"

    app = Application.builder().token(TOKEN).build()

    # Handlers ...
    # app.add_handler(...)

    async def main():
        await app.bot.set_webhook(f"{DOMAIN}/webhook")
        await app.initialize()
        await app.start()
        await app.updater.start_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 5000)),
            url_path="webhook",  # chỉ dùng nếu version cũ
        )
        await app.updater.idle()

    asyncio.run(main())


