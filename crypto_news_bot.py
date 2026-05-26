import logging
import os
import io
import asyncio
import zipfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from pypdf import PdfReader, PdfWriter

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get bot token from environment variable
BOT_TOKEN = os.environ.get('BOT_TOKEN')

# Limits
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB (Telegram bot upload limit)
MAX_MERGE_FILES = 10

# Modes
MODE_MERGE = "merge"
MODE_SPLIT_WAIT_FILE = "split_wait_file"
MODE_SPLIT_WAIT_RANGE = "split_wait_text_range"


# ---------- Helpers ----------

def main_menu_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📎 Merge PDFs", callback_data="menu_merge")],
        [InlineKeyboardButton("✂️ Split PDF", callback_data="menu_split")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="menu_help")],
    ]
    return InlineKeyboardMarkup(keyboard)


def merge_controls_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("✅ Done — Merge Now", callback_data="merge_done")],
        [InlineKeyboardButton("🗑 Clear Files", callback_data="merge_clear")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="menu_home")],
    ]
    return InlineKeyboardMarkup(keyboard)


def reset_user_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop('mode', None)
    context.user_data.pop('merge_files', None)
    context.user_data.pop('split_file', None)


# ---------- Commands ----------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"User {user.id} started the bot")
    reset_user_state(context)

    welcome_text = (
        "👋 *Welcome to PDF Merger & Splitter Bot!*\n\n"
        "I can help you:\n"
        "• 📎 *Merge* multiple PDFs into one\n"
        "• ✂️ *Split* a PDF into pages or a custom range\n\n"
        f"_Max file size: 20 MB. Max files per merge: {MAX_MERGE_FILES}._\n\n"
        "Choose an option below:"
    )
    await update.message.reply_text(
        welcome_text, reply_markup=main_menu_markup(), parse_mode='Markdown'
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "ℹ️ *How to use this bot*\n\n"
        "*Merge PDFs:*\n"
        "1. Tap 📎 Merge PDFs\n"
        "2. Send 2 or more PDF files one by one\n"
        "3. Tap ✅ Done — Merge Now\n\n"
        "*Split PDF:*\n"
        "1. Tap ✂️ Split PDF\n"
        "2. Send a PDF file\n"
        "3. Choose: split every page OR enter a custom range (e.g. `1-3,5,7-9`)\n\n"
        "Use /cancel anytime to reset."
    )
    if update.message:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=main_menu_markup())
    else:
        await update.callback_query.edit_message_text(
            text, parse_mode='Markdown', reply_markup=main_menu_markup()
        )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_user_state(context)
    await update.message.reply_text(
        "❌ Operation cancelled. Use /start to begin again.",
        reply_markup=main_menu_markup(),
    )


# ---------- Menu callbacks ----------

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_home":
        reset_user_state(context)
        await query.edit_message_text(
            "🏠 *Main Menu*\nChoose an option below:",
            reply_markup=main_menu_markup(),
            parse_mode='Markdown',
        )

    elif data == "menu_help":
        await help_command(update, context)

    elif data == "menu_merge":
        context.user_data['mode'] = MODE_MERGE
        context.user_data['merge_files'] = []
        await query.edit_message_text(
            "📎 *Merge Mode*\n\n"
            "Send the PDFs you want to merge — one by one, *in the order* you want them combined.\n\n"
            f"You can send up to *{MAX_MERGE_FILES}* PDFs.\n"
            "When done, tap ✅ *Done — Merge Now* below.",
            reply_markup=merge_controls_markup(),
            parse_mode='Markdown',
        )

    elif data == "menu_split":
        context.user_data['mode'] = MODE_SPLIT_WAIT_FILE
        await query.edit_message_text(
            "✂️ *Split Mode*\n\nSend me the PDF file you want to split.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Main Menu", callback_data="menu_home")]]
            ),
        )

    elif data == "merge_clear":
        context.user_data['merge_files'] = []
        await query.edit_message_text(
            "🗑 Cleared. Send PDFs again to merge.",
            reply_markup=merge_controls_markup(),
            parse_mode='Markdown',
        )

    elif data == "merge_done":
        await do_merge(update, context)

    elif data.startswith("split_"):
        await handle_split_choice(update, context)


