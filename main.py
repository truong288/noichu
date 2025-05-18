from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from stay_alive import keep_alive
import asyncio
import re
import json
import os

keep_alive()

# Game state
players = []
player_names = {}  # Lưu tên người chơi để hiển thị đẹp hơn
current_phrase = ""
used_phrases = {}
current_player_index = 0
in_game = False
waiting_for_phrase = False
turn_timeout_task = None

# Banned words
BANNED_WORDS = {"đần", "bần", "ngu", "ngốc", "bò", "dốt", "nát", "chó", "địt", "mẹ", "mày", "má"}

# Stats
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
    global players, player_names, current_phrase, used_phrases, current_player_index, in_game, waiting_for_phrase, turn_timeout_task
    players = []
    player_names = {}
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
    await update.message.reply_text("✅ Trò chơi và bảng xếp hạng đã được reset!")

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

def get_player_name(user):
    """Lấy tên hiển thị của người chơi"""
    if user.id in player_names:
        return player_names[user.id]
    name = user.first_name
    if user.last_name:
        name += f" {user.last_name}"
    player_names[user.id] = name
    return name

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game_state()
    global in_game
    in_game = True
    await update.message.reply_text(
        "🎮 Trò chơi bắt đầu!\n"
        "👉 Gõ /join Để tham gia\n"
        "👉 Gõ /begin Khi đủ người, để bắt đầu\n\n"
    )

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players
    user = update.effective_user
    if user.id not in players:
        players.append(user.id)
        get_player_name(user)  # Lưu tên người chơi
        await update.message.reply_text(f"✅ {get_player_name(user)} đã tham gia! (Tổng: {len(players)} người)")
    else:
        await update.message.reply_text("⚠️ Bạn đã tham gia rồi!")

async def begin_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global waiting_for_phrase
    if len(players) < 2:
        await update.message.reply_text("❗ Cần ít nhất 2 người chơi để bắt đầu!")
        return
    
    waiting_for_phrase = True
    user_id = players[current_player_index]
    user = await context.bot.get_chat(user_id)
    await update.message.reply_text(
        f"✏️ {get_player_name(user)}, Hãy nhập cụm từ đầu tiên..!\n"
        f"⏰ Bạn có 60 giây để nhập..."
    )
    await start_turn_timer(context)

async def play_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_phrase, current_player_index, used_phrases, players, in_game, waiting_for_phrase, turn_timeout_task
    
    if not in_game:
        return

    user = update.effective_user
    text = update.message.text.strip().lower()

    # Chỉ xử lý nếu là người chơi hiện tại
    if user.id != players[current_player_index]:
        return

    # Validate từ
    if not is_vietnamese(text):
        await eliminate_player(update, context, "Phải nhập đúng 2 từ tiếng Việt")
        return

    if contains_banned_words(text):
        await eliminate_player(update, context, "Sử dụng từ không phù hợp")
        return

    # Xử lý từ đầu tiên
    if waiting_for_phrase:
        current_phrase = text
        used_phrases[text] = 1
        waiting_for_phrase = False
        await process_valid_word(update, context, text, is_first_word=True)
        return

    # Kiểm tra từ nối
    if text.split()[0] != current_phrase.split()[-1]:
        await eliminate_player(update, context, f"Từ đầu phải là: '{current_phrase.split()[-1]}'")
        return

    if text in used_phrases:
        await eliminate_player(update, context, "Cụm từ này đã được dùng trước đó")
        return

    # Từ hợp lệ
    used_phrases[text] = 1
    current_phrase = text
    await process_valid_word(update, context, text)

async def process_valid_word(update, context, text, is_first_word=False):
    global current_player_index, players
    
    # Hủy bộ đếm thời gian cũ
    if turn_timeout_task:
        turn_timeout_task.cancel()
    
    if is_first_word:
        message = f"🎯 Từ bắt đầu: '{text}'\n\n"
    else:
        message = f"✅ {get_player_name(update.effective_user)} Đã nối thành công!\n\n"
    
    # Chuyển lượt
    current_player_index = (current_player_index + 1) % len(players)
    
    # Kiểm tra nếu chỉ còn 1 người chơi
    if len(players) == 1:
        await announce_winner(update, context)
        return
    
    # Chuẩn bị lượt tiếp theo
    current_word = current_phrase.split()[-1]
    next_user = await context.bot.get_chat(players[current_player_index])
    
    await update.message.reply_text(
        f"{message}"
        f"🔄 Lượt tiếp theo:\n"
        f"👉 Từ cần nối: 『{current_word}』\n"
        f"👤 Người chơi: {get_player_name(next_user)}\n"
        f"⏳ Thời gian: 60 giây"
    )
    
    await start_turn_timer(context)

