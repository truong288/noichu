import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from stay_alive import keep_alive
import asyncio
import re

# Cài API OpenAI
openai.api_key = "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 "  # Thay bằng key của bạn

keep_alive()

# Game state
players = []
current_phrase = ""
used_phrases = {}
current_player_index = 0
in_game = False
waiting_for_phrase = False
turn_timeout_task = None
win_counts = {}

# Sử dụng ChatGPT để kiểm tra nghĩa
async def check_meaning(previous_phrase, current_phrase):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # Dùng GPT-4 nếu có thể
            messages=[
                {"role": "system", "content": "Bạn là một giáo viên nghiêm khắc về ngữ nghĩa tiếng Việt. Nhiệm vụ của bạn là kiểm tra xem hai cụm từ được nối lại có hợp lý và có nghĩa không."},
                {"role": "user", "content": f"""Hãy đánh giá cụm từ nối sau: '{previous_phrase}' -> {current_phrase}' có hợp lý và có nghĩa trong tiếng Việt không?
Chỉ trả lời một trong hai dòng sau:

- Hợp lý và có nghĩa.
- Không hợp lý hoặc không có nghĩa."""}
            ],
            temperature=0,
            max_tokens=10
        )
        result = response.choices[0].message['content'].strip()
        return result
    except Exception as e:
        return f"Đã có lỗi khi gọi API: {str(e)}"

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

    if not is_vietnamese(text):
        await eliminate_player(update, context, reason="Không dùng tiếng Việt")
        return

    if len(text.split()) != 2:
        await eliminate_player(update, context, reason="Cụm từ phải có đúng 2 từ. Bạn quá kém!")
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
            f"✅ Từ bắt đầu là: '{text}'. {mention}, hãy nối với từ '{text.split()[-1]}'",
            parse_mode="HTML")
        await start_turn_timer(context)
        return

    # Kiểm tra nghĩa với AI
    result = await check_meaning(current_phrase, text)
    print(f"AI Kiểm Tra: {result}")  # Để debug kết quả trả về từ OpenAI
    if result.lower().startswith("không hợp lý") or "không có nghĩa" in result.lower():
        await eliminate_player(update, context, reason="Cụm từ không hợp lý hoặc không có nghĩa. Bạn quá kém!")
        return

    if text.split()[0] != current_phrase.split()[-1]:
        await eliminate_player(update, context, reason="Không đúng từ nối. Bạn quá kém!")
        return

    if used_phrases.get(text, 0) >= 1:
        await eliminate_player(update, context, reason="Cụm từ đã bị sử dụng. Bạn quá kém!")
        return

    used_phrases[text] = 1
    current_phrase = text
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
    next_mention = f"<a href='tg://user?id={next_id}'>@{next_chat.username or next_chat.first_name}</a>"

    await update.message.reply_text(
        f"✅ Hợp lệ! \u2003\u2003 Nối tiếp từ: '{text.split()[-1]}'. Tới lượt bạn! {next_mention}",
        parse_mode="HTML")
    await start_turn_timer(context)


async def eliminate_player(update, context, reason):
    global players, current_player_index, current_phrase
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
            win_counts[winner_id] = win_counts.get(winner_id, 0) + 1
            winner_chat = await context.bot.get_chat(winner_id)
            mention = f"<a href='tg://user?id={winner_id}'>@{winner_chat.username or winner_chat.first_name}</a>"
            await context.bot.send_message(
                chat_id=context._chat_id,
                text=f"🏆 {mention} Vô Địch Nối CHỮ! Tổng chiến thắng: {win_counts[winner_id]}",
                parse_mode="HTML")
            reset_game()
            return

        if current_player_index >= len(players):
            current_player_index = 0

        await start_turn_timer(context)

    except asyncio.CancelledError:
        pass


async def start_turn_timer(context):
    global turn_timeout_task
    if turn_timeout_task:
        turn_timeout_task.cancel()
    turn_timeout_task = asyncio.create_task(turn_timer(context))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/startgame - bắt đầu trò chơi\n/join - tham gia\n/begin - người đầu tiên nhập cụm từ\n/win - Xếp Hạng\n/help - hướng dẫn"
    )
    
async def win_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not win_counts:
        await update.message.reply_text("Chưa có ai chiến thắng trong trò chơi này cả!")
        return

    sorted_winners = sorted(win_counts.items(), key=lambda x: x[1], reverse=True)
    leaderboard = "🏆 BẢNG XẾP HẠNG CHIẾN THẮNG:\n"
    for idx, (user_id, count) in enumerate(sorted_winners, start=1):
        chat = await context.bot.get_chat(user_id)
        name = chat.username or chat.first_name
        leaderboard += f"{idx}. {name}: {count} lần thắng\n"

    await update.message.reply_text(leaderboard)

if __name__ == '__main__':
    TOKEN = "7670306744:AAHIKDeed6h3prNCmkFhFydwrHkxJB5HM6g"  # Thay bằng token bot của bạn
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("startgame", start_game))
    app.add_handler(CommandHandler("join", join_game))
    app.add_handler(CommandHandler("begin", begin_game))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("win", win_leaderboard))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, play_word))

    print("Bot is running...")
    app.run_polling()