# ---------- Document handler ----------

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get('mode')
    doc = update.message.document
    if not doc:
        return

    if doc.mime_type != "application/pdf" and not (doc.file_name or "").lower().endswith(".pdf"):
        await update.message.reply_text("⚠️ Please send a PDF file (.pdf).")
        return

    if doc.file_size and doc.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(
            f"⚠️ File too large ({doc.file_size // (1024*1024)} MB). Max is 20 MB."
        )
        return

    if mode == MODE_MERGE:
        files = context.user_data.setdefault('merge_files', [])
        if len(files) >= MAX_MERGE_FILES:
            await update.message.reply_text(
                f"⚠️ You already sent {MAX_MERGE_FILES} files. Tap ✅ Done to merge."
            )
            return
        files.append({"file_id": doc.file_id, "name": doc.file_name or f"file_{len(files)+1}.pdf"})
        await update.message.reply_text(
            f"✅ Added *{doc.file_name}* ({len(files)} file(s) queued).",
            parse_mode='Markdown',
            reply_markup=merge_controls_markup(),
        )

    elif mode == MODE_SPLIT_WAIT_FILE:
        context.user_data['split_file'] = {"file_id": doc.file_id, "name": doc.file_name or "document.pdf"}
        try:
            tg_file = await context.bot.get_file(doc.file_id)
            buf = io.BytesIO()
            await tg_file.download_to_memory(out=buf)
            buf.seek(0)
            reader = PdfReader(buf)
            page_count = len(reader.pages)
            context.user_data['split_file']['pages'] = page_count
        except Exception as e:
            logger.error(f"Failed to read PDF: {e}")
            await update.message.reply_text("⚠️ Could not read that PDF. Try another file.")
            reset_user_state(context)
            return

        keyboard = [
            [InlineKeyboardButton("📄 Split into individual pages", callback_data="split_all")],
            [InlineKeyboardButton("🔢 Custom page range", callback_data="split_range")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="menu_home")],
        ]
        await update.message.reply_text(
            f"📄 Got *{doc.file_name}* — {page_count} page(s).\n\nHow do you want to split it?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown',
        )

    else:
        await update.message.reply_text(
            "Please pick an action first.", reply_markup=main_menu_markup()
        )


# ---------- Merge ----------

async def do_merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    files = context.user_data.get('merge_files', [])

    if len(files) < 2:
        await query.edit_message_text(
            "⚠️ You need at least *2 PDFs* to merge. Send more files.",
            reply_markup=merge_controls_markup(),
            parse_mode='Markdown',
        )
        return

    await query.edit_message_text(f"⏳ Merging {len(files)} PDFs… please wait.")

    writer = PdfWriter()
    try:
        for f in files:
            tg_file = await context.bot.get_file(f["file_id"])
            buf = io.BytesIO()
            await tg_file.download_to_memory(out=buf)
            buf.seek(0)
            reader = PdfReader(buf)
            for page in reader.pages:
                writer.add_page(page)

        out_buf = io.BytesIO()
        writer.write(out_buf)
        out_buf.seek(0)

        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=InputFile(out_buf, filename="merged.pdf"),
            caption=f"✅ Merged {len(files)} PDFs successfully!",
            reply_markup=main_menu_markup(),
        )
    except Exception as e:
        logger.error(f"Merge failed: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"❌ Merge failed: {e}",
            reply_markup=main_menu_markup(),
        )
    finally:
        reset_user_state(context)


# ---------- Split ----------

async def handle_split_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    split_file = context.user_data.get('split_file')

    if not split_file:
        await query.edit_message_text(
            "⚠️ No file found. Start again.", reply_markup=main_menu_markup()
        )
        return

    if data == "split_all":
        await query.edit_message_text("⏳ Splitting into individual pages…")
        await do_split(update, context, ranges=None)

    elif data == "split_range":
        await query.edit_message_text(
            f"🔢 Send the page range you want.\n\n"
            f"Total pages: *{split_file.get('pages')}*\n\n"
            "Examples:\n"
            "• `1-3` (pages 1 to 3 as one PDF)\n"
            "• `1,3,5` (each page as its own PDF)\n"
            "• `1-3,7,9-10` (mix)\n\n"
            "Use /cancel to abort.",
            parse_mode='Markdown',
        )
        context.user_data['mode'] = MODE_SPLIT_WAIT_RANGE


