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

# Game state
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
all_players_data = {}

BANNED_WORDS = {"đần", "bần", "ngu", "ngốc", "bò", "dốt", "nát", "chó", "địt", "mẹ", "mày","chi","mô","răng","rứa", "má", "lồn", "lòn", "cứt"}
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
    global players, player_names, player_usernames, player_join_times, current_phrase, used_phrases, current_player_index, in_game, waiting_for_phrase, turn_timeout_task, game_start_time
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
    if turn_timeout_task:
        turn_timeout_task.cancel()

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game_state()
    global stats
    stats = {}
    save_stats(stats)
    await update.message.reply_text("✅ Trò chơi và bảng xếp hạng đã được reset!")

def is_vietnamese(text):
    text = text.strip()
    words = text.split()
    if len(words) != 2:
        return False
    if re.search(r'[0-9]', text):
        return False
    vietnamese_pattern = r'^[a-zA-Zàáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ\s]+$'
    return bool(re.match(vietnamese_pattern, text.lower()))

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

def get_current_time():
    return datetime.now().strftime("%H:%M")

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game_state()
    global in_game, game_start_time
    in_game = True
    game_start_time = get_current_time()
    await update.message.reply_text(
        "🎮 Trò chơi bắt đầu!\n"
        "👉 Gõ /join Để tham gia\n"
        "👉 Gõ /begin Khi đủ người, để bắt đầu "
    )

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players
    user = update.effective_user
    if user.id not in players:
        players.append(user.id)
        get_player_name(user)
        get_player_username(user)
        player_join_times[user.id] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await update.message.reply_text(f"✅ {get_player_name(user)} Đã tham gia! (Tổng: {len(players)} Ng)")
    else:
        await update.message.reply_text("⚠️ Bạn đã tham gia rồi!")

async def begin_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global waiting_for_phrase, current_player_index
    if len(players) < 2:
        await update.message.reply_text("❗ Cần ít nhất 2 người chơi để bắt đầu!")
        return

    waiting_for_phrase = True
    current_player_index = 0
    user_id = players[current_player_index]
    user = await context.bot.get_chat(user_id)
    await update.message.reply_text(
        f"✏️ {get_player_name(user)}, Hãy nhập cụm từ đầu tiên:...\n"
        f"⏰ Bạn có: 60 giây"
    )
    await start_turn_timer(context)

async def play_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_phrase, current_player_index, used_phrases, players, in_game, waiting_for_phrase, turn_timeout_task

    if not in_game:
        return
    user = update.effective_user
    if user.id not in players or user.id != players[current_player_index]:
        return

    text = update.message.text.strip().lower()

    if not is_vietnamese(text):
        await eliminate_player(update, context, "Không hợp lệ!")
        return
    if contains_banned_words(text):
        await eliminate_player(update, context, "Không hợp lệ!")
        return
    if waiting_for_phrase:
        current_phrase = text
        used_phrases[text] = 1
        waiting_for_phrase = False
        await process_valid_word(update, context, text, is_first_word=True)
        return
    if text.split()[0] != current_phrase.split()[-1]:
        await eliminate_player(update, context, f"Từ đầu phải là: '{current_phrase.split()[-1]}'")
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
        f"👉 Từ cần nối: 『{current_word}』\n"
        f"👤 Người chơi: {get_player_name(next_user)}\n"
        f"⏳ Thời gian: 60 giây "
    )
    await start_turn_timer(context)

async def eliminate_player(update, context, reason):
    global players, current_player_index, turn_timeout_task
    user = update.effective_user
    user_name = get_player_name(user)
    player_index = players.index(user.id)

    if turn_timeout_task:
        turn_timeout_task.cancel()

    await update.message.reply_text(f"❌ {user_name} bị loại! Lý do: {reason}")
    players.remove(user.id)

    if len(players) == 1:
        await announce_winner(update, context)
        return

    if player_index < current_player_index:
        current_player_index -= 1
    elif player_index == current_player_index and current_player_index >= len(players):
        current_player_index = 0

    current_word = current_phrase.split()[-1]
    next_user = await context.bot.get_chat(players[current_player_index])
    await update.message.reply_text(
        f"👥 Người chơi còn lại: {len(players)}\n"
        f"🔄 Lượt tiếp theo:\n"
        f"👉 Từ cần nối: 『{current_word}』\n"
        f"👤 Người chơi: {get_player_name(next_user)}\n"
        f"⏳ Thời gian: 60 giây "
    )
    await start_turn_timer(context)

