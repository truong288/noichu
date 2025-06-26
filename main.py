import os
import re
import json
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import openpyxl
from openpyxl.styles import Font
from stay_alive import keep_alive

# Giữ bot luôn hoạt động
keep_alive()

# ==== Cấu hình ban đầu ====
TOKEN = "7670306744:AAHIKDeed6h3prNCmkFhFydwrHkxJB5HM6g"  # Thay bằng token thật
STATS_FILE = "winners.json"
BANNED_WORDS = {
    "đần", "bần", "ngu", "ngốc", "bò", "dốt", "nát", "chó", "địt", "mẹ", "mày",
    "chi", "mô", "răng", "rứa", "má", "cứt"
}

# ==== Biến toàn cục ====
players = []                # user_id của người chơi đang chơi
player_names = {}          # user_id -> tên hiển thị
player_usernames = {}      # user_id -> @username (nếu có)
player_join_times = {}     # user_id -> thời gian /join
all_participants = set()   # tất cả user đã join ít nhất 1 lần
used_phrases = set()       # cụm từ đã dùng
current_phrase = ""        # cụm từ hiện tại
current_player_index = 0
in_game = False
waiting_for_phrase = False
turn_timeout_task = None

# Thống kê vòng thắng
def load_stats():
    return json.load(open(STATS_FILE, "r", encoding="utf-8")) if os.path.exists(STATS_FILE) else {}
