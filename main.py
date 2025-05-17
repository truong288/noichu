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

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game_state()
    global in_game
    in_game = True
    await update.message.reply_text(
        "╔══════════════════╗\n"
        "║   🎮 TRÒ CHƠI BẮT ĐẦU!   ║\n"
        "╚══════════════════╝\n"
        "👉 Gõ /join để tham gia\n"
        "👉 Gõ /begin để bắt đầu chơi"
    )

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players
    user = update.effective_user
    if not in_game:
        await update.message.reply_text(
            "╔══════════════════════╗\n"
            "║   ⚠️ TRÒ CHƠI CHƯA BẮT ĐẦU   ║\n"
            "╚══════════════════════╝\n"
            "👉 Gõ /startgame để bắt đầu"
        )
        return
    if user.id not in players:
        players.append(user.id)
        await update.message.reply_text(
            f"╔══════════════════════╗\n"
            f"║   ✅ {user.first_name} ĐÃ THAM GIA   ║\n"
            f"╚══════════════════════╝\n"
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
            "╚══════════════════════╝\n"
            "👉 Gõ /startgame để bắt đầu"
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

async def announce_next_turn(update, context):
    next_id = players[current_player_index]
    chat = await context.bot.get_chat(next_id)
    mention = f"<a href='tg://user?id={next_id}'>{chat.first_name}</a>"
    word = current_phrase.split()[-1]
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"╔════════════════════════╗\n"
             f"║   ✅ TỪ HIỆN TẠI: {word:<10} ║\n"
             f"╚════════════════════════╝\n"
             f"┌───────────────────────┐\n"
             f"│ 🔄 LƯỢT TIẾP THEO      │\n"
             f"├───────────────────────┤\n"
             f"│ 👉 Từ cần nói: 【{word}】 │\n"
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

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "╔══════════════════════╗\n"
        "║   🆘 HƯỚNG DẪN TRÒ CHƠI   ║\n"
        "╚══════════════════════╝\n"
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
    message = "╔══════════════════════╗\n"
    message += "║   🏆 BẢNG XẾP HẠNG   ║\n"
    message += "╚══════════════════════╝\n"
    for i, (name, count) in enumerate(ranking, 1):
        message += f"{i}. {name}: {count} lần thắng\n"
    await update.message.reply_text(message)

# ... (phần còn lại của các hàm giữ nguyên)

if __name__ == '__main__':
    TOKEN = "from telegram import Update
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

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game_state()
    global in_game
    in_game = True
    await update.message.reply_text(
        "╔══════════════════╗\n"
        "║   🎮 TRÒ CHƠI BẮT ĐẦU!   ║\n"
        "╚══════════════════╝\n"
        "👉 Gõ /join để tham gia\n"
        "👉 Gõ /begin để bắt đầu chơi"
    )

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players
    user = update.effective_user
    if not in_game:
        await update.message.reply_text(
            "╔══════════════════════╗\n"
            "║   ⚠️ TRÒ CHƠI CHƯA BẮT ĐẦU   ║\n"
            "╚══════════════════════╝\n"
            "👉 Gõ /startgame để bắt đầu"
        )
        return
    if user.id not in players:
        players.append(user.id)
        await update.message.reply_text(
            f"╔══════════════════════╗\n"
            f"║   ✅ {user.first_name} ĐÃ THAM GIA   ║\n"
            f"╚══════════════════════╝\n"
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
            "╚══════════════════════╝\n"
            "👉 Gõ /startgame để bắt đầu"
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

async def announce_next_turn(update, context):
    next_id = players[current_player_index]
    chat = await context.bot.get_chat(next_id)
    mention = f"<a href='tg://user?id={next_id}'>{chat.first_name}</a>"
    word = current_phrase.split()[-1]
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"╔════════════════════════╗\n"
             f"║   ✅ TỪ HIỆN TẠI: {word:<10} ║\n"
             f"╚════════════════════════╝\n"
             f"┌───────────────────────┐\n"
             f"│ 🔄 LƯỢT TIẾP THEO      │\n"
             f"├───────────────────────┤\n"
             f"│ 👉 Từ cần nói: 【{word}】 │\n"
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

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "╔══════════════════════╗\n"
        "║   🆘 HƯỚNG DẪN TRÒ CHƠI   ║\n"
        "╚══════════════════════╝\n"
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
    message = "╔══════════════════════╗\n"
    message += "║   🏆 BẢNG XẾP HẠNG   ║\n"
    message += "╚══════════════════════╝\n"
    for i, (name, count) in enumerate(ranking, 1):
        message += f"{i}. {name}: {count} lần thắng\n"
    await update.message.reply_text(message)

# ... (phần còn lại của các hàm giữ nguyên)

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
    app.run_polling()"
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
