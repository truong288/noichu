from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from stay_alive import keep_alive
import asyncio
import re
import json
import os
from datetime import datetime
import openpyxl

keep_alive()

players = []
player_names = {}
player_usernames = {}
player_join_times = {}
current_phrase = ""
used_phrases = {}
current_player_index = 0
in_game = False
waiting_for_phrase = False
turn_timeout_task = None
game_start_time = None
chat_id = None
BANNED_USERS = set()

BANNED_WORDS = {
    "đần", "bần", "ngu", "ngốc", "bò", "dốt", "nát", "chó", "địt", "mẹ", "mày",
    "chi", "mô", "răng", "rứa", "má", "lồn", "lòn", "cứt"
}
STATS_FILE = "winners.json"
EXCEL_FILE = "danh_sach.xlsx"


def is_admin(user_id):
    admin_ids = [5429428390, 5930936939, 7034158998]
    return user_id in admin_ids


def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_stats(data):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


stats = load_stats()


def save_player_to_excel(user_id, name, username, join_time):
    today = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(EXCEL_FILE):
        wb = openpyxl.load_workbook(EXCEL_FILE)
        if today in wb.sheetnames:
            ws = wb[today]
        else:
            ws = wb.create_sheet(today)
            ws.append([
                "Tên người chơi", "Username", "Telegram ID",
                "Thời gian tham gia"
            ])
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = today
        ws.append([
            "Tên người chơi", "Username", "Telegram ID", "Thời gian tham gia"
        ])

    if user_id not in [row[2].value for row in ws.iter_rows(min_row=2)]:
        ws.append([name, username, user_id, join_time])
        wb.save(EXCEL_FILE)


def reset_game_state():
    global players, player_names, player_usernames, player_join_times, current_phrase, used_phrases, current_player_index, in_game, waiting_for_phrase, turn_timeout_task, game_start_time, chat_id
    players = []
    player_names = {}
    player_usernames = {}
    player_join_times = {}
    current_phrase = ""
    used_phrases = {}
    current_player_index = 0
    in_game = False
    waiting_for_phrase = False
    game_start_time = None
    chat_id = None
    if turn_timeout_task:
        turn_timeout_task.cancel()
        turn_timeout_task = None


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game_state()
    global stats
    stats = {}
    save_stats(stats)
    await update.message.reply_text(
        "✅ Trò chơi và bảng xếp hạng đã được reset!")


def is_vietnamese(text):
    text = text.strip().lower()
    words = text.split()
    if len(words) != 2:
        return False
    if any(len(word) == 1 for word in words):
        return False
    if re.search(r'\d', text):
        return False
    vietnamese_pattern = r'^[a-zàáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ\s]+$'
    if not re.match(vietnamese_pattern, text):
        return False
    return True


def contains_banned_words(text):
    words = text.lower().split()
    return any(word in BANNED_WORDS for word in words)


def get_player_name(user):
    if user.id in player_names:
        return player_names[user.id]
    name = user.first_name
    if user.last_name:
        name += f" {user.last_name}"
    player_names[user.id] = name
    return name


def get_player_username(user):
    if user.username:
        player_usernames[user.id] = user.username
        return user.username
    return "(chưa có username)"


async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global in_game, waiting_for_phrase, game_start_time, chat_id

    # Nếu trò chơi đang diễn ra hoặc đang chờ người chơi nhập cụm đầu
    if in_game or waiting_for_phrase:
        await update.message.reply_text(
            "⚠️ Trò chơi đang diễn ra, chưa kết thúc. Hãy ấn /luuy để hiểu thêm nhé!")
        return

    reset_game_state()  # Đặt lại toàn bộ trạng thái trò chơi
    game_start_time = datetime.now().strftime("%H:%M") 
    chat_id = update.effective_chat.id

    await update.message.reply_text(
        "🎮 Trò chơi bắt đầu!\n"
        "👉 Gõ \u2003/join \u2003 để tham gia.\n"
        "👉 Gõ \u2003/begin \u2003 khi đủ người, để bắt đầu."
    )

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players
    user = update.effective_user
    if user.id in BANNED_USERS:
        await update.message.reply_text("🚫 Bạn đã bị cấm tham gia trò chơi.")
        return
    if user.id not in players:
        players.append(user.id)
        name = get_player_name(user)
        username = get_player_username(user)
        join_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        player_join_times[user.id] = join_time
        save_player_to_excel(user.id, name, username, join_time)
        await update.message.reply_text(
            f"✅ {name} Đã tham gia! (Tổng: {len(players)} Ng)")
    else:
        await update.message.reply_text("⚠️ Bạn đã tham gia rồi!")