def save_stats(d): json.dump(d, open(STATS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
stats = load_stats()

# ==== Hàm reset trạng thái game ====
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

# ==== Hàm kiểm tra tiếng Việt hợp lệ ====
def has_vietnamese_diacritics(text):
    return bool(re.search(r"[àáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]", text))

def is_valid_phrase(text):
    text = text.strip().lower()
    words = text.split()
    if len(words) != 2: return False
    if any(len(w) < 2 for w in words): return False
    if any(ch.isdigit() for ch in text): return False
    # Không phải tiếng Anh không dấu
    if re.fullmatch(r"[a-z ]+", text) and not has_vietnamese_diacritics(text): return False
    if not has_vietnamese_diacritics(text): return False
    return True

def contains_banned(text):
    return any(w in BANNED_WORDS for w in text.lower().split())

def get_player_name(user):
    if user.id not in player_names:
        player_names[user.id] = (user.first_name or "") + (f" {user.last_name}" if user.last_name else "")
    return player_names[user.id]

def get_player_username(user):
    if user.id not in player_usernames:
        player_usernames[user.id] = f"@{user.username}" if user.username else ""
    return player_usernames[user.id]

# ==== Bot command handlers ====

async def start_game(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    reset_game_state()
    global in_game
    in_game = True
    await update.message.reply_text(
        "🎮 Game mới đã bắt đầu! Gõ /join để tham gia.\nGõ /begin khi đã đủ người."
    )

async def join_game(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not in_game:
        await update.message.reply_text("❌ Chưa có game nào. Gõ /startgame để khởi tạo.")
        return
    u = update.effective_user
    if u.id in players:
        await update.message.reply_text("⚠️ Bạn đã tham gia rồi.")
    else:
        players.append(u.id)
        all_participants.add(u.id)
        get_player_name(u)
        get_player_username(u)
        player_join_times[u.id] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await update.message.reply_text(f"✅ {get_player_name(u)} đã tham gia! Tổng: {len(players)} người.")

async def begin_game(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global waiting_for_phrase, current_player_index
    if not in_game:
        await update.message.reply_text("❌ Chưa có game nào đang chạy.")
        return
    if len(players) < 2:
        await update.message.reply_text("❗ Cần ít nhất 2 người để bắt đầu!")
        return
    waiting_for_phrase = True
    current_player_index = 0
    u = await ctx.bot.get_chat(players[0])
    await update.message.reply_text(f"✏️ {get_player_name(u)}, hãy nhập cụm từ đầu tiên (2 từ có dấu). Bạn có 60 giây.")
    await start_turn_timer(ctx, update.effective_chat.id)

async def play_word(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global current_phrase, current_player_index, waiting_for_phrase
    if not in_game: return
    u = update.effective_user
    if u.id not in players:
        await update.message.reply_text("⚠️ Bạn chưa tham gia hoặc đã bị loại!")
        return
    if u.id != players[current_player_index]:
        await update.message.reply_text("❌ Chưa đến lượt bạn.")
        return
    text = update.message.text.strip().lower()
    if not is_valid_phrase(text):
        return await eliminate_player(update, ctx, "Cụm từ không hợp lệ! (2 từ tiếng Việt có dấu).")
    if contains_banned(text):
        return await eliminate_player(update, ctx, "Cụm từ chứa từ cấm.")
    if waiting_for_phrase:
        current_phrase = text
        used_phrases.add(text)
        waiting_for_phrase = False
        return await next_turn(update, ctx)
    if text.split()[0] != current_phrase.split()[-1]:
        return await eliminate_player(update, ctx, f"Phải bắt đầu bằng '{current_phrase.split()[-1]}'.")
    if text in used_phrases:
        return await eliminate_player(update, ctx, "Cụm từ đã được dùng.")
    used_phrases.add(text)
    current_phrase = text
    await next_turn(update, ctx)

async def next_turn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global current_player_index, turn_timeout_task
    if turn_timeout_task:
        turn_timeout_task.cancel()
    if len(players) == 1:
        return await announce_winner(update, ctx)
    current_player_index = (current_player_index + 1) % len(players)
    nxt = await ctx.bot.get_chat(players[current_player_index])
    await update.message.reply_text(
        f"🔄 Từ cần nối: 『{current_phrase.split()[-1]}』\n"
        f"👤 Lượt: {get_player_name(nxt)} {get_player_username(nxt)}\n⏰ 60 giây"
    )
    await start_turn_timer(ctx, update.effective_chat.id)

async def eliminate_player(update: Update, ctx: ContextTypes.DEFAULT_TYPE, reason: str):
    global current_player_index, turn_timeout_task
    u = update.effective_user
    name = get_player_name(u)
    await update.message.reply_text(f"❌ {name} bị loại! Lý do: {reason}")
    if turn_timeout_task:
        turn_timeout_task.cancel()
    idx = players.index(u.id)
    players.remove(u.id)
    if len(players) == 1:
        return await announce_winner(update, ctx)
    if idx < current_player_index:
        current_player_index -= 1
    elif idx == current_player_index:
        current_player_index %= len(players)
    nxt = await ctx.bot.get_chat(players[current_player_index])
    await update.message.reply_text(
        f"🔄 Từ cần nối: 『{current_phrase.split()[-1]}』\n"
        f"👤 Lượt: {get_player_name(nxt)} {get_player_username(nxt)}\n⏰ 60 giây"
    )
    await start_turn_timer(ctx, update.effective_chat.id)

async def announce_winner(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global stats
    if len(players) == 0:
        return await ctx.bot.send_message(update.effective_chat.id, "🏁 Không có người thắng!")
    w = await ctx.bot.get_chat(players[0])
    name = get_player_name(w)
    stats[name] = stats.get(name, 0) + 1
    save_stats(stats)
    await ctx.bot.send_message(update.effective_chat.id, f"🏆 {name} chiến thắng! (Tổng: {stats[name]} lần)")
    reset_game_state()

async def start_turn_timer(ctx, chat_id):
    global turn_timeout_task
    if turn_timeout_task:
        turn_timeout_task.cancel()
    turn_timeout_task = asyncio.create_task(turn_timer(ctx, chat_id))

async def turn_timer(ctx, chat_id):
    global current_player_index, turn_timeout_task
    try:
        await asyncio.sleep(60)
        if not players:
            return
        uf = await ctx.bot.get_chat(players[current_player_index])
        await ctx.bot.send_message(chat_id, f"⏰ {get_player_name(uf)} hết giờ và bị loại!")
        players.remove(uf.id)
        if len(players) == 1:
            return await announce_winner(None, ctx)
        current_player_index %= len(players)
        nxt = await ctx.bot.get_chat(players[current_player_index])
        await ctx.bot.send_message(
            chat_id,
            f"🔄 Từ cần nối: 『{current_phrase.split()[-1]}』\n"
            f"👤 Lượt: {get_player_name(nxt)} {get_player_username(nxt)}\n⏰ 60 giây"
        )
        await start_turn_timer(ctx, chat_id)
    except asyncio.CancelledError:
        pass

async def show_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not stats:
        return await update.message.reply_text("📊 Chưa có ai thắng lần nào.")
    arr = sorted(stats.items(), key=lambda x: x[1], reverse=True)
    msg = "🏆 BẢNG XẾP HẠNG 🏆\n"
    for i,(n,c) in enumerate(arr[:10],1):
        msg += f"{i}. {n}: {c} lần thắng\n"
    await update.message.reply_text(msg)

async def export_players_to_excel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not all_participants:
        return await update.message.reply_text("❌ Chưa có ai tham gia.")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "DanhSach"

    headers = ["STT","Tên","Username","Telegram ID","Thời gian join"]
    ws.append(headers)
    for cell in ws[1]: cell.font = Font(bold=True)

    for i,uid in enumerate(all_participants,1):
        ws.append([
            i,
            player_names.get(uid,""),
            player_usernames.get(uid,""),
            uid,
            player_join_times.get(uid,"")
        ])

    fn="nguoi_choi.xlsx"
    wb.save(fn)
    await ctx.bot.send_document(update.effective_chat.id, open(fn,"rb"))
    os.remove(fn)

async def reset_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global stats
    reset_game_state()
    stats = {}
    save_stats(stats)
    await update.message.reply_text("✅ Đã reset game + thống kê!")

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/startgame - Bắt đầu game  \n"
        "/join - Tham gia  \n"
        "/begin - Bắt đầu chơi  \n"
        "/win - Xem bảng thắng  \n"
        "/export - Xuất Excel người tham gia  \n"
        "/reset - Đặt lại mọi thứ  \n"
        "/help - Hướng dẫn"
    )

# ==== Đăng ký handler & chạy bot ====
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("startgame", start_game))
app.add_handler(CommandHandler("join", join_game))
app.add_handler(CommandHandler("begin", begin_game))
app.add_handler(CommandHandler("win", show_stats))
app.add_handler(CommandHandler("export", export_players_to_excel))
app.add_handler(CommandHandler("reset", reset_all))
app.add_handler(CommandHandler("help", help_cmd))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, play_word))

print("🤖 Bot đã chạy!")
app.run_polling()

