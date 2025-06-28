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

BANNED_WORDS = {"đần", "bần", "ngu", "ngốc", "bò", "dốt", "nát", "chó", "địt", "mẹ", "mày","chi","mô","răng","rứa", "má", "lồn", "lòn", "cứt"}
STATS_FILE = "winners.json"
EXCEL_FILE = "danh_sach.xlsx"

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
            ws.append(["Tên người chơi", "Username", "Telegram ID", "Thời gian tham gia"])
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = today
        ws.append(["Tên người chơi", "Username", "Telegram ID", "Thời gian tham gia"])

    if user_id not in [row[2].value for row in ws.iter_rows(min_row=2)]:
        ws.append([name, username, user_id, join_time])
        wb.save(EXCEL_FILE)

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
    reset_game_state()
    global in_game, game_start_time
    in_game = True
    game_start_time = datetime.now().strftime("%H:%M")
    await update.message.reply_text(
        "🎮 Trò chơi bắt đầu!\n"
        "👉 Gõ /join để tham gia\n"
        "👉 Gõ /begin khi đủ người, để bắt đầu "
    )

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players
    user = update.effective_user
    if user.id not in players:
        players.append(user.id)
        name = get_player_name(user)
        username = get_player_username(user)
        join_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        player_join_times[user.id] = join_time
        save_player_to_excel(user.id, name, username, join_time)
        await update.message.reply_text(f"✅ {name} Đã tham gia! (Tổng: {len(players)} Ng)")
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
        f"✏️ {get_player_name(user)}, Hãy nhập cụm từ đầu tiên:...\u2003\n"
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
        f"{message}🔄 Lượt tiếp theo:\n"
        f"👉 Từ cần nối: 『\u2003{current_word}\u2003』\n"
        f"👤 Người chơi: {get_player_name(next_user)}\n"
        f"⏳ Thời gian: 60 giây "
    )
    await start_turn_timer(context)

async def eliminate_player(update, context, reason):
    global players, current_player_index, turn_timeout_task
    user = update.effective_user
    name = get_player_name(user)
    idx = players.index(user.id)
    if turn_timeout_task:
        turn_timeout_task.cancel()
    await update.message.reply_text(f"❌ {name} Loại! Lý do: {reason}")
    players.remove(user.id)
    if len(players) == 1:
        await announce_winner(update, context)
        return
    if idx < current_player_index:
        current_player_index -= 1
    current_word = current_phrase.split()[-1]
    next_user = await context.bot.get_chat(players[current_player_index])
    await update.message.reply_text(
        f"🔄 Lượt tiếp theo:\n"
        f"👉 Từ cần nối: 『\u2003{current_word}\u2003』\n"
        f"👤 Người chơi: {get_player_name(next_user)}\n"
        f"⏳ Thời gian: 60 giây"
    )
    await start_turn_timer(context)

async def announce_winner(update, context):
    winner = await context.bot.get_chat(players[0])
    name = get_player_name(winner)
    stats[name] = stats.get(name, 0) + 1
    save_stats(stats)
    reset_game_state()
    await update.message.reply_text(f"🎉 {name} Đã chiến thắng!\n\n🌟 Tổng chiến thắng: {stats.get(name, 0)}")

async def start_turn_timer(context):
    global turn_timeout_task
    turn_timeout_task = asyncio.create_task(turn_timer(context))

async def turn_timer(context):
    global players, current_player_index
    await asyncio.sleep(60)
    if len(players) <= current_player_index:
        return
    user_id = players[current_player_index]
    if user_id not in players:
        return
    user = await context.bot.get_chat(user_id)
    await context.bot.send_message(chat_id=context._chat_id, text=f"⏰ {get_player_name(user)} Hết giờ! Loại.")
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
        text=f"🔄 Lượt tiếp theo:\n"
        f"👉 Từ cần nối: 『\u2003{current_word}\u2003』\n"
        f"👤 Người chơi: {get_player_name(next_user)}\n"
        f"⏳ Thời gian: 60 giây"
    )
    await start_turn_timer(context)

async def add_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Vui lòng thêm:...")
        return
    new_word = context.args[0].strip().lower()
    if new_word in BANNED_WORDS:
        await update.message.reply_text(f"⚠️ Từ '{new_word}' Đã tồn tại.")
    else:
        BANNED_WORDS.add(new_word)
        await update.message.reply_text(f"✅ Đã thêm từ '{new_word}' Thên thành công.")

async def export_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(players) == 0:
        await update.message.reply_text("⚠️ Không có người chơi nào.")
        return
    player_list = "\n".join([f"{get_player_name(await context.bot.get_chat(player))} (@{get_player_username(await context.bot.get_chat(player))})" for player in players])
    await update.message.reply_text(f"📋 Danh sách người chơi:\n{player_list}")

async def clear_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists(EXCEL_FILE):
        os.remove(EXCEL_FILE)
        await update.message.reply_text("✅ Tệp Excel đã được xóa.")
    else:
        await update.message.reply_text("⚠️ Không tìm thấy tệp Excel.")

def main():
    application = ApplicationBuilder().token("7670306744:AAHIKDeed6h3prNCmkFhFydwrHkxJB5HM6g").build()

    application.add_handler(CommandHandler("start", start_game))
    application.add_handler(CommandHandler("join", join_game))
    application.add_handler(CommandHandler("begin", begin_game))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(CommandHandler("fast", export_players))
    application.add_handler(CommandHandler("secure", clear_excel))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, play_word))
    application.add_handler(CommandHandler("add_word", add_word))

    application.run_polling()

if __name__ == "__main__":
    main()

