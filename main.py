import os
import re
import json
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import openpyxl
from openpyxl.styles import Font

# File lưu thống kê người thắng
STATS_FILE = "winners.json"

# Từ cấm không được chứa trong cụm từ
BANNED_WORDS = {
    "đần", "bần", "ngu", "ngốc", "bò", "dốt", "nát", "chó", "địt", "mẹ", "mày",
    "chi", "mô", "răng", "rứa", "má"
}

# Biến toàn cục quản lý trạng thái game
players = []  # Danh sách user_id người chơi đang trong game
player_names = {}  # user_id -> tên hiển thị
player_usernames = {}  # user_id -> @username (nếu có)
player_join_times = {}  # user_id -> thời gian tham gia (chuỗi)
all_participants = set()  # Tất cả user_id đã tham gia kể từ đầu phiên
used_phrases = set()  # Các cụm từ đã dùng
current_phrase = ""  # Cụm từ hiện tại để người kế tiếp nối
current_player_index = 0  # Vị trí lượt chơi trong players
in_game = False  # Cờ game đang chạy
waiting_for_phrase = False  # Đang đợi nhập cụm từ đầu tiên
turn_timeout_task = None  # Task hẹn giờ hết lượt

# Thống kê số lần thắng
def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_stats(data):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

stats = load_stats()

# --- Hàm reset trạng thái game ---
def reset_game_state():
    global players, player_names, player_usernames, player_join_times
    global all_participants, used_phrases, current_phrase, current_player_index
    global in_game, waiting_for_phrase, turn_timeout_task

    players.clear()
    player_names.clear()
    player_usernames.clear()
    player_join_times.clear()
    all_participants.clear()
    used_phrases.clear()
    current_phrase = ""
    current_player_index = 0
    in_game = False
    waiting_for_phrase = False
    if turn_timeout_task:
        turn_timeout_task.cancel()

# --- Kiểm tra cụm từ hợp lệ ---
def has_vietnamese_diacritics(text):
    return re.search(r"[àáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệ"
                     r"ìíỉĩịòóỏõọôồốổỗộơờớởỡợ"
                     r"ùúủũụưừứửữựỳýỷỹỵđ]", text.lower()) is not None

def is_vietnamese_phrase(text):
    words = text.strip().split()
    if len(words) != 2:
        return False
    # Mỗi từ >= 2 ký tự
    if any(len(w) < 2 for w in words):
        return False
    # Có dấu tiếng Việt
    if not has_vietnamese_diacritics(text):
        return False
    # Không chứa số
    if re.search(r'\d', text):
        return False
    # Không phải tiếng Anh không dấu
    if re.search(r'[a-zA-Z]', text) and not has_vietnamese_diacritics(text):
        return False
    return True

def contains_banned_words(text):
    text_lower = text.lower()
    for w in BANNED_WORDS:
        if w in text_lower:
            return True
    return False

# --- Lấy tên hiển thị ---
def get_player_name(user):
    if user.id not in player_names:
        name = user.first_name or ""
        if user.last_name:
            name += " " + user.last_name
        player_names[user.id] = name
    return player_names[user.id]

# --- Lấy username với dấu @ ---
def get_player_username(user):
    if user.id not in player_usernames:
        player_usernames[user.id] = f"@{user.username}" if user.username else ""
    return player_usernames[user.id]

# --- Lệnh bắt đầu game ---
async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global in_game
    reset_game_state()
    in_game = True
    await update.message.reply_text(
        "🎮 Game đã bắt đầu! Mời mọi người tham gia bằng lệnh /join.\n"
        "Khi đủ người, dùng /begin để bắt đầu chơi."
    )

# --- Lệnh tham gia ---
async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not in_game:
        await update.message.reply_text("❌ Chưa có game nào đang chạy. Dùng /startgame để bắt đầu.")
        return
    user = update.effective_user
    if user.id in players:
        await update.message.reply_text("⚠️ Bạn đã tham gia rồi!")
        return
    players.append(user.id)
    all_participants.add(user.id)
    get_player_name(user)
    get_player_username(user)
    player_join_times[user.id] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await update.message.reply_text(f"✅ {get_player_name(user)} đã tham gia! Tổng: {len(players)} người.")