async def begin_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global waiting_for_phrase, current_player_index, in_game

    # Nếu đã bắt đầu rồi thì không được ấn thêm
    if in_game or waiting_for_phrase:
        await update.message.reply_text("⚠️ Trò chơi đã bắt đầu.")
        return

    if len(players) < 2:
        await update.message.reply_text(
            "❗ Cần ít nhất 2 người chơi để bắt đầu!")
        return

    in_game = True
    waiting_for_phrase = True
    current_player_index = 0
    user_id = players[current_player_index]
    user = await context.bot.get_chat(user_id)

    await update.message.reply_text(
        f"✏️ {get_player_name(user)}, Hãy nhập cụm từ đầu tiên:...\u2003\n"
        f"⏰ Bạn có 60 giây.")
    await start_turn_timer(context)



async def play_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_phrase, current_player_index, used_phrases, players, in_game, waiting_for_phrase, turn_timeout_task
    if not in_game or not waiting_for_phrase and current_phrase == "":
        return
    user = update.effective_user
    if user.id not in players or user.id != players[current_player_index]:
        return
    text = update.message.text.strip().lower()
    if not is_vietnamese(text) or contains_banned_words(text):
        await eliminate_player(update, context, "Không hợp lệ!")
        return
    if waiting_for_phrase:
        current_phrase = text
        used_phrases[text] = 1
        waiting_for_phrase = False
        await process_valid_word(update, context, text, is_first_word=True)
        return
    if text.split()[0] != current_phrase.split()[-1]:
        await eliminate_player(
            update, context, f"Từ đầu phải là: '{current_phrase.split()[-1]}'")
        return
    if text in used_phrases:
        await eliminate_player(update, context, "Cụm từ đã dùng")
        return
    used_phrases[text] = 1
    current_phrase = text
    await process_valid_word(update, context, text)


async def process_valid_word(update, context, text, is_first_word=False):
    global current_player_index, players, turn_timeout_task
    if turn_timeout_task:
        turn_timeout_task.cancel()
        turn_timeout_task = None
    if is_first_word:
        message = f"🎯 Từ bắt đầu: '{text}'\n\n"
    else:
        message = f"✅ {get_player_name(update.effective_user)} Đã nối thành công!\n\n"
    current_player_index = (current_player_index + 1) % len(players)
    if len(players) == 1:
        await announce_winner(update, context)
        return
    current_word = current_phrase.split()[-1]
    next_user = await context.bot.get_chat(players[current_player_index])
    await update.message.reply_text(
        f"{message}"
        f"🔄 Lượt tiếp theo:\n"
        f"👉 Từ cần nối: 『\u2003{current_word}\u2003』\n"
        f"👤 Người chơi: {get_player_name(next_user)}\n"
        f"⏳ Thời gian: 60 giây ")
    await start_turn_timer(context)


async def eliminate_player(update, context, reason):
    global players, current_player_index, turn_timeout_task
    user = update.effective_user
    name = get_player_name(user)
    if user.id not in players:
        return
    idx = players.index(user.id)
    if turn_timeout_task:
        turn_timeout_task.cancel()
        turn_timeout_task = None
    await update.message.reply_text(f"❌ {name} Loại! Lý do: {reason}")
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
        f"👥 Người chơi còn lại: {len(players)}\n"
        f"🔄 Lượt tiếp theo:\n"
        f"👉 Từ cần nối: 『\u2003{current_word}\u2003』\n"
        f"👤 Người chơi: {get_player_name(next_user)}\n"
        f"⏳ Thời gian: 60 giây ")
    await start_turn_timer(context)


