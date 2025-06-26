from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from stay_alive import keep_alive
import asyncio
import re
import json
import os
from datetime import datetime
import openpyxl
from openpyxl.styles import Font

keep_alive()

# ==== Trạng thái game ====
players = []
player_names = {}
current_phrase = ""
used_phrases = {}
current_player_index = 0
in_game = False
waiting_for_phrase = False
turn_timeout_task = None
game_start_time = None
all_participants = set()  # Lưu tất cả người từng tham gia

# ==== Từ cấm ====
BANNED_WORDS = {
    "đần", "bần", "ngu", "ngốc", "bò", "dốt", "nát", "chó", "địt", "mẹ", "mày",
    "chi", "mô", "răng", "rứa", "má"
}

# ==== File thống kê ====
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
    global players, player_names, current_phrase, used_phrases, current_player_index
    global in_game, waiting_for_phrase, turn_timeout_task, game_start_time
    players.clear()
    player_names.clear()
    used_phrases.clear()
    current_phrase = ""
    current_player_index = 0
    in_game = False
    waiting_for_phrase = False
    game_start_time = None
    if turn_timeout_task:
        turn_timeout_task.cancel()

def has_vietnamese_diacritics(text):
    return re.search(r"[àáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệ"
                     r"ìíỉĩịòóỏõọôồốổỗộơờớởỡợ"
                     r"ùúủũụưừứửữựỳýỷỹỵđ]", text.lower()) is not None

def is_vietnamese(text):
    words = text.strip().lower().split()
    return (
        len(words) == 2 and
        all(len(word) >= 2 for word in words) and
        not re.search(r'[0-9]', text) and
        not (re.search(r'[a-zA-Z]', text) and not has_vietnamese_diacritics(text)) and
        has_vietnamese_diacritics(text)
    )

def contains_banned_words(text):
    return any(word in BANNED_WORDS for word in text.lower().split())

def get_player_name(user):
    if user.id not in player_names:
        name = user.first_name
        if user.last_name:
            name += f" {user.last_name}"
        player_names[user.id] = name
    return player_names[user.id]

# ==== Lệnh game ====

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game_state()
    global in_game, game_start_time
    in_game = True
    game_start_time = datetime.now().strftime("%H:%M:%S")
    await update.message.reply_text(
        "🎮 Trò chơi bắt đầu!\n👉 /join để tham gia.\n👉 /begin để bắt đầu khi đủ người."
    )

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in players:
        players.append(user.id)
        all_participants.add(user.id)
        get_player_name(user)
        await update.message.reply_text(f"✅ {get_player_name(user)} đã tham gia! (Tổng: {len(players)} ng)")
    else:
        await update.message.reply_text("⚠️ Bạn đã tham gia rồi!")

async def begin_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global waiting_for_phrase, current_player_index
    if len(players) < 2:
        await update.message.reply_text("❗ Cần ít nhất 2 người để bắt đầu!")
        return

    waiting_for_phrase = True
    current_player_index = 0
    user = await context.bot.get_chat(players[current_player_index])
    await update.message.reply_text(
        f"✏️ {get_player_name(user)}, hãy nhập cụm từ bắt đầu (2 từ, có dấu):\n⏰ 60 giây"
    )
    await start_turn_timer(context)

# ==== Luật chơi ====

async def play_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_phrase, current_player_index, used_phrases, waiting_for_phrase

    user = update.effective_user

    # Nếu có game đang chơi và người nhập không đến lượt
    if in_game:
        if user.id not in players:
            await update.message.reply_text("⚠️ Trò chơi đang diễn ra, bạn không được phép chơi.")
            return
        if user.id != players[current_player_index]:
            await eliminate_player(update, context, "❌ Bạn nhập sai lượt!")
            return

    text = update.message.text.strip().lower()

    if not is_vietnamese(text):
        await eliminate_player(update, context, "❌ Cụm từ không hợp lệ (2 từ có dấu)")
        return
    if contains_banned_words(text):
        await eliminate_player(update, context, "❌ Cụm từ chứa từ cấm")
        return

    if waiting_for_phrase:
        current_phrase = text
        used_phrases[text] = 1
        waiting_for_phrase = False
        await process_valid_word(update, context, text, True)
        return

    if text.split()[0] != current_phrase.split()[-1]:
        await eliminate_player(update, context, f"❌ Từ đầu phải là: 『{current_phrase.split()[-1]}』")
        return
    if text in used_phrases:
        await eliminate_player(update, context, "❌ Cụm từ đã được dùng")
        return

    used_phrases[text] = 1
    current_phrase = text
    await process_valid_word(update, context, text)

async def process_valid_word(update, context, text, is_first=False):
    global current_player_index

    if turn_timeout_task:
        turn_timeout_task.cancel()

    msg = f"🎯 Từ bắt đầu: 『{text}』\n" if is_first else f"✅ {get_player_name(update.effective_user)} đã nối thành công!\n"

    current_player_index = (current_player_index + 1) % len(players)

    if len(players) == 1:
        await announce_winner(update, context)
        return

    current_word = current_phrase.split()[-1]
    next_user = await context.bot.get_chat(players[current_player_index])
    await update.message.reply_text(
        f"{msg}🔄 Từ cần nối: 『{current_word}』\n👤 Người chơi: {get_player_name(next_user)}\n⏳ 60 giây"
    )
    await start_turn_timer(context)

