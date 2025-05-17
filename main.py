import nest_asyncio
nest_asyncio.apply()
from telegram import Update
nest_asyncio.apply()
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import asyncio
import re

# Dictionary lưu trữ số lần chiến thắng của mỗi người chơi
win_counts = {}
players = []
current_phrase = ""
used_phrases = {}
current_player_index = 0
in_game = False
waiting_for_phrase = False
turn_timeout_task = None
BANNED_WORDS = {"đần", "bần", "ngu", "ngốc", "bò", "dốt", "nát", "chó", "địt", "mẹ", "mày", "má"}

# Hàm kiểm tra từ tiếng Việt
def is_vietnamese(text):
    return bool(re.search(r'[àáạảãâầấậẩẫăằắặẳẵêèéẹẻẽềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡ'
                          r'ùúụủũưừứựửữỳýỵỷỹđ]', text))

# Hàm kiểm tra từ cấm
def contains_banned_words(text):
    return any(word in text for word in BANNED_WORDS)

# Reset game
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

# Gửi thông báo khi chiến thắng
async def send_winner_message(update, context, winner_id):
    global win_counts
    # Cập nhật số lần chiến thắng của người chiến thắng
    if winner_id in win_counts:
        win_counts[winner_id] += 1
    else:
        win_counts[winner_id] = 1
    
    chat = await context.bot.get_chat(winner_id)
    mention = f"<a href='tg://user?id={winner_id}'>@{chat.username or chat.first_name}</a>"

    # Gửi thông báo chiến thắng
    await update.message.reply_text(
        f"🏆 {mention} Vô Địch Nối CHỮ! 🏆\n"
        f"📊 Thắng: {win_counts[winner_id]} lần",
        parse_mode="HTML"
    )

# Hiển thị thống kê chiến thắng
async def show_stats(update, context):
    global win_counts

    if not win_counts:
        await update.message.reply_text("Chưa có ai chiến thắng!")
        return

    # Sắp xếp các người chơi theo số lần chiến thắng giảm dần
    sorted_winners = sorted(win_counts.items(), key=lambda item: item[1], reverse=True)

    message = "📊 Bảng Xếp Hạng Chiến Thắng:\n"
    for winner_id, win_count in sorted_winners:
        chat = await context.bot.get_chat(winner_id)
        mention = f"<a href='tg://user?id={winner_id}'>@{chat.username or chat.first_name}</a>"
        message += f"{mention}: {win_count} lần chiến thắng\n"

    await update.message.reply_text(message, parse_mode="HTML")

# Reset bảng xếp hạng và trò chơi
async def reset(update, context):
    global players, win_counts
    reset_game()
    win_counts = {}  # Reset bảng xếp hạng
    await update.message.reply_text("🎮 Trò chơi đã được reset và bảng xếp hạng đã được làm mới.")

# Lệnh bắt đầu trò chơi
async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game()
    global in_game
    in_game = True

    await update.message.reply_text("🎮 Trò chơi bắt đầu!\n"
                                   "👉 Gõ /join để tham gia.\n"
                                   "👉 Gõ /begin để bắt đầu chơi.")

# Lệnh tham gia trò chơi
async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players
    user = update.effective_user
    if user.id not in players:
        players.append(user.id)
        await update.message.reply_text(
            f"✅ {user.first_name} đã tham gia... (Tổng {len(players)})")
    else:
        await update.message.reply_text("⚠️ Bạn đã tham gia rồi!")

# Lệnh bắt đầu vòng chơi
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
        f"✏️ {mention}, hãy nhập cụm từ đầu tiên để bắt đầu trò chơi! (Phải gồm 2 từ tiếng Việt)",
        parse_mode="HTML")
    await start_turn_timer(context)

# Lệnh chơi từ
async def play_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_phrase, current_player_index, used_phrases, players, in_game, waiting_for_phrase, turn_timeout_task

    if not in_game:
        return

    user = update.effective_user
    text = update.message.text.strip().lower()

    if user.id != players[current_player_index]:
        return

    if not is_vietnamese(text):
        await eliminate_player(update, context, reason="Phải dùng tiếng Việt (không dùng số hoặc tiếng Anh)")
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
            f"🔄 Lượt chơi tiếp theo\n"
            f"👉 Từ cần nói: [{current_word}]\n"
            f"👤 Người chơi: {mention}\n"
            f"⏳ Thời gian: 60 giây",
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
        await send_winner_message(update, context, winner_id)
        reset_game()
        return

    next_id = players[current_player_index]
    next_chat = await context.bot.get_chat(next_id)
    next_mention = f"<a href='tg://user?id={next_id}'>@{next_chat.username or next_chat.first_name}</a>"
    current_word = text.split()[-1]

    await update.message.reply_text(
        f"✅ Hợp lệ!\n\n"
        f"🔄 Lượt chơi tiếp theo\n"
        f"👉 Từ cần nói: [\u2003{current_word}\u2003]\n"
        f"👤 Người chơi: {next_mention}\n"
        f"⏳ Thời gian:  giây",
        parse_mode="HTML")
    await start_turn_timer(context)

# Loại người chơi
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
        await send_winner_message(update, context, winner_id)
        reset_game()
    else:
        await update.message.reply_text(
            f"Hiện còn lại {len(players)} người chơi.")
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

# Hàm bắt đầu hẹn giờ
async def start_turn_timer(context):
    global turn_timeout_task
    if turn_timeout_task:
        turn_timeout_task.cancel()

    turn_timeout_task = asyncio.create_task(turn_timeout(context))

# Hàm timeout
async def turn_timeout(context):
    await asyncio.sleep(60)
    if len(players) > 1:
        await eliminate_player(update, context, reason="Hết thời gian")

# Main entry point to set up the bot
async def main():
    app = ApplicationBuilder().token("YOUR_BOT_TOKEN").build()

    # Command Handlers
    app.add_handler(CommandHandler("start", start_game))
    app.add_handler(CommandHandler("join", join_game))
    app.add_handler(CommandHandler("begin", begin_game))
    app.add_handler(CommandHandler("win", show_stats))
    app.add_handler(CommandHandler("reset", reset))

    # Message Handler cho từ
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, play_word))

    # Chạy bot
    await app.run_polling()

# Khởi chạy bot
if __name__ == "__main__":
    asyncio.run(main()) 