async def announce_winner(update, context):
    if not players:
        await context.bot.send_message(
            chat_id=update.effective_chat.id if update else context._chat_id,
            text="🏁 Trò chơi kết thúc, không có người chiến thắng!"
        )
        reset_game_state()
        return

    winner_id = players[0]
    winner = await context.bot.get_chat(winner_id)
    winner_name = get_player_name(winner)

    stats[winner_name] = stats.get(winner_name, 0) + 1
    save_stats(stats)

    await context.bot.send_message(
        chat_id=update.effective_chat.id if update else context._chat_id,
        text=f"🏆 CHIẾN THẮNG! 🏆\n"
             f"👑 {winner_name}:\u2003\u2003 Vô Địch Nối Chữ!\n"
             f"📊 Số lần thắng:\u2003 {stats[winner_name]}"
    )
    reset_game_state()

async def start_turn_timer(context):
    global turn_timeout_task
    if turn_timeout_task:
        turn_timeout_task.cancel()
    turn_timeout_task = asyncio.create_task(turn_timer(context))

async def turn_timer(context):
    global players, current_player_index
    try:
        await asyncio.sleep(60)
        if not players or current_player_index >= len(players):
            return
        user_id = players[current_player_index]
        user = await context.bot.get_chat(user_id)
        await context.bot.send_message(
            chat_id=context._chat_id,
            text=f"⏰ {get_player_name(user)} Hết giờ: Loại!"
        )
        eliminated_index = current_player_index
        players.remove(user_id)

        if len(players) == 1:
            await announce_winner(None, context)
            return

        if eliminated_index < current_player_index:
            current_player_index -= 1
        elif eliminated_index == current_player_index and current_player_index >= len(players):
            current_player_index = 0

        current_word = current_phrase.split()[-1]
        next_user = await context.bot.get_chat(players[current_player_index])
        await context.bot.send_message(
            chat_id=context._chat_id,
            text=f"👥 Người chơi còn lại: {len(players)}\n"
                 f"🔄 Lượt tiếp theo:\n"
                 f"👉 Từ cần nối: 『{current_word}』\n"
                 f"👤 Người chơi: {get_player_name(next_user)}\n"
                 f"⏳ Thời gian: 60 giây "
        )
        await start_turn_timer(context)
    except asyncio.CancelledError:
        pass

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not stats:
        await update.message.reply_text("📊 Chưa có ai thắng cả!")
        return
    ranking = sorted(stats.items(), key=lambda x: x[1], reverse=True)
    message = "🏆 BẢNG XẾP HẠNG 🏆\n\n"
    for i, (name, wins) in enumerate(ranking[:10], 1):
        message += f"{i}. {name}: {wins} lần thắng\n"
    await update.message.reply_text(message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 HƯỚNG DẪN TRÒ CHƠI NỐI CHỮ\n\n"
        "🔹 /startgame - Bắt đầu trò chơi mới\n"
        "🔹 /join - Tham gia trò chơi\n"
        "🔹 /begin - Bắt đầu khi đủ người\n"
        "🔹 /win - Xem bảng xếp hạng\n"
        "🔹 /help - Xem hướng dẫn\n\n"
        "📌 LUẬT CHƠI:\n"
        "- Mỗi cụm từ gồm 2 từ.\n"
        "- Nối từ cuối của cụm trước đó.\n"
        "- Không lặp lại cụm từ đã dùng.\n"
        "- Không dùng từ không phù hợp.\n"
        "- Mỗi lượt có 60 giây để trả lời.\n"
        "- Người cuối cùng còn lại sẽ chiến thắng!"
        "- @xukaxuka2k1 code free,export,clearfile!"
    )

async def export_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not player_names:
        await update.message.reply_text("❌ Chưa có người chơi nào tham gia!")
        return
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Danh sách người chơi"
    ws.append(["Tên người chơi", "Username", "Telegram ID", "Thời gian tham gia"])
    for user_id in player_names:
        name = player_names.get(user_id, "Không rõ")
        username = player_usernames.get(user_id, "(chưa có username)")
        join_time = player_join_times.get(user_id, "Không rõ")
        ws.append([name, username, user_id, join_time])
    filename = "danh_sach_nguoi_choi.xlsx"
    wb.save(filename)
    with open(filename, "rb") as f:
        await update.message.reply_document(document=f, filename=filename)

async def clear_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    filename = "danh_sach_nguoi_choi.xlsx"
    if os.path.exists(filename):
        os.remove(filename)
        await update.message.reply_text("🧹 File Excel đã được xóa.")
    else:
        await update.message.reply_text("⚠️ Không tìm thấy file Excel để xóa.")

if __name__ == '__main__':
    TOKEN = "7670306744:AAHIKDeed6h3prNCmkFhFydwrHkxJB5HM6g"
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("startgame", start_game))
    app.add_handler(CommandHandler("join", join_game))
    app.add_handler(CommandHandler("begin", begin_game))
    app.add_handler(CommandHandler("win", show_stats))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("export", export_players))
    app.add_handler(CommandHandler("clearfile", clear_excel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, play_word))

    print("Bot đang chạy...")
    app.run_polling()

