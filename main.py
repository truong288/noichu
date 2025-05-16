from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
import os
import logging
from datetime import datetime, timedelta
import asyncio

# Cấu hình logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Game state
players = []
current_phrase = ""
used_phrases = set()
current_player_index = 0
in_game = False
waiting_for_phrase = False
turn_timeout_task = None
BANNED_WORDS = {'đần', 'bần', 'ngu', 'ngôc', 'bò', 'dốt', 'nát'}

def reset_game():
    global players, current_phrase, used_phrases, current_player_index, in_game, waiting_for_phrase, turn_timeout_task
    players = []
    current_phrase = ""
    used_phrases = set()
    current_player_index = 0
    in_game = False
    waiting_for_phrase = False
    if turn_timeout_task:
        turn_timeout_task.cancel()
        turn_timeout_task = None

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_game()
    global in_game
    in_game = True

    await update.message.reply_text(
        "🎮 Trò chơi bắt đầu!\n"
        "👉 Gõ /join để tham gia.\n"
        "👉 Gõ /begin để bắt đầu chơi khi đủ người."
    )

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players
    if not in_game:
        await update.message.reply_text("❗ Trò chơi chưa được bắt đầu. Dùng /startgame để bắt đầu.")
        return

    user = update.effective_user
    if user.id not in [p[0] for p in players]:
        players.append((user.id, user.first_name))
        await update.message.reply_text(
            f"✅ {user.first_name} đã tham gia... (Tổng {len(players)} người)"
        )
        
        # Người đầu tiên là người bắt đầu
        if len(players) == 1:
            await update.message.reply_text(
                f"🎯 {user.first_name} sẽ là người bắt đầu trò chơi!"
            )
    else:
        await update.message.reply_text("⚠️ Bạn đã tham gia rồi!")

async def begin_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_player_index, waiting_for_phrase
    
    if not in_game:
        await update.message.reply_text("❗ Trò chơi chưa được bắt đầu. Dùng /startgame để bắt đầu.")
        return

    if len(players) < 2:
        await update.message.reply_text("❗ Cần ít nhất 2 người chơi để bắt đầu.")
        return

    waiting_for_phrase = True
    user_id, user_name = players[current_player_index]

    await update.message.reply_text(
        f"✏️ {user_name}, hãy nhập cụm từ đầu tiên (2 từ trở lên) để bắt đầu trò chơi!"
    )
    await start_turn_timer(update, context)

def is_valid_phrase(phrase):
    # Kiểm tra từ cấm
    phrase_lower = phrase.lower()
    for word in BANNED_WORDS:
        if word in phrase_lower:
            return False
    
    # Kiểm tra ít nhất 2 từ
    if len(phrase.split()) < 2:
        return False
        
    return True

async def play_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_phrase, current_player_index, used_phrases, players, in_game, waiting_for_phrase, turn_timeout_task

    if not in_game:
        return

    user = update.effective_user
    text = update.message.text.strip()

    # Kiểm tra có phải người chơi không
    if user.id not in [p[0] for p in players]:
        return

    # Kiểm tra lượt chơi
    current_player_id, current_player_name = players[current_player_index]
    if user.id != current_player_id:
        return

    if waiting_for_phrase:
        if not is_valid_phrase(text):
            await update.message.reply_text("❌ Cụm từ không hợp lệ! Phải có ít nhất 2 từ và không chứa từ cấm.")
            return

        current_phrase = text
        used_phrases.add(text.lower())
        waiting_for_phrase = False
        current_player_index = (current_player_index + 1) % len(players)

        next_id, next_name = players[current_player_index]

        await update.message.reply_text(
            f"✅ Từ bắt đầu là: '{text}'\n"
            f"👤 {next_name}, hãy nối với từ cuối: '{text.split()[-1]}'"
        )
        await start_turn_timer(update, context)
        return

    # Kiểm tra từ nối
    if text.split()[0].lower() != current_phrase.split()[-1].lower():
        await eliminate_player(update, context, reason="Không đúng từ nối")
        return

    # Kiểm tra từ đã dùng
    if text.lower() in used_phrases:
        await eliminate_player(update, context, reason="Cụm từ đã được sử dụng")
        return

    # Kiểm tra từ hợp lệ
    if not is_valid_phrase(text):
        await eliminate_player(update, context, reason="Cụm từ không hợp lệ")
        return

    used_phrases.add(text.lower())
    current_phrase = text
    current_player_index = (current_player_index + 1) % len(players)

    if len(players) == 1:
        winner_id, winner_name = players[0]
        await update.message.reply_text(f"🏆 {winner_name} chiến thắng! 🎉")
        reset_game()
        return

    next_id, next_name = players[current_player_index]

    await update.message.reply_text(
        f"✅ Hợp lệ! Từ tiếp theo phải bắt đầu bằng: '{text.split()[-1]}'\n"
        f"👤 Đến lượt: {next_name}"
    )
    await start_turn_timer(update, context)