async def handle_text_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('mode') != MODE_SPLIT_WAIT_RANGE:
        return

    text = (update.message.text or "").strip()
    split_file = context.user_data.get('split_file')
    if not split_file:
        await update.message.reply_text("⚠️ No file. Start again with /start.")
        reset_user_state(context)
        return

    total = split_file.get('pages', 0)
    try:
        ranges = parse_ranges(text, total)
    except ValueError as e:
        await update.message.reply_text(f"⚠️ {e}\nTry again or /cancel.")
        return

    await update.message.reply_text(f"⏳ Splitting {len(ranges)} part(s)…")
    await do_split(update, context, ranges=ranges)


def parse_ranges(text: str, total_pages: int):
    """Parse '1-3,5,7-9' into list of (start, end) tuples, 1-indexed inclusive."""
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        raise ValueError("Empty range.")

    ranges = []
    for p in parts:
        if "-" in p:
            a, b = p.split("-", 1)
            a, b = int(a.strip()), int(b.strip())
            if a < 1 or b < 1 or a > total_pages or b > total_pages or a > b:
                raise ValueError(f"Invalid range '{p}'. PDF has {total_pages} page(s).")
            ranges.append((a, b))
        else:
            n = int(p)
            if n < 1 or n > total_pages:
                raise ValueError(f"Page {n} out of range. PDF has {total_pages} page(s).")
            ranges.append((n, n))
    return ranges


async def do_split(update: Update, context: ContextTypes.DEFAULT_TYPE, ranges=None):
    """Split the stored PDF. If ranges is None, split every page individually."""
    split_file = context.user_data.get('split_file')
    chat_id = update.effective_chat.id

    try:
        tg_file = await context.bot.get_file(split_file["file_id"])
        buf = io.BytesIO()
        await tg_file.download_to_memory(out=buf)
        buf.seek(0)
        reader = PdfReader(buf)
        total = len(reader.pages)

        if ranges is None:
            ranges = [(i + 1, i + 1) for i in range(total)]

        outputs = []
        base = os.path.splitext(split_file.get("name", "document.pdf"))[0]

        for (start, end) in ranges:
            writer = PdfWriter()
            for i in range(start - 1, end):
                writer.add_page(reader.pages[i])
            out = io.BytesIO()
            writer.write(out)
            out.seek(0)
            name = f"{base}_p{start}.pdf" if start == end else f"{base}_p{start}-{end}.pdf"
            outputs.append((name, out))

        # Zip if many outputs, else send individually
        if len(outputs) > 5:
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for name, data in outputs:
                    zf.writestr(name, data.getvalue())
            zip_buf.seek(0)
            await context.bot.send_document(
                chat_id=chat_id,
                document=InputFile(zip_buf, filename=f"{base}_split.zip"),
                caption=f"✅ Split into {len(outputs)} files (zipped).",
                reply_markup=main_menu_markup(),
            )
        else:
            for name, data in outputs:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=InputFile(data, filename=name),
                )
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Done — {len(outputs)} file(s) sent.",
                reply_markup=main_menu_markup(),
            )
    except Exception as e:
        logger.error(f"Split failed: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Split failed: {e}",
            reply_markup=main_menu_markup(),
        )
    finally:
        reset_user_state(context)


# ---------- Runner ----------

async def run_bot():
    if not BOT_TOKEN:
        logger.critical("FATAL: BOT_TOKEN is missing!")
        return

    try:
        application = Application.builder().token(BOT_TOKEN).build()

        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("cancel", cancel_command))
        application.add_handler(CallbackQueryHandler(menu_callback))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_range))

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
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.error(f"Main loop error: {e}")


if __name__ == '__main__':
    main()
