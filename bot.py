"""
Tennis Value Bet Bot — Point d'entrée principal
Lance le bot Telegram + le scheduler de scan automatique
"""

import asyncio
import logging
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler
from scheduler import start_scheduler
from handlers import (
    cmd_start, cmd_help, cmd_scan, cmd_status,
    cmd_config, cmd_matches, button_callback
)
from config import BOT_TOKEN

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Démarrage du Tennis Value Bet Bot...")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commandes
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("scan",    cmd_scan))
    app.add_handler(CommandHandler("matches", cmd_matches))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("config",  cmd_config))

    # Boutons inline
    app.add_handler(CallbackQueryHandler(button_callback))

    # Scheduler (scan automatique)
    await start_scheduler(app)

    logger.info("Bot lancé, en attente de messages...")
    await app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
