import asyncio
import re
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# Game state
players = []
current_phrase = ""
used_phrases = {}
current_player_index = 0
in_game = False
waiting_for_phrase = False
turn_timeout_task = None
win_counts = {}

BAD_WORDS = {"đần", "bần", "ngu", "ngốc", "bò", "dốt", "nát", "chó", "má"}

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
    return bool(re.search(r'[àáạảãâầấậẩẫăằắặẳẵêèéẹẻẽềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡ'
                          r'ùúụủũưừứựửữỳýỵỷỹđ]', text))

def contains_bad_word(phrase):
    return any(bad in phrase.split() for bad in BAD_WORDS)

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game()
    global in_game
    in_game = True
    await update.message.reply_text("🎮 Trò chơi bắt đầu!\n👉 Gõ /join để tham gia.\n👉 Gõ /begin để bắt đầu chơi.")

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players
    user = update.effective_user
    if user.id not in players:
        players.append(user.id)
        await update.message.reply_text(f"✅ {user.first_name} đã tham gia... (Tổng {len(players)})")
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
        f"✏️ {mention}, Hãy nhập cụm từ đầu tiên để bắt đầu!",
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
        await eliminate_player(update, context, reason="Dùng tiếng Việt")
        return

    words = text.split()
    if len(words) != 2:
        await eliminate_player(update, context, reason="Cụm từ phải gồm đúng 2 từ.")
        return

    if contains_bad_word(text):
        await eliminate_player(update, context, reason="Không Nghĩa.")
        return

    if used_phrases.get(text, 0) >= 1:
        await eliminate_player(update, context, reason="Cụm từ đã được dùng.")
        return

    if not waiting_for_phrase and words[0] != current_phrase.split()[-1]:
        await eliminate_player(update, context, reason="Không đúng từ nối.")
        return

    # Hợp lệ
    used_phrases[text] = 1
    current_phrase = text
    waiting_for_phrase = False
    current_player_index = (current_player_index + 1) % len(players)

    if len(players) == 1:
        winner_id = players[0]
        win_counts[winner_id] = win_counts.get(winner_id, 0) + 1
        chat = await context.bot.get_chat(winner_id)
        mention = f"<a href='tg://user?id={winner_id}'>@{chat.username or chat.first_name}</a>"
        await update.message.reply_text(
            f"🏆 {mention} Vô Địch Nối CHỮ! Tổng chiến thắng: {win_counts[winner_id]}",
            parse_mode="HTML")
        reset_game()
        return

    next_id = players[current_player_index]
    next_chat = await context.bot.get_chat(next_id)
    mention = f"<a href='tg://user?id={next_id}'>@{next_chat.username or next_chat.first_name}</a>"

    await update.message.reply_text(
        f"✅ Hợp lệ! \u2003\u2003 Từ tiếp theo nối với: '{current_phrase.split()[-1]}'.\u2003 Tới lượt bạn! {mention} ",
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
    elif eliminated_index == current_player_index:
        if current_player_index >= len(players):
            current_player_index = 0

    if len(players) == 1:
        winner_id = players[0]
        win_counts[winner_id] = win_counts.get(winner_id, 0) + 1
        chat = await context.bot.get_chat(winner_id)
        mention = f"<a href='tg://user?id={winner_id}'>@{chat.username or chat.first_name}</a>"
        await update.message.reply_text(
            f"🏆 {mention} Vô Địch Nối CHỮ! Tổng chiến thắng: {win_counts[winner_id]}",
            parse_mode="HTML")
        reset_game()
    else:
        await update.message.reply_text(f"👥 Còn lại {len(players)} người chơi.")
        next_id = players[current_player_index]
        next_chat = await context.bot.get_chat(next_id)
        mention = f"<a href='tg://user?id={next_id}'>@{next_chat.username or next_chat.first_name}</a>"
        await update.message.reply_text(
            f"✏️ {mention}, Hãy nối tiếp với từ: '{current_phrase.split()[-1]}'",
            parse_mode="HTML"
        )
        await start_turn_timer(context)

async def turn_timer(context):
    await asyncio.sleep(59)
    user_id = players[current_player_index]
    chat = await context.bot.get_chat(user_id)
    mention = f"<a href='tg://user?id={user_id}'>@{chat.username or chat.first_name}</a>"
    await context.bot.send_message(chat_id=context._chat_id, text=f"⏰ {mention} hết thời gian và bị loại!", parse_mode="HTML")
    await eliminate_player_by_id(context, user_id)

async def eliminate_player_by_id(context, user_id):
    global current_player_index
    if user_id in players:
        index = players.index(user_id)
        players.remove(user_id)
        if index <= current_player_index and current_player_index > 0:
            current_player_index -= 1

        if len(players) == 1:
            winner_id = players[0]
            win_counts[winner_id] = win_counts.get(winner_id, 0) + 1
            chat = await context.bot.get_chat(winner_id)
            mention = f"<a href='tg://user?id={winner_id}'>@{chat.username or chat.first_name}</a>"
            await context.bot.send_message(chat_id=context._chat_id, text=f"🏆 {mention} Vô Địch Nối CHỮ! Tổng chiến thắng: {win_counts[winner_id]}", parse_mode="HTML")
            reset_game()
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
        "/begin - Người đầu tiên nhập cụm từ\n"
        "/win - Bảng xếp hạng\n"
        "/help - Hướng dẫn")

async def win_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not win_counts:
        await update.message.reply_text("Chưa có ai chiến thắng trong trò chơi này.")
        return

    sorted_winners = sorted(win_counts.items(), key=lambda x: x[1], reverse=True)
    leaderboard = "🏆 BẢNG XẾP HẠNG CHIẾN THẮNG:\n"
    for idx, (user_id, count) in enumerate(sorted_winners, start=1):
        chat = await context.bot.get_chat(user_id)
        name = chat.username or chat.first_name
        leaderboard += f"{idx}. {name}: {count} lần thắng\n"

    await update.message.reply_text(leaderboard)

if __name__ == '__main__':
    TOKEN = "7670306744:AAHIKDeed6h3prNCmkFhFydwrHkxJB5HM6g"
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("startgame", start_game))
    app.add_handler(CommandHandler("join", join_game))
    app.add_handler(CommandHandler("begin", begin_game))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("win", win_leaderboard))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, play_word))

    print("Bot is running...")
    app.run_polling()