async def eliminate_player(update, context, reason):
    global players, current_player_index
    
    user = update.effective_user
    user_name = get_player_name(user)
    player_index = players.index(user.id)
    
    await update.message.reply_text(f"❌ {user_name} bị loại! Lý do: {reason}")
    players.remove(user.id)
    
    # Điều chỉnh chỉ số người chơi hiện tại
    if player_index < current_player_index:
        current_player_index -= 1
    elif player_index == current_player_index and current_player_index >= len(players):
        current_player_index = 0
    
    # Kiểm tra người chiến thắng
    if len(players) == 1:
        await announce_winner(update, context)
    else:
        current_word = current_phrase.split()[-1]
        next_user = await context.bot.get_chat(players[current_player_index])
        await update.message.reply_text(
            f"👥 Người chơi còn lại: {len(players)}\n"
            f"🔄 Lượt tiếp theo:\n"
            f"👉 Từ cần nối: 『{current_word}』\n"
            f"👤 Người chơi: {get_player_name(next_user)}\n"
            f"⏳ Thời gian: 60 giây"
        )
        await start_turn_timer(context)

async def announce_winner(update, context):
    if not players:  # Trường hợp không còn người chơi
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🏁 Trò chơi kết thúc, không có người chiến thắng!"
        )
        reset_game_state()
        return
    
    winner_id = players[0]
    winner = await context.bot.get_chat(winner_id)
    winner_name = get_player_name(winner)
    
    # Cập nhật thống kê
    stats[winner_name] = stats.get(winner_name, 0) + 1
    save_stats(stats)
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🏆 CHIẾN THẮNG! 🏆\n"
             f"👑 {winner_name} Vô Địch Nối Chữ!\n"
             f"📊 Số lần thắng: {stats[winner_name]}"
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
        user_name = get_player_name(user)
        
        await context.bot.send_message(
            chat_id=context._chat_id,
            text=f"⏰ {user_name} hết thời gian và bị loại!"
        )
        
        # Lưu vị trí trước khi loại
        eliminated_index = current_player_index
        players.remove(user_id)
        
        # Điều chỉnh chỉ số người chơi hiện tại
        if eliminated_index < current_player_index:
            current_player_index -= 1
        elif eliminated_index == current_player_index and current_player_index >= len(players):
            current_player_index = 0
        
        # Kiểm tra người chiến thắng
        if len(players) == 1:
            await announce_winner(None, context)
        elif players:
            current_word = current_phrase.split()[-1]
            next_user = await context.bot.get_chat(players[current_player_index])
            await context.bot.send_message(
                chat_id=context._chat_id,
                text=f"👥 Người chơi còn lại: {len(players)}\n"
                     f"🔄 Lượt tiếp theo:\n"
                     f"👉 Từ cần nối: 『{current_word}』\n"
                     f"👤 Người chơi: {get_player_name(next_user)}\n"
                     f"⏳ Thời gian: 60 giây"
            )
            await start_turn_timer(context)
            
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Lỗi timer: {e}")

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not stats:
        await update.message.reply_text("📊 Chưa có ai thắng cả!")
        return
    
    ranking = sorted(stats.items(), key=lambda x: x[1], reverse=True)
    message = "🏆 BẢNG XẾP HẠNG 🏆\n\n"
    for i, (name, wins) in enumerate(ranking[:10], 1):  # Top 10
        message += f"{i}. {name}: {wins} lần thắng\n"
    
    await update.message.reply_text(message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 HƯỚNG DẪN TRÒ CHƠI NỐI CHỮ\n\n"
        "🔹 /startgame - Bắt đầu trò chơi mới\n"
        "🔹 /join - Tham gia trò chơi\n"
        "🔹 /begin - Bắt đầu khi đủ người\n"
        "🔹 /win - Xem bảng xếp hạng\n"
        "🔹 /reset - Reset trò chơi\n"
        "🔹 /help - Xem hướng dẫn\n\n"
        "📌 LUẬT CHƠI:\n"
        "- Mỗi cụm từ gồm 2 từ tiếng Việt\n"
        "- Nối từ cuối của cụm trước đó\n"
        "- Không lặp lại cụm từ đã dùng\n"
        "- Không dùng từ cấm hoặc không phù hợp\n"
        "- Mỗi lượt có 60 giây để trả lời\n"
        "- Người cuối cùng còn lại sẽ chiến thắng!"
    )

if __name__ == '__main__':
    TOKEN = "7670306744:AAHIKDeed6h3prNCmkFhFydwrHkxJB5HM6g"  # Thay bằng token thật
    app = ApplicationBuilder().token(TOKEN).build()

    # Đăng ký các command
    commands = [
        ("startgame", start_game),
        ("join", join_game),
        ("begin", begin_game),
        ("win", show_stats),
        ("reset", reset),
        ("help", help_command)
    ]
    
    for cmd, handler in commands:
        app.add_handler(CommandHandler(cmd, handler))
    
    # Xử lý tin nhắn thường
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, play_word))
    
    print("Bot đang chạy...")
    app.run_polling()
