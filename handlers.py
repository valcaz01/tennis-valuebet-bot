"""
Handlers des commandes Telegram
"""

import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from data_fetcher import fetch_upcoming_matches
from analyzer import scan_all_matches, is_today
from formatter import (
    fmt_valuebet_alert, fmt_scan_summary,
    fmt_match_list, fmt_status, escape
)
from config import (
    MIN_EDGE, KELLY_FRACTION, BANKROLL,
    SCAN_INTERVAL_MINUTES, FACTOR_WEIGHTS, ALLOWED_CHAT_IDS
)

logger = logging.getLogger(__name__)


def is_authorized(update: Update) -> bool:
    """Vérifie si le chat est autorisé."""
    if not ALLOWED_CHAT_IDS:
        return True
    return update.effective_chat.id in ALLOWED_CHAT_IDS


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    keyboard = [
        [
            InlineKeyboardButton("🔍 Scanner maintenant", callback_data="scan"),
            InlineKeyboardButton("📋 Matchs du jour",     callback_data="matches"),
        ],
        [
            InlineKeyboardButton("⚙️ Configuration",      callback_data="status"),
            InlineKeyboardButton("❓ Aide",               callback_data="help"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🎾 *Tennis Value Bet Bot*\n\n"
        "Je scanne les matchs ATP/WTA et détecte les paris à valeur positive "
        "en comparant les cotes du marché à mes probabilités estimées\\.\n\n"
        "Utilise les boutons ou les commandes ci\\-dessous\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=reply_markup,
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    text = (
        "❓ *Commandes disponibles*\n\n"
        "/scan — Lance un scan immédiat des matchs du jour\n"
        "/matches — Liste les matchs du jour avec leurs cotes\n"
        "/status — Affiche la configuration actuelle\n"
        "/config — Modifie les paramètres \\(soon\\)\n"
        "/help — Ce message\n\n"
        "*Comment ça marche ?*\n"
        "1\\. Je récupère les matchs et cotes via The Odds API\n"
        "2\\. Je récupère les stats joueurs via API\\-Tennis\\.com\n"
        "3\\. Je calcule une probabilité estimée \\(ranking, forme, surface, H2H, fatigue\\)\n"
        "4\\. Je compare à la probabilité implicite du marché\n"
        "5\\. Si l'edge dépasse le seuil configuré → alerte\\!"
    )
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    msg = await update.effective_message.reply_text(
        "⏳ Scan en cours\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2
    )

    try:
        matches = await fetch_upcoming_matches()
        # Filtrer uniquement les matchs du jour
        today_matches = [m for m in matches if is_today(m.commence_time)]
        vbs = await scan_all_matches(today_matches)

        await msg.edit_text(
            fmt_scan_summary(vbs, len(today_matches)),
            parse_mode=ParseMode.MARKDOWN_V2
        )

        for vb in vbs:
            await update.effective_message.reply_text(
                fmt_valuebet_alert(vb),
                parse_mode=ParseMode.MARKDOWN_V2
            )

    except Exception as e:
        logger.exception("Erreur lors du scan")
        await msg.edit_text(f"❌ Erreur : {escape(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_matches(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    msg = await update.effective_message.reply_text(
        "⏳ Récupération des matchs du jour\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2
    )
    try:
        matches = await fetch_upcoming_matches()
        # Filtrer uniquement les matchs du jour
        today_matches = [m for m in matches if is_today(m.commence_time)]
        await msg.edit_text(
            fmt_match_list(today_matches), parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as e:
        logger.exception("Erreur récupération matchs")
        await msg.edit_text(f"❌ Erreur : {escape(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    config = {
        "min_edge":       MIN_EDGE,
        "kelly_fraction": KELLY_FRACTION,
        "bankroll":       BANKROLL,
        "scan_interval":  SCAN_INTERVAL_MINUTES,
        "weights":        FACTOR_WEIGHTS,
    }
    await update.effective_message.reply_text(
        fmt_status(config), parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_config(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await update.effective_message.reply_text(
        "⚙️ *Configuration*\n\n"
        "Pour modifier les paramètres, éditez le fichier `\\.env` ou `config\\.py`\\.\n\n"
        "Variables disponibles :\n"
        "• `MIN_EDGE` \\— Edge minimum \\(défaut : 0\\.05\\)\n"
        "• `KELLY_FRACTION` \\— Fraction Kelly \\(défaut : 0\\.25\\)\n"
        "• `BANKROLL` \\— Bankroll de référence en € \\(défaut : 1000\\)\n"
        "• `SCAN_INTERVAL` \\— Minutes entre deux scans \\(défaut : 30\\)\n",
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def button_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Gère les clics sur les boutons inline."""
    query = update.callback_query
    await query.answer()

    action = query.data
    if action == "scan":
        await cmd_scan(update, ctx)
    elif action == "matches":
        await cmd_matches(update, ctx)
    elif action == "status":
        await cmd_status(update, ctx)
    elif action == "help":
        await cmd_help(update, ctx)


async def send_valuebet_alert(app, chat_id: int, vb):
    """Envoie une alerte value bet à un chat donné (appelé par le scheduler)."""
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text=fmt_valuebet_alert(vb),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except Exception as e:
        logger.error(f"Erreur envoi alerte à {chat_id}: {e}")
