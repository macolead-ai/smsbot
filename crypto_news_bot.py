import logging
import os
import sys
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get bot token from environment variable
BOT_TOKEN = os.environ.get('BOT_TOKEN')

# Quiz Data
QUIZ_QUESTIONS = [
    {
        "question": "1. What is the consensus mechanism used by Bitcoin?",
        "options": ["Proof of Stake", "Proof of Work", "Proof of History", "Proof of Burn"],
        "correct": 1
    },
    {
        "question": "2. What is a 'Seed Phrase'?",
        "options": ["A password for an exchange", "A list of words to recover a wallet", "The title of a crypto coin", "A transaction ID"],
        "correct": 1
    },
    {
        "question": "3. What does 'HODL' stand for in the crypto community?",
        "options": ["Hold On for Dear Life", "High Operations Digital Ledger", "Help Others Discover Liberty", "Highly Optimized Decentralized Layer"],
        "correct": 0
    },
    {
        "question": "4. Which of these is a 'Stablecoin'?",
        "options": ["Ethereum", "Dogecoin", "USDT", "Solana"],
        "correct": 2
    },
    {
        "question": "5. What is a 'Smart Contract'?",
        "options": ["A physical legal document", "Self-executing code on a blockchain", "A trading bot", "A digital signature"],
        "correct": 1
    }
]

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the quiz and reset user progress"""
    user = update.effective_user
    logger.info(f"User {user.id} started the quiz")
    
    context.user_data['score'] = 0
    context.user_data['question_index'] = 0
    
    welcome_text = (
        "👋 **Welcome to the Crypto Knowledge Test!**\n\n"
        "I will ask you 5 questions to determine if you are a newbie or an expert.\n\n"
        "Ready to start?"
    )
    
    keyboard = [[InlineKeyboardButton("🚀 Start Quiz", callback_data="quiz_0")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle quiz progression and answer checking"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # Check if this is an answer to a previous question
    if data.startswith("ans_"):
        parts = data.split("_")
        q_idx = int(parts[1])
        choice = int(parts[2])
        
        # Increment score if correct
        if choice == QUIZ_QUESTIONS[q_idx]["correct"]:
            context.user_data['score'] = context.user_data.get('score', 0) + 1
        
        next_q = q_idx + 1
    else:
        # Starting from the beginning
        next_q = 0

    # End of quiz logic
    if next_q >= len(QUIZ_QUESTIONS):
        score = context.user_data.get('score', 0)
        level = "Expert 🧠" if score >= 4 else "Newbie 🌱"
        
        final_text = (
            f"✅ **Test Completed!**\n\n"
            f"Your Score: {score}/5\n"
            f"Assessed Level: **{level}**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🙌 **Kudos for getting to test 5!**\n"
            "📅 **New class begins next week.**\n"
            "👋 Come back soon!\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        await query.edit_message_text(final_text, parse_mode='Markdown')
        return

    # Show next question
    q_data = QUIZ_QUESTIONS[next_q]
    keyboard = []
    for i, option in enumerate(q_data["options"]):
        keyboard.append([InlineKeyboardButton(option, callback_data=f"ans_{next_q}_{i}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"📝 **Question {next_q + 1}:**\n\n{q_data['question']}", reply_markup=reply_markup, parse_mode='Markdown')

async def run_bot():
    """Start the bot asynchronously"""
    if not BOT_TOKEN:
        logger.critical("FATAL: BOT_TOKEN is missing!")
        return

    try:
        application = Application.builder().token(BOT_TOKEN).build()
        
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CallbackQueryHandler(handle_quiz, pattern="^(quiz_|ans_)"))
        
        logger.info("Bot is now polling...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        
        stop_event = asyncio.Event()
        await stop_event.wait()
        
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
    finally:
        if 'application' in locals():
            await application.stop()
            await application.shutdown()

def main():
    """Main entry point"""
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.error(f"Main loop error: {e}")

if __name__ == '__main__':
    main()