async def eliminate_player(update, context, reason):
    global players, current_player_index

    user = update.effective_user
    name = get_player_name(user)
    idx = players.index(user.id)

    if turn_timeout_task:
        turn_timeout_task.cancel()

    await update.message.reply_text(f"❌ {name} bị loại! {reason}")
    players.remove(user.id)

    if len(players) == 1:
        await announce_winner(update, context)
        return

    if idx < current_player_index:
        current_player_index -= 1
    elif idx == current_player_index and current_player_index >= len(players):
        current_player_index = 0

    current_word = current_phrase.split()[-1]
    next_user = await context.bot.get_chat(players[current_player_index])
    await update.message.reply_text(
        f"🔄 Từ cần nối: 『{current_word}』\n👤 Người chơi: {get_player_name(next_user)}\n⏳ 60 giây"
    )
    await start_turn_timer(context)

async def announce_winner(update, context):
    if not players:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="🏁 Không có người chiến thắng.")
        reset_game_state()
        return

    winner_id = players[0]
    winner = await context.bot.get_chat(winner_id)
    name = get_player_name(winner)
    stats[name] = stats.get(name, 0) + 1
    save_stats(stats)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🏆 {name} chiến thắng!\n🥇 Số lần: {stats[name]}"
    )
    reset_game_state()

# ==== Timer ====

async def start_turn_timer(context):
    global turn_timeout_task
    if turn_timeout_task:
        turn_timeout_task.cancel()
    turn_timeout_task = asyncio.create_task(turn_timer(context))

async def turn_timer(context):
    global players, current_player_index

    try:
        await asyncio.sleep(60)
        if current_player_index >= len(players):
            return
        user_id = players[current_player_index]
        user = await context.bot.get_chat(user_id)
        await context.bot.send_message(chat_id=context._chat_id, text=f"⏰ {get_player_name(user)} hết giờ và bị loại!")
        players.remove(user_id)
        if len(players) == 1:
            await announce_winner(None, context)
            return
        if current_player_index >= len(players):
            current_player_index = 0
        current_word = current_phrase.split()[-1]
        next_user = await context.bot.get_chat(players[current_player_index])
        await context.bot.send_message(
            chat_id=context._chat_id,
            text=f"🔄 Từ cần nối: 『{current_word}』\n👤 Người chơi: {get_player_name(next_user)}\n⏳ 60 giây"
        )
        await start_turn_timer(context)

    except asyncio.CancelledError:
        pass

# ==== Lệnh khác ====

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not stats:
        await update.message.reply_text("📊 Chưa có ai chiến thắng.")
        return
    rank = sorted(stats.items(), key=lambda x: x[1], reverse=True)
    msg = "🏆 BẢNG XẾP HẠNG 🏆\n\n"
    for i, (name, count) in enumerate(rank[:10], 1):
        msg += f"{i}. {name}: {count} lần thắng\n"
    await update.message.reply_text(msg)

async def export_players_to_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not all_participants:
        await update.message.reply_text("❌ Chưa có người chơi nào.")
        return

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Nguoi choi"
    headers = ["STT", "Tên người chơi", "Telegram ID"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for idx, user_id in enumerate(all_participants, 1):
        name = player_names.get(user_id, f"User {user_id}")
        ws.append([idx, name, user_id])

    file_name = "nguoi_choi.xlsx"
    wb.save(file_name)
    await context.bot.send_document(chat_id=update.effective_chat.id, document=open(file_name, "rb"))
    os.remove(file_name)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game_state()
    global stats
    stats = {}
    save_stats(stats)
    await update.message.reply_text("✅ Game và thống kê đã được reset.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 HƯỚNG DẪN\n\n"
        "🔹 /startgame - Bắt đầu game\n"
        "🔹 /join - Tham gia\n"
        "🔹 /begin - Bắt đầu chơi\n"
        "🔹 /export - Xuất danh sách người tham gia\n"
        "🔹 /win - Xem bảng xếp hạng\n"
        "🔹 /reset - Reset game\n"
        "🔹 /help - Xem hướng dẫn\n\n"
        "📌 Luật:\n"
        "- Cụm từ 2 từ tiếng Việt có dấu\n"
        "- Không lặp lại cụm từ\n"
        "- Không chứa từ cấm\n"
        "- Hết 60s sẽ bị loại\n"
        "- Sai lượt sẽ bị loại"
    )

# ==== Khởi động ====

if __name__ == '__main__':
    TOKEN = "7670306744:AAHIKDeed6h3prNCmkFhFydwrHkxJB5HM6g"  # 👉 Thay bằng token thật
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("startgame", start_game))
    app.add_handler(CommandHandler("join", join_game))
    app.add_handler(CommandHandler("begin", begin_game))
    app.add_handler(CommandHandler("win", show_stats))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("export", export_players_to_excel))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, play_word))

    print("🤖 Bot đang chạy...")
    app.run_polling()
