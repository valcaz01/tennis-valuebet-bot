"""
Scheduler : scan automatique toutes les X minutes
"""

import logging
import json
import os
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from data_fetcher import fetch_upcoming_matches
from analyzer import scan_all_matches
from config import SCAN_INTERVAL_MINUTES, ALLOWED_CHAT_IDS

logger = logging.getLogger(__name__)

# Fichier de persistance des value bets déjà envoyés (évite les doublons)
SENT_FILE = "data/sent_valuebets.json"


def load_sent_ids() -> set[str]:
    """Charge les IDs des value bets déjà envoyés."""
    if not os.path.exists(SENT_FILE):
        return set()
    try:
        with open(SENT_FILE) as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_sent_id(match_id: str, player: str):
    """Enregistre un value bet comme envoyé."""
    sent = load_sent_ids()
    sent.add(f"{match_id}_{player}")
    os.makedirs("data", exist_ok=True)
    with open(SENT_FILE, "w") as f:
        json.dump(list(sent), f)


async def run_scan(app):
    """Tâche exécutée par le scheduler."""
    logger.info(f"[Scheduler] Démarrage scan automatique — {datetime.now(timezone.utc).strftime('%H:%M UTC')}")

    try:
        matches = await fetch_upcoming_matches()
        vbs = await scan_all_matches(matches)

        if not vbs:
            logger.info("[Scheduler] Aucun value bet détecté")
            return

        sent_ids = load_sent_ids()
        # Déterminer les chats à notifier
        chat_ids = ALLOWED_CHAT_IDS if ALLOWED_CHAT_IDS else []

        if not chat_ids:
            logger.warning("[Scheduler] Aucun chat_id configuré dans ALLOWED_CHAT_IDS. "
                           "Ajoute ton chat_id dans config.py pour recevoir les alertes automatiques.")
            return

        new_count = 0
        for vb in vbs:
            key = f"{vb.match.id}_{vb.player}"
            if key in sent_ids:
                logger.debug(f"[Scheduler] Déjà envoyé : {vb.player}")
                continue

            # Importer ici pour éviter la circularité
            from handlers import send_valuebet_alert
            for chat_id in chat_ids:
                await send_valuebet_alert(app, chat_id, vb)

            save_sent_id(vb.match.id, vb.player)
            new_count += 1

        logger.info(f"[Scheduler] {new_count} nouvelle(s) alerte(s) envoyée(s)")

    except Exception as e:
        logger.exception(f"[Scheduler] Erreur lors du scan automatique : {e}")


async def start_scheduler(app):
    """Initialise et lance le scheduler APScheduler."""
    scheduler = AsyncIOScheduler(timezone="UTC")

    scheduler.add_job(
        run_scan,
        trigger=IntervalTrigger(minutes=SCAN_INTERVAL_MINUTES),
        args=[app],
        id="auto_scan",
        name=f"Scan automatique toutes les {SCAN_INTERVAL_MINUTES} min",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(f"Scheduler démarré — scan toutes les {SCAN_INTERVAL_MINUTES} minutes")
    return scheduler
