from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from stay_alive import keep_alive
import asyncio
import re
import json
import os

keep_alive()

# Trạng thái trò chơi
players = []
current_phrase = ""
used_phrases = {}
current_player_index = 0
in_game = False
waiting_for_phrase = False
turn_timeout_task = None

# Từ cấm
BANNED_WORDS = {"đần", "bần", "ngu", "ngốc", "bò", "dốt", "nát", "chó", "địt", "mẹ", "mày", "má"}

# Thống kê
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
    await update.message.reply_text(
        "╔══════════════════════╗\n"
        "║   🔄 ĐÃ RESET TRÒ CHƠI   ║\n"
        "╚══════════════════════╝"
    )

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

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game_state()
    global in_game
    in_game = True
    await update.message.reply_text(
        "╔════════════════════════════╗\n"
        "║   🎮 TRÒ CHƠI NỐI TỪ BẮT ĐẦU!   ║\n"
        "╚════════════════════════════╝\n"
        "👉 Gõ /join để tham gia\n"
        "👉 Gõ /begin để bắt đầu khi đủ người\n\n"
        "📌 Luật chơi:\n"
        "- Mỗi cụm từ gồm 2 từ tiếng Việt\n"
        "- Nối đúng từ cuối của cụm trước\n"
        "- Không lặp lại cụm từ\n"
        "- Không dùng số/từ cấm\n"
        "- 60 giây/lượt"
    )

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players
    user = update.effective_user
    if not in_game:
        await update.message.reply_text(
            "╔══════════════════════╗\n"
            "║   ⚠️ TRÒ CHƠI CHƯA BẮT ĐẦU   ║\n"
            "╚══════════════════════╝"
        )
        return
    if user.id not in players:
        players.append(user.id)
        await update.message.reply_text(
            f"╔════════════════════════════╗\n"
            f"║   ✅ {user.first_name} ĐÃ THAM GIA   ║\n"
            f"╚════════════════════════════╝\n"
            f"👥 Tổng số người chơi: {len(players)}"
        )
    else:
        await update.message.reply_text(
            "╔══════════════════════╗\n"
            "║   ℹ️ BẠN ĐÃ THAM GIA RỒI   ║\n"
            "╚══════════════════════╝"
        )

async def begin_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global waiting_for_phrase
    if not in_game:
        await update.message.reply_text(
            "╔══════════════════════╗\n"
            "║   ⚠️ TRÒ CHƠI CHƯA BẮT ĐẦU   ║\n"
            "╚══════════════════════╝"
        )
        return
    if len(players) < 2:
        await update.message.reply_text(
            "╔══════════════════════╗\n"
            "║   ❌ CẦN ÍT NHẤT 2 NGƯỜI   ║\n"
            "╚══════════════════════╝"
        )
        return
    
    waiting_for_phrase = True
    user_id = players[current_player_index]
    chat = await context.bot.get_chat(user_id)
    mention = f"<a href='tg://user?id={user_id}'>{chat.first_name}</a>"
    await update.message.reply_text(
        f"╔════════════════════════════╗\n"
        f"║   ✏️ {mention.upper()}, NHẬP CỤM TỪ ĐẦU TIÊN   ║\n"
        f"╚════════════════════════════╝\n"
        "📝 Yêu cầu: 2 từ tiếng Việt, không số, không từ cấm",
        parse_mode="HTML"
    )
    await start_turn_timer(update, context)

async def play_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_phrase, current_player_index, used_phrases, players, in_game, waiting_for_phrase, turn_timeout_task
    if not in_game:
        return

    user = update.effective_user
    text = update.message.text.strip().lower()

    if user.id != players[current_player_index]:
        return

    if not is_vietnamese(text):
        await eliminate_player(update, context, "❌ Phải nhập đúng 2 từ tiếng Việt (không số/tiếng Anh)")
        return

    if contains_banned_words(text):
        await eliminate_player(update, context, "❌ Sử dụng từ không phù hợp")
        return

    if waiting_for_phrase:
        current_phrase = text
        used_phrases[text] = 1
        waiting_for_phrase = False
        current_player_index = (current_player_index + 1) % len(players)
        await update.message.reply_text(
            f"╔════════════════════════╗\n"
            f"║   ✅ TỪ BẮT ĐẦU: {text:<10} ║\n"
            f"╚════════════════════════╝"
        )
        await announce_next_turn(update, context)
        return

    if text.split()[0] != current_phrase.split()[-1]:
        await eliminate_player(update, context, f"❌ Từ đầu phải là: '{current_phrase.split()[-1]}'")
        return

    if used_phrases.get(text, 0) >= 1:
        await eliminate_player(update, context, "❌ Cụm từ này đã được dùng trước đó")
        return

    used_phrases[text] = 1
    current_phrase = text
    current_player_index = (current_player_index + 1) % len(players)

    if len(players) == 1:
        await announce_winner(update, context)
        return

    await update.message.reply_text(
        f"╔════════════════════════╗\n"
        f"║   ✅ HỢP LỆ!           ║\n"
        f"╚════════════════════════╝"
    )
    await announce_next_turn(update, context)