async def eliminate_player(update, context, reason):
    global players, current_player_index
    
    user = update.effective_user
    player_index = next((i for i, (p_id, _) in enumerate(players) if p_id == user.id), None)
    
    if player_index is None:
        return

    _, player_name = players[player_index]
    await update.message.reply_text(
        f"❌ {player_name} bị loại! Lý do: {reason}"
    )
    
    # Xóa người chơi
    del players[player_index]
    
    # Điều chỉnh chỉ số người chơi hiện tại
    if current_player_index >= len(players):
        current_player_index = 0
    elif player_index < current_player_index:
        current_player_index -= 1

    if len(players) == 1:
        winner_id, winner_name = players[0]
        await update.message.reply_text(f"🏆 {winner_name} chiến thắng! 🎉")
        reset_game()
    else:
        await update.message.reply_text(
            f"👥 Còn lại {len(players)} người chơi."
        )
        await start_turn_timer(update, context)

async def start_turn_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global turn_timeout_task
    if turn_timeout_task:
        turn_timeout_task.cancel()
    turn_timeout_task = asyncio.create_task(turn_timer(update, context))

async def turn_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global players, current_player_index
    
    try:
        await asyncio.sleep(59)
        
        if not in_game or not players:
            return
            
        current_player_id, current_player_name = players[current_player_index]
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"⏰ {current_player_name} hết thời gian và bị loại!"
        )
        
        # Xóa người chơi
        del players[current_player_index]
        
        if current_player_index >= len(players):
            current_player_index = 0

        if len(players) == 1:
            winner_id, winner_name = players[0]
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"🏆 {winner_name} chiến thắng! 🎉"
            )
            reset_game()
            return
            
        await start_turn_timer(update, context)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Error in turn timer: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 Hướng dẫn chơi:\n\n"
        "1. /startgame - Bắt đầu trò chơi mới\n"
        "2. /join - Tham gia trò chơi (người đầu tiên sẽ bắt đầu)\n"
        "3. /begin - Bắt đầu khi đủ người chơi\n"
        "4. Mỗi lượt có 59 giây để trả lời\n"
        "5. Từ phải có ít nhất 2 từ và không chứa từ cấm\n"
        "6. Phải nối đúng từ cuối của từ trước\n"
        "7. Không được lặp lại từ đã dùng"
    )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Error while processing update: {update}")
    if update and hasattr(update, 'message') and update.message:
        await update.message.reply_text("❌ Đã xảy ra lỗi, vui lòng thử lại!")

async def set_webhook(app):
    webhook_url = os.getenv('WEBHOOK_URL')
    if not webhook_url:
        raise ValueError("WEBHOOK_URL environment variable not set")
    
    await app.bot.set_webhook(
        url=webhook_url,
        allowed_updates=Update.ALL_TYPES
    )
    logger.info(f"Webhook set to: {webhook_url}")

def main():
    # Lấy token từ biến môi trường
    TOKEN = os.getenv('TELEGRAM_TOKEN')
    if not TOKEN:
        raise ValueError("Vui lòng đặt biến môi trường TELEGRAM_TOKEN")

    # Tạo ứng dụng
    app = ApplicationBuilder().token(TOKEN).build()

    # Đăng ký handlers
    app.add_handler(CommandHandler("startgame", start_game))
    app.add_handler(CommandHandler("join", join_game))
    app.add_handler(CommandHandler("begin", begin_game))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, play_word))
    
    # Xử lý lỗi
    app.add_error_handler(error_handler)

    # Chạy ứng dụng
    if os.getenv('WEBHOOK_MODE', 'false').lower() == 'true':
        # Chế độ webhook cho Render
        port = int(os.getenv('PORT', 10000))
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            webhook_url=os.getenv('WEBHOOK_URL'),
            secret_token=os.getenv('WEBHOOK_SECRET', ''),
            cert=os.getenv('SSL_CERT'),
            key=os.getenv('SSL_PRIVKEY')
        )
    else:
        # Chế độ polling cho development
        app.run_polling()

if __name__ == '__main__':
    main()
