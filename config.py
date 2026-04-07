"""
Configuration centrale du bot
Remplir les variables d'environnement ou éditer directement ici
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ────────────────────────────────────────────────
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "TON_TOKEN_ICI")

# IDs des chats autorisés à recevoir les alertes (liste d'int)
# Laisser vide [] pour accepter tout le monde
ALLOWED_CHAT_IDS: list[int] = [8425473716]

# ── APIs ────────────────────────────────────────────────────
# The Odds API  → https://the-odds-api.com  (plan gratuit : 500 req/mois)
ODDS_API_KEY    = os.getenv("ODDS_API_KEY", "TON_ODDS_API_KEY")
ODDS_API_BASE   = "https://api.the-odds-api.com/v4"

# API-Tennis.com → https://api-tennis.com  (essai 14 jours puis 40$/mois)
APITENNIS_KEY   = os.getenv("APITENNIS_KEY", "TON_APITENNIS_KEY")
APITENNIS_BASE  = "https://api.api-tennis.com/tennis/"

# ── Paramètres value bet ────────────────────────────────────
# Edge minimum pour déclencher une alerte (ex: 0.05 = 5%)
MIN_EDGE        = float(os.getenv("MIN_EDGE", "0.05"))

# Fraction Kelly à utiliser (0.25 = quart de Kelly, recommandé)
KELLY_FRACTION  = float(os.getenv("KELLY_FRACTION", "0.25"))

# Bankroll de référence pour le calcul des mises (en €)
BANKROLL        = float(os.getenv("BANKROLL", "1000"))

# ── Poids des facteurs d'analyse ────────────────────────────
# Total doit faire 1.0
FACTOR_WEIGHTS = {
    "ranking":      0.20,   # Position ATP/WTA (réduit)
    "recent_form":  0.30,   # Victoires sur les derniers matchs (augmenté)
    "surface":      0.25,   # Win rate sur la surface en cours (augmenté)
    "h2h":          0.15,   # Historique des confrontations directes
    "fatigue":      0.10,   # Nombre de matchs joués récemment
}

# ── Scheduler ───────────────────────────────────────────────
# Intervalle de scan automatique (en minutes)
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL", "30"))

# ── Tournois à couvrir (The Odds API) ───────────────────────
# Clés The Odds API — les matchs sont récupérés ici
TENNIS_SPORTS = [
    "tennis_atp_french_open",
    "tennis_wta_french_open",
    "tennis_atp_us_open",
    "tennis_wta_us_open",
    "tennis_atp_wimbledon",
    "tennis_wta_wimbledon",
    "tennis_atp_australian_open",
    "tennis_wta_australian_open",
    "tennis_atp_monte_carlo_masters",
    "tennis_atp_miami_open",
    "tennis_atp_madrid_open",
    "tennis_atp_rome_masters",
    "tennis_atp_indian_wells",
    "tennis_atp_canadian_open",
    "tennis_atp_cincinnati_masters",
    "tennis_atp_shanghai_masters",
    "tennis_atp_paris_masters",
    "tennis_wta_miami_open",
    "tennis_wta_madrid_open",
    "tennis_wta_rome_masters",
    "tennis_wta_indian_wells",
    "tennis_wta_canadian_open",
    "tennis_wta_cincinnati",
    "tennis_wta_beijing",
    "tennis_atp",
    "tennis_wta",
]

# Région bookmakers (uk, eu, us, au)
ODDS_REGIONS = "eu"

# Bookmakers de référence pour la démarginisation
REFERENCE_BOOKMAKERS = ["bet365", "unibet", "betclic", "winamax", "pinnacle"]