async def eliminate_player(update, context, reason):
    global players, current_player_index
    user = update.effective_user
    await update.message.reply_text(
        f"╔════════════════════════╗\n"
        f"║   💥 {user.first_name} BỊ LOẠI!   ║\n"
        f"╚════════════════════════╝\n"
        f"📌 Lý do: {reason}"
    )
    players.remove(user.id)
    if current_player_index >= len(players):
        current_player_index = 0
    if len(players) == 1:
        await announce_winner(update, context)
    else:
        await announce_next_turn(update, context)

async def announce_next_turn(update, context):
    next_id = players[current_player_index]
    chat = await context.bot.get_chat(next_id)
    mention = f"<a href='tg://user?id={next_id}'>{chat.first_name}</a>"
    word = current_phrase.split()[-1]
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"╔════════════════════════╗\n"
             f"║   🔄 LƯỢT TIẾP THEO    ║\n"
             f"╚════════════════════════╝\n"
             f"┌───────────────────────┐\n"
             f"│ 👉 Từ cần nối: 【{word}】 │\n"
             f"│ 👤 Người chơi: {mention:<15} │\n"
             f"│ ⏳ Thời gian: 60 giây   │\n"
             f"└───────────────────────┘",
        parse_mode="HTML"
    )
    await start_turn_timer(update, context)

async def announce_winner(update, context):
    winner_id = players[0]
    chat = await context.bot.get_chat(winner_id)
    name = chat.first_name
    mention = f"<a href='tg://user?id={winner_id}'>{name}</a>"
    stats[name] = stats.get(name, 0) + 1
    save_stats(stats)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"╔════════════════════════════╗\n"
             f"║   🏆 {mention.upper()} VÔ ĐỊCH!   ║\n"
             f"╚════════════════════════════╝\n"
             f"🎉 Số lần thắng: {stats[name]}",
        parse_mode="HTML"
    )
    reset_game_state()

async def start_turn_timer(update, context):
    global turn_timeout_task
    if turn_timeout_task:
        turn_timeout_task.cancel()
    turn_timeout_task = asyncio.create_task(turn_timer(update, context))

async def turn_timer(update, context):
    global players, current_player_index
    try:
        await asyncio.sleep(60)
        user_id = players[current_player_index]
        chat = await context.bot.get_chat(user_id)
        mention = f"<a href='tg://user?id={user_id}'>{chat.first_name}</a>"
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"╔════════════════════════╗\n"
                 f"║   ⏰ {mention} HẾT GIỜ!   ║\n"
                 f"╚════════════════════════╝",
            parse_mode="HTML"
        )
        players.remove(user_id)
        if len(players) == 1:
            await announce_winner(update, context)
        else:
            if current_player_index >= len(players):
                current_player_index = 0
            await announce_next_turn(update, context)
    except asyncio.CancelledError:
        pass

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "╔════════════════════════════╗\n"
        "║   🆘 HƯỚNG DẪN TRÒ CHƠI   ║\n"
        "╚════════════════════════════╝\n"
        "🎮 Lệnh trò chơi:\n"
        "👉 /startgame - Bắt đầu trò chơi mới\n"
        "👉 /join - Tham gia trò chơi\n"
        "👉 /begin - Bắt đầu khi đủ người\n\n"
        "📊 Lệnh thống kê:\n"
        "👉 /win - Xem bảng xếp hạng\n"
        "👉 /reset - Reset trò chơi\n\n"
        "📌 Luật chơi:\n"
        "- Mỗi cụm từ gồm 2 từ tiếng Việt\n"
        "- Nối đúng từ cuối của cụm trước\n"
        "- Không lặp lại cụm từ\n"
        "- Không dùng số/từ cấm\n"
        "- 60 giây/lượt"
    )

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not stats:
        await update.message.reply_text(
            "╔══════════════════════╗\n"
            "║   📊 CHƯA CÓ AI THẮNG   ║\n"
            "╚══════════════════════╝"
        )
        return
    
    ranking = sorted(stats.items(), key=lambda x: x[1], reverse=True)
    message = "╔════════════════════════════╗\n"
    message += "║   🏆 BẢNG XẾP HẠNG        ║\n"
    message += "╚════════════════════════════╝\n"
    for i, (name, count) in enumerate(ranking, 1):
        message += f"{i}. {name}: {count} lần thắng\n"
    await update.message.reply_text(message)

if __name__ == '__main__':
    TOKEN = "7670306744:AAHIKDeed6h3prNCmkFhFydwrHkxJB5HM6g"
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("startgame", start_game))
    app.add_handler(CommandHandler("join", join_game))
    app.add_handler(CommandHandler("begin", begin_game))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("win", show_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, play_word))

    print("🤖 Bot đã sẵn sàng hoạt động...")
    app.run_polling()