# --- Lệnh bắt đầu chơi ---
async def begin_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global waiting_for_phrase, current_player_index

    if not in_game:
        await update.message.reply_text("❌ Chưa có game nào đang chạy. Dùng /startgame để bắt đầu.")
        return

    if len(players) < 2:
        await update.message.reply_text("❗ Cần ít nhất 2 người chơi để bắt đầu.")
        return

    waiting_for_phrase = True
    current_player_index = 0
    first_player_id = players[current_player_index]
    first_player = await context.bot.get_chat(first_player_id)
    await update.message.reply_text(
        f"📝 {get_player_name(first_player)}, hãy nhập cụm từ bắt đầu (2 từ tiếng Việt có dấu).\n⏰ Bạn có 60 giây."
    )
    await start_turn_timer(context, update.effective_chat.id)

# --- Hàm xử lý khi người chơi nhập từ ---
async def play_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_phrase, current_player_index, waiting_for_phrase, used_phrases, players

    if not in_game:
        return

    user = update.effective_user
    text = update.message.text.strip().lower()

    if user.id not in players:
        await update.message.reply_text("⚠️ Bạn chưa tham gia hoặc đã bị loại.")
        return

    # Kiểm tra lượt chơi
    if user.id != players[current_player_index]:
        await update.message.reply_text("❌ Chưa đến lượt bạn.")
        return

    # Kiểm tra cụm từ hợp lệ
    if not is_vietnamese_phrase(text):
        await eliminate_player(update, context, "Cụm từ không hợp lệ (phải 2 từ tiếng Việt có dấu).")
        return

    if contains_banned_words(text):
        await eliminate_player(update, context, "Cụm từ chứa từ cấm.")
        return

    if waiting_for_phrase:
        # Cụm từ đầu tiên
        current_phrase = text
        used_phrases.add(text)
        waiting_for_phrase = False
        await next_turn(update, context)
        return

    # Kiểm tra nối từ
    if text.split()[0] != current_phrase.split()[-1]:
        await eliminate_player(update, context, f"Từ đầu tiên phải là '{current_phrase.split()[-1]}'.")
        return

    # Kiểm tra lặp từ
    if text in used_phrases:
        await eliminate_player(update, context, "Cụm từ đã được dùng.")
        return

    used_phrases.add(text)
    current_phrase = text
    await next_turn(update, context)

# --- Xử lý chuyển lượt ---
async def next_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_player_index, players, current_phrase, turn_timeout_task

    if turn_timeout_task:
        turn_timeout_task.cancel()

    # Kiểm tra kết thúc
    if len(players) == 1:
        await announce_winner(update, context)
        return

    current_player_index = (current_player_index + 1) % len(players)
    next_player_id = players[current_player_index]
    next_player = await context.bot.get_chat(next_player_id)
    await update.message.reply_text(
        f"🔄 Từ cần nối: 『{current_phrase.split()[-1]}』\n"
        f"👤 Lượt của {get_player_name(next_player)} (@{next_player.username or 'Không có username'})\n"
        "⏰ Bạn có 60 giây."
    )
    await start_turn_timer(context, update.effective_chat.id)

# --- Loại người chơi sai luật hoặc hết thời gian ---
async def eliminate_player(update: Update, context: ContextTypes.DEFAULT_TYPE, reason: str):
    global players, current_player_index, turn_timeout_task

    user = update.effective_user
    name = get_player_name(user)
    await update.message.reply_text(f"❌ {name} bị loại! Lý do: {reason}")

    if turn_timeout_task:
        turn_timeout_task.cancel()

    # Xóa người chơi khỏi danh sách
    idx = players.index(user.id)
    players.remove(user.id)

    # Điều chỉnh chỉ số lượt
    if len(players) == 1:
        await announce_winner(update, context)
        return

    if idx < current_player_index:
        current_player_index -= 1
    elif idx == current_player_index and current_player_index >= len(players):
        current_player_index = 0

    next_player_id = players[current_player_index]
    next_player = await context.bot.get_chat(next_player_id)

    await update.message.reply_text(
        f"🔄 Từ cần nối: 『{current_phrase.split()[-1]}』\n"
        f"👤 Lượt của {get_player_name(next_player)} (@{next_player.username or 'Không có username'})\n"
        "⏰ Bạn có 60 giây."
    )
    await start_turn_timer(context, update.effective_chat.id)

