from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from stay_alive import keep_alive
import asyncio
import re

keep_alive()

# Game state
players = []
current_phrase = ""
used_phrases = {}
current_player_index = 0
in_game = False
waiting_for_phrase = False
turn_timeout_task = None

# Banned words list
BANNED_WORDS = {"đần", "bần", "ngu", "ngốc", "bò", "dốt", "nát", "chó", "địt", "mẹ", "mày", "má"}


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
    # Check if text contains Vietnamese characters
    vietnamese_chars = bool(re.search(r'[àáạảãâầấậẩẫăằắặẳẵêèéẹẻẽềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡ'
                          r'ùúụủũưừứựửữỳýỵỷỹđ]', text.lower()))
    
    # Also check if it contains numbers or English (basic check)
    has_numbers = bool(re.search(r'\d', text))
    has_english = bool(re.search(r'[a-zA-Z]', text))
    
    return vietnamese_chars and not has_numbers and not has_english


def contains_banned_words(text):
    words = text.lower().split()
    return any(word in BANNED_WORDS for word in words)


async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game()
    global in_game
    in_game = True

    await update.message.reply_text("🎮 Trò chơi bắt đầu!\n"
                                   "👉 Gõ /join Để tham gia.\n"
                                   "👉 Gõ /begin Để bắt đầu chơi.")


async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players
    user = update.effective_user
    if user.id not in players:
        players.append(user.id)
        await update.message.reply_text(
            f"✅ {user.first_name} đã tham gia... (Tổng {len(players)})")
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
        f"✏️ {mention}, Hãy nhập cụm từ đầu tiên để bắt đầu trò chơi!",
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

    if not is_vietnamese(text):
        await eliminate_player(update, context, reason="Dùng tiếng Việt ")
        return

    word_count = len(text.split())
    if word_count != 2:
        await eliminate_player(update, context, reason=f"Cụm từ phải có đúng 2 từ (bạn nhập {word_count} từ)")
        return

    if contains_banned_words(text):
        await eliminate_player(update, context, reason="Sử dụng từ không phù hợp")
        return

    if waiting_for_phrase:
        current_phrase = text
        used_phrases[text] = 1
        waiting_for_phrase = False
        current_player_index = (current_player_index + 1) % len(players)

        next_id = players[current_player_index]
        next_chat = await context.bot.get_chat(next_id)
        mention = f"<a href='tg://user?id={next_id}'>@{next_chat.username or next_chat.first_name}</a>"
        current_word = text.split()[-1]

        await update.message.reply_text(
            f"✅ Từ bắt đầu là: '{text}'\n\n"
            f"Lượt chơi tiếp theo\n"
            f"Từ cần nói: [{current_word}]\n"
            f"Người chơi: {mention}\n"
            f"Thời gian: 59 giây",
            parse_mode="HTML")
        await start_turn_timer(context)
        return

    if text.split()[0] != current_phrase.split()[-1]:
        await eliminate_player(update, context, reason=f"Không đúng từ nối (cần nối với từ '{current_phrase.split()[-1]}')")
        return

    if used_phrases.get(text, 0) >= 1:
        await eliminate_player(update, context, reason="Cụm từ đã bị sử dụng")
        return

    used_phrases[text] = 1
    current_phrase = text
    current_player_index = (current_player_index + 1) % len(players)

    if len(players) == 1:
        winner_id = players[0]
        chat = await context.bot.get_chat(winner_id)
        mention = f"<a href='tg://user?id={winner_id}'>@{chat.username or chat.first_name}</a>"
        await update.message.reply_text(f"🏆 {mention} Vô Địch Nối CHỮ!🏆🏆",
                                      parse_mode="HTML")
        reset_game()
        return

    next_id = players[current_player_index]
    next_chat = await context.bot.get_chat(next_id)
    next_mention = f"<a href='tg://user?id={next_id}'>@{next_chat.username or next_chat.first_name}</a>"
    current_word = text.split()[-1]

    await update.message.reply_text(
        f"✅ Hợp lệ!\n\n"
        f"Lượt chơi tiếp theo\n"
        f"Từ cần nói: [{current_word}]\n"
        f"Người chơi: {next_mention}\n"
        f"Thời gian: 59 giây",
        parse_mode="HTML")
    await start_turn_timer(context)


