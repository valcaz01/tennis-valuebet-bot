"""
Handlers des commandes Telegram
"""

import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from data_fetcher import fetch_upcoming_matches
from analyzer import scan_all_matches, is_today_or_tomorrow, get_surface_from_tournament
from totals_analyzer import analyze_totals, is_today_or_tomorrow as totals_filter
from elo import get_player_withdrawals
from tracker import record_bet, verify_results, get_stats
from formatter import (
    fmt_scan_compact, fmt_totals_compact,
    fmt_match_list, fmt_status, escape
)
from config import (
    MIN_EDGE, KELLY_FRACTION, BANKROLL,
    SCAN_INTERVAL_MINUTES, FACTOR_WEIGHTS, ALLOWED_CHAT_IDS
)

logger = logging.getLogger(__name__)


def is_authorized(update: Update) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    return update.effective_chat.id in ALLOWED_CHAT_IDS


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    keyboard = [
        [
            InlineKeyboardButton("🔍 Scanner ML", callback_data="scan"),
            InlineKeyboardButton("📏 Over/Under", callback_data="totals"),
        ],
        [
            InlineKeyboardButton("📋 Matchs",     callback_data="matches"),
            InlineKeyboardButton("📊 Résultats",  callback_data="results"),
        ],
        [
            InlineKeyboardButton("❓ Aide",       callback_data="help"),
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
        "/scan — Value bets Match Winner \\(J et J\\+1\\)\n"
        "/totals — Value bets Over/Under jeux \\(J et J\\+1\\)\n"
        "/matches — Liste les matchs à venir\n"
        "/results — Performances et ROI du bot\n"
        "/status — Configuration actuelle\n"
        "/help — Ce message\n\n"
        "*Comment ça marche ?*\n"
        "1\\. Récupération des matchs et cotes\n"
        "2\\. Stats joueurs via API\\-Tennis \\+ Elo calculé\n"
        "3\\. 6 facteurs : Elo, Performance, Forme, Marché, H2H, Contexte\n"
        "4\\. Détection des écarts significatifs avec le marché\n"
        "5\\. Alerte si edge ≥ 5%"
    )
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    msg = await update.effective_message.reply_text(
        "⏳ Scan ML en cours\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2
    )

    try:
        matches = await fetch_upcoming_matches()
        upcoming = [m for m in matches if is_today_or_tomorrow(m.commence_time)]
        vbs = await scan_all_matches(upcoming)

        # Enregistrer les bets pour le tracking
        for vb in vbs:
            record_bet(
                bet_type="ml", match_id=vb.match.id,
                tournament=vb.match.tournament,
                player=vb.player, opponent=vb.opponent,
                odds=vb.best_odds, edge=vb.edge,
                p_estimated=vb.p_estimated,
                kelly_stake=vb.kelly_stake,
                commence_time=vb.match.commence_time,
            )

        # Collecter les alertes santé
        withdrawals = {}
        for vb in vbs:
            for name in [vb.player, vb.opponent]:
                if name not in withdrawals:
                    withdrawals[name] = get_player_withdrawals(name)

        # Un seul message compact
        await msg.edit_text(
            fmt_scan_compact(vbs, len(upcoming), withdrawals),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    except Exception as e:
        logger.exception("Erreur lors du scan")
        await msg.edit_text(f"❌ Erreur : {escape(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_totals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    msg = await update.effective_message.reply_text(
        "⏳ Analyse Over/Under en cours\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2
    )

    try:
        matches = await fetch_upcoming_matches()
        upcoming = [m for m in matches if totals_filter(m.commence_time)]

        all_totals = []
        for match in upcoming:
            if not match.totals_odds:
                continue
            surface = get_surface_from_tournament(match.tournament)
            bets = analyze_totals(match, surface)
            all_totals.extend(bets)

        all_totals.sort(key=lambda b: b.edge, reverse=True)
        top_totals = all_totals[:5]

        # Enregistrer les bets
        for tb in top_totals:
            record_bet(
                bet_type=tb.side, match_id=tb.match.id,
                tournament=tb.match.tournament,
                player=tb.match.player1, opponent=tb.match.player2,
                odds=tb.best_odds, edge=tb.edge,
                p_estimated=0, kelly_stake=0,
                commence_time=tb.match.commence_time,
                side=tb.side, line=tb.line,
            )

        # Un seul message compact
        await msg.edit_text(
            fmt_totals_compact(top_totals, len(upcoming)),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    except Exception as e:
        logger.exception("Erreur lors du scan totals")
        await msg.edit_text(f"❌ Erreur : {escape(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_matches(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    msg = await update.effective_message.reply_text(
        "⏳ Récupération des matchs\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2
    )
    try:
        matches = await fetch_upcoming_matches()
        upcoming = [m for m in matches if is_today_or_tomorrow(m.commence_time)]
        await msg.edit_text(
            fmt_match_list(upcoming), parse_mode=ParseMode.MARKDOWN_V2
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


async def cmd_results(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    msg = await update.effective_message.reply_text(
        "⏳ Vérification des résultats\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2
    )

    try:
        verified = await verify_results()
        stats_30d = get_stats(days=30)
        stats_all = get_stats(days=0)

        def fmt_section(label, s):
            if s["count"] == 0:
                return f"*{label}* : aucun pari vérifié"
            emoji = "🟢" if s["profit"] > 0 else ("🔴" if s["profit"] < 0 else "⚪")
            return (
                f"*{label}*\n"
                f"├ Paris : `{s['count']}` \\({s['won']}W \\- {s['lost']}L\\)\n"
                f"├ Win rate : `{s['win_rate']*100:.0f}%`\n"
                f"├ Profit : {emoji} `{s['profit']:+.1f}u`\n"
                f"└ ROI : `{s['roi']:+.1f}%`"
            )

        lines = [
            f"📊 *Performances du bot*",
            f"",
            f"_Résultats vérifiés : {verified} nouveau\\(x\\)_",
            f"_En attente : {stats_all['pending']} pari\\(s\\)_",
            f"",
            f"📅 *30 derniers jours*",
            fmt_section("Match Winner", stats_30d["ml"]),
            f"",
            fmt_section("Over/Under", stats_30d["totals"]),
            f"",
            fmt_section("Global", stats_30d["all"]),
            f"",
            f"📈 *Depuis le début*",
            fmt_section("Global", stats_all["all"]),
        ]

        await msg.edit_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    except Exception as e:
        logger.exception("Erreur résultats")
        await msg.edit_text(f"❌ Erreur : {escape(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)


async def button_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action = query.data
    if action == "scan":
        await cmd_scan(update, ctx)
    elif action == "matches":
        await cmd_matches(update, ctx)
    elif action == "totals":
        await cmd_totals(update, ctx)
    elif action == "results":
        await cmd_results(update, ctx)
    elif action == "status":
        await cmd_status(update, ctx)
    elif action == "help":
        await cmd_help(update, ctx)


async def send_valuebet_alert(app, chat_id: int, vb):
    """Envoie une alerte ML (appelé par le scheduler)."""
    try:
        withdrawals = {
            vb.player: get_player_withdrawals(vb.player),
            vb.opponent: get_player_withdrawals(vb.opponent),
        }
        await app.bot.send_message(
            chat_id=chat_id,
            text=fmt_scan_compact([vb], 1, withdrawals),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except Exception as e:
        logger.error(f"Erreur envoi alerte à {chat_id}: {e}")