# --- Thông báo người thắng ---
async def announce_winner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players, stats

    if len(players) == 0:
        await context.bot.send_message(update.effective_chat.id, "🏁 Không có người thắng cuộc.")
        reset_game_state()
        return

    winner_id = players[0]
    winner = await context.bot.get_chat(winner_id)
    name = get_player_name(winner)

    stats[name] = stats.get(name, 0) + 1
    save_stats(stats)

    await context.bot.send_message(
        update.effective_chat.id,
        f"🏆 {name} đã chiến thắng!\n🥇 Số lần thắng: {stats[name]}"
    )
    reset_game_state()

# --- Hẹn giờ hết lượt ---
async def start_turn_timer(context, chat_id):
    global turn_timeout_task

    if turn_timeout_task:
        turn_timeout_task.cancel()

    turn_timeout_task = asyncio.create_task(turn_timer(context, chat_id))

async def turn_timer(context, chat_id):
    global players, current_player_index, turn_timeout_task

    try:
        await asyncio.sleep(60)

        if len(players) == 0:
            return

        timed_out_player_id = players[current_player_index]
        timed_out_player = await context.bot.get_chat(timed_out_player_id)
        await context.bot.send_message(chat_id, f"⏰ {get_player_name(timed_out_player)} hết thời gian và bị loại!")

        players.remove(timed_out_player_id)

        if len(players) == 1:
            await announce_winner(None, context)
            return

        if current_player_index >= len(players):
            current_player_index = 0

        next_player_id = players[current_player_index]
        next_player = await context.bot.get_chat(next_player_id)
        await context.bot.send_message(
            chat_id,
            f"🔄 Từ cần nối: 『{current_phrase.split()[-1]}』\n"
            f"👤 Lượt của {get_player_name(next_player)} (@{next_player.username or 'Không có username'})\n"
            "⏰ Bạn có 60 giây."
        )
        await start_turn_timer(context, chat_id)

    except asyncio.CancelledError:
        pass

# --- Lệnh xem bảng xếp hạng ---
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not stats:
        await update.message.reply_text("📊 Chưa có ai chiến thắng lần nào.")
        return

    rank = sorted(stats.items(), key=lambda x: x[1], reverse=True)
    msg = "🏆 BẢNG XẾP HẠNG 🏆\n\n"
    for i, (name, count) in enumerate(rank[:10], 1):
        msg += f"{i}. {name}: {count} lần thắng\n"
    await update.message.reply_text(msg)

# --- Lệnh xuất danh sách người chơi ra file Excel ---
async def export_players_to_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not all_participants:
        await update.message.reply_text("❌ Chưa có người chơi nào tham gia.")
        return

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "DanhSachNguoiChoi"

    headers = ["STT", "Tên người chơi", "Username", "Telegram ID", "Thời gian tham gia"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for idx, user_id in enumerate(all_participants, 1):
        name = player_names.get(user_id, f"User {user_id}")
        username = player_usernames.get(user_id, "")
        join_time = player_join_times.get(user_id, "N/A")
        ws.append([idx, name, username, user_id, join_time])

    file_path = "nguoi_choi.xlsx"
    wb.save(file_path)
    await context.bot.send_document(update.effective_chat.id, document=open(file_path, "rb"))
    os.remove(file_path)

# --- Lệnh reset toàn bộ game và thống kê ---
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stats
    reset_game_state()
    stats = {}
    save_stats(stats)
    await update.message.reply_text("✅ Đã reset game và bảng thống kê.")

# --- Lệnh help ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 HƯỚNG DẪN TRÒ CHƠI\n\n"
        "/startgame - Bắt đầu game mới.\n"
        "/join - Tham gia game.\n"
        "/begin - Bắt đầu chơi khi đủ người.\n"
        "/win - Bảng xếp hạng.\n"
        "/help - Xem hướng dẫn.\n\n"
        "📌 Luật chơi:\n"
        "- Nhập cụm từ 2 từ.\n"
        "- Không được dùng lại cụm từ\n"
        "- Không chứa từ cấm\n"
        "- Hết 60 giây bị loại\n"
        "- Sai lượt bị loại"
    )

# --- Khởi chạy bot ---
if __name__ == '__main__':
    TOKEN = "7670306744:AAHIKDeed6h3prNCmkFhFydwrHkxJB5HM6g" # 
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("startgame", start_game))
    app.add_handler(CommandHandler("join", join_game))
    app.add_handler(CommandHandler("begin", begin_game))
    app.add_handler(CommandHandler("win", show_stats))
    app.add_handler(CommandHandler("export", export_players_to_excel))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, play_word))

    print("🤖 Bot đã sẵn sàng và đang chạy...")
    app.run_polling()