async def announce_winner(update, context):
    global stats, players
    if not players:
        if update:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="🏁 Không có người chiến thắng.")
        reset_game_state()
        return
    winner_id = players[0]
    winner = await context.bot.get_chat(winner_id)
    name = get_player_name(winner)
    stats[name] = stats.get(name, 0) + 1
    save_stats(stats)
    cid = update.effective_chat.id if update else chat_id
    await context.bot.send_message(chat_id=cid,
                                   text=f"🏆 CHIẾN THẮNG!🏆\n"
                                   f"👑 {name} -\u2003 Vô địch nối chữ!\n"
                                   f"📊 Số lần thắng:\u2003 {stats[name]}")
    try:
        await context.bot.send_sticker(
            chat_id=cid,
            sticker=
            "CAACAgUAAxkBAAIBhWY9Bz7A0vjK0-BzFLEIF3qv7fBvAAK7AQACVp29V_R3rfJPL2MlNAQ"
        )
    except Exception as e:
        print(f"Lỗi gửi sticker thắng: {e}")
    reset_game_state()


async def start_turn_timer(context):
    global turn_timeout_task
    if turn_timeout_task:
        turn_timeout_task.cancel()
        turn_timeout_task = None
    turn_timeout_task = asyncio.create_task(turn_timer(context))


async def turn_timer(context):
    global players, current_player_index, chat_id
    try:
        await asyncio.sleep(60)
        if not players or current_player_index >= len(players):
            return
        user_id = players[current_player_index]
        user = await context.bot.get_chat(user_id)
        await context.bot.send_message(
            chat_id=chat_id, text=f"⏰ {get_player_name(user)} Hết giờ! Loại.")
        if user_id in players:
            players.remove(user_id)
        if len(players) == 1:
            await announce_winner(None, context)
            return
        if current_player_index >= len(players):
            current_player_index = 0
        current_word = current_phrase.split()[-1]
        next_user = await context.bot.get_chat(players[current_player_index])
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔄 Lượt tiếp theo:\n"
            f"👉 Từ cần nối: 『\u2003{current_word}\u2003』\n"
            f"👤 Người chơi: {get_player_name(next_user)}\n"
            f"⏳ Thời gian:60 giây")
        await start_turn_timer(context)
    except asyncio.CancelledError:
        pass


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not stats:
        await update.message.reply_text("📊 Chưa có ai thắng cả!🏁")
        return
    ranking = sorted(stats.items(), key=lambda x: x[1], reverse=True)
    message = "🏆 BẢNG XẾP HẠNG 🏆\n\n"
    for i, (name, wins) in enumerate(ranking[:10], 1):
        message += f"{i}. {name}: {wins} Lần thắng\n"
    await update.message.reply_text(message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 HƯỚNG DẪN TRÒ CHƠI NỐI CHỮ\n\n"
        "🔹 /startgame - Bắt đầu trò chơi mới.\n"
        "🔹 /join - Tham gia trò chơi.\n"
        "🔹 /begin - Bắt đầu khi đủ người.\n"
        "🔹 /win - Xem bảng xếp hạng.\n"
        "🔹 /reset - Làm mới lại toàn bộ.\n"
        "🔹 /help - Xem hướng dẫn.\n\n"
        "📌 LUẬT CHƠI:\n"
        "- Mỗi cụm từ gồm 2 từ.\n"
        "- Nối từ cuối của cụm trước đó.\n"
        "- Không lặp lại cụm từ đã dùng.\n"
        "- Không dùng từ không phù hợp.\n"
        "- Mỗi lượt có 60 giây để trả lời.\n"
        "- Người cuối cùng còn lại sẽ chiến thắng.!\n"
        "👉 @xukaxuka2k1 code free,fastandsecure👈")


async def export_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(EXCEL_FILE):
        await update.message.reply_text("❌ Chưa có dữ liệu người chơi.")
        return
    with open(EXCEL_FILE, "rb") as f:
        await update.message.reply_document(document=f, filename=EXCEL_FILE)