async def eliminate_player(update, context, reason):
    global players, current_player_index
    user = update.effective_user
    await update.message.reply_text(
        f"❌ {user.first_name} bị loại! Lý do: {reason}")
    players.remove(user.id)
    if current_player_index >= len(players):
        current_player_index = 0

    if len(players) == 1:
        winner_id = players[0]
        chat = await context.bot.get_chat(winner_id)
        mention = f"<a href='tg://user?id={winner_id}'>@{chat.username or chat.first_name}</a>"
        await update.message.reply_text(f"🏆 {mention} Vô Địch Nối CHỮ!🏆🏆",
                                      parse_mode="HTML")
        reset_game()
    else:
        await update.message.reply_text(
            f"Hiện còn lại {len(players)} người chơi.")
        # Show current word for next player
        next_id = players[current_player_index]
        next_chat = await context.bot.get_chat(next_id)
        next_mention = f"<a href='tg://user?id={next_id}'>@{next_chat.username or next_chat.first_name}</a>"
        current_word = current_phrase.split()[-1]
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Lượt chơi tiếp theo\n"
                 f"Từ cần nói: [{current_word}]\n"
                 f"Người chơi: {next_mention}\n"
                 f"Thời gian: 59 giây",
            parse_mode="HTML")
        await start_turn_timer(context)


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
        chat = await context.bot.get_chat(user_id)
        mention = f"<a href='tg://user?id={user_id}'>@{chat.username or chat.first_name}</a>"

        await context.bot.send_message(
            chat_id=context._chat_id,
            text=f"⏰ {mention} hết thời gian và bị loại!",
            parse_mode="HTML")
        players.remove(user_id)

        if len(players) == 1:
            winner_id = players[0]
            winner_chat = await context.bot.get_chat(winner_id)
            mention = f"<a href='tg://user?id={winner_id}'>@{winner_chat.username or winner_chat.first_name}</a>"
            await context.bot.send_message(
                chat_id=context._chat_id,
                text=f"🏆 {mention} Vô Địch Nối CHỮ!🏆🏆",
                parse_mode="HTML")
            reset_game()
            return

        if current_player_index >= len(players):
            current_player_index = 0

        # Show current word for next player
        next_id = players[current_player_index]
        next_chat = await context.bot.get_chat(next_id)
        next_mention = f"<a href='tg://user?id={next_id}'>@{next_chat.username or next_chat.first_name}</a>"
        current_word = current_phrase.split()[-1]
        
        await context.bot.send_message(
            chat_id=context._chat_id,
            text=f"Lượt chơi tiếp theo\n"
                 f"Từ cần nói: [{current_word}]\n"
                 f"Người chơi: {next_mention}\n"
                 f"Thời gian: 59 giây",
            parse_mode="HTML")
        await start_turn_timer(context)

    except asyncio.CancelledError:
        pass


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/startgame - Bắt đầu trò chơi\n/join - Tham gia\n/begin - Người đầu tiên nhập cụm từ\n/help - Hướng dẫn\n\n"
        "📌 Luật chơi:\n"
        "- Mỗi cụm từ phải gồm 2 từ tiếng Việt\n"
        "- Phải nối từ cuối của cụm từ trước\n"
        "- Không được lặp lại cụm từ\n"
        "- Không sử dụng từ cấm\n"
        "- Không dùng số hoặc tiếng Anh\n"
        "- Có 59 giây cho mỗi lượt"
    )


if __name__ == '__main__':
    TOKEN = "7670306744:AAHIKDeed6h3prNCmkFhFydwrHkxJB5HM6g"
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("startgame", start_game))
    app.add_handler(CommandHandler("join", join_game))
    app.add_handler(CommandHandler("begin", begin_game))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, play_word))

    print("Bot is running...")
    app.run_polling()
