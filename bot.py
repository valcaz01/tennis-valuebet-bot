"""
Tennis Value Bet Bot — Point d'entrée principal
Lance le bot Telegram + le scheduler de scan automatique
"""

import logging
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler
from handlers import (
    cmd_start, cmd_help, cmd_scan, cmd_status,
    cmd_config, cmd_matches, button_callback
)
from config import BOT_TOKEN

import os
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


async def on_startup(app):
    """Appelé au démarrage du bot — charge le Elo + lance le scheduler."""
    # 1. Charger les ratings Elo
    from elo import load_elo_ratings
    logger.info("Chargement des ratings Elo...")
    await load_elo_ratings()
    logger.info("Ratings Elo chargés.")

    # 2. Lancer le scheduler
    from scheduler import start_scheduler
    await start_scheduler(app)


def main():
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

    # Startup : Elo + Scheduler
    app.post_init = on_startup

    logger.info("Bot lancé, en attente de messages...")
    app.run_polling()


if __name__ == "__main__":
    main()