async def clear_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists(EXCEL_FILE):
        os.remove(EXCEL_FILE)
        await update.message.reply_text("🧹 File Excel đã được xoá.")
    else:
        await update.message.reply_text("⚠️ Không tìm thấy file Excel để xoá.")


async def add_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⚠️ Chưa thêm quyền.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Vui lòng nhập từ...")
        return

    new_word = context.args[0].strip().lower()
    if new_word in BANNED_WORDS:
        await update.message.reply_text("⚠️ Từ này đã tồn tại.")
    else:
        BANNED_WORDS.add(new_word)
        await update.message.reply_text(
            f"✅ Đã thêm từ '{new_word}' thành công.")


async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Chưa thêm quyền.")
    if not context.args:
        return await update.message.reply_text("⚠️ Cú pháp: /ban @username")
    username = context.args[0].lstrip('@')
    for uid, uname in player_usernames.items():
        if uname == username:
            BANNED_USERS.add(uid)
            if uid in players:
                players.remove(uid)
            await update.message.reply_text(
                f"🚫 Đã ban {username} khỏi trò chơi.")
            return
    await update.message.reply_text("⚠️ Không tìm thấy người chơi đó.")


async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text(
            "❌ Bạn không có quyền sử dụng lệnh này.")
    if not context.args:
        return await update.message.reply_text("⚠️ Cú pháp: /kick @username")
    username = context.args[0].lstrip('@')
    for uid in players:
        if player_usernames.get(uid) == username:
            players.remove(uid)
            await update.message.reply_text(
                f"👢 Đã loại {username} khỏi trò chơi.")
            return
    await update.message.reply_text(
        "⚠️ Không tìm thấy người chơi đó trong danh sách.")


async def list_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not players:
        return await update.message.reply_text("👥 Chưa có người chơi nào.")
    msg = "📋 Danh sách người chơi:\n"
    for i, uid in enumerate(players, 1):
        name = player_names.get(uid, "(ẩn danh)")
        uname = player_usernames.get(uid, "")
        msg += f"{i}. {name} (@{uname})\n"
    await update.message.reply_text(msg)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Kiểm tra quyền admin
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text(
            "❌ Bạn không có quyền sử dụng lệnh này.")

    # Danh sách các lệnh quản trị viên
    admin_commands ="📜 **\u2003ADMMIN\u2003** 📜\n"\
                    "🔹 /ban @username - Cấm.\n"\
                    "🔹 /kick @username - Kích.\n"\
                    "🔹 /addword <từ> - Thêm từ:...\n"\
                    "🔹 /reset - Làm mới lại toàn bộ."

    # Gửi tin nhắn chứa các lệnh quản trị viên
    await update.message.reply_text(admin_commands, parse_mode="Markdown")

async def luu_y(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Nội dung lưu ý
    note = (
        "⚠️ **Lưu ý** ⚠️\n\n"
        "🔹 **Bot không hoạt động cùng lúc ở nhiều nhóm**.\n"
        "🔹 **Bot chỉ hoạt động trong nhóm nào ấn [begin] trước**.\n"
        "🔹 **Vì vậy, nếu trò chơi đang diễn ra trong nhóm này**.\n"
        "🔹 **Nhóm khác sẽ không thể bắt đầu trò chơi**.\n"
        "🔹 **Cho đến khi trò chơi kết thúc ở nhóm trước**.\n"
        "🔹 **Thì mới [startgame] để tiếp tục chơi nhé!**"
    )
    await update.message.reply_text(note)

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Lệnh không hợp lệ. Gõ /help để xem lệnh.")


def main():
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("startgame", start_game))
    app.add_handler(CommandHandler("join", join_game))
    app.add_handler(CommandHandler("begin", begin_game))
    app.add_handler(CommandHandler("win", show_stats))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("fast", export_players))
    app.add_handler(CommandHandler("dsecure", clear_excel))
    app.add_handler(CommandHandler("addword", add_word))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("kick", kick_user))
    app.add_handler(CommandHandler("list", list_players))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("luuy", luu_y))
    app.add_handler(
        MessageHandler(filters.TEXT & (~filters.COMMAND), play_word))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    print("Bot is running...")
    app.run_polling()


if __name__ == '__main__':
    main()
