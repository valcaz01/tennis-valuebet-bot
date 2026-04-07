"""
Module Elo — Calcul des ratings Elo pour les joueurs ATP/WTA
Charge les résultats jour par jour sur les derniers mois via API-Tennis.com.

Formule Elo standard :
  - Expected score : E = 1 / (1 + 10^((Rb - Ra) / 400))
  - New rating : Ra' = Ra + K * (S - E)
"""

import logging
import aiohttp
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Optional

from config import APITENNIS_KEY, APITENNIS_BASE

logger = logging.getLogger(__name__)

# ── Constantes Elo ────────────────────────────────────────────────────────────
DEFAULT_ELO = 1500
K_FACTOR = 32
K_FACTOR_NEW = 48
MATCHES_THRESHOLD = 30
SURFACE_K_FACTOR = 40

# Nombre de jours à charger pour construire le Elo
DAYS_TO_LOAD = 90


@dataclass
class PlayerElo:
    """Ratings Elo d'un joueur."""
    name: str
    player_key: int
    elo_global: float = DEFAULT_ELO
    elo_hard: float = DEFAULT_ELO
    elo_clay: float = DEFAULT_ELO
    elo_grass: float = DEFAULT_ELO
    matches_played: int = 0


# Cache global
_elo_ratings: dict[int, PlayerElo] = {}
_elo_loaded: bool = False


# ── Calcul Elo ────────────────────────────────────────────────────────────────

def expected_score(rating_a: float, rating_b: float) -> float:
    """Probabilité attendue que le joueur A batte le joueur B."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def update_elo(winner_elo: float, loser_elo: float, k: float) -> tuple[float, float]:
    """Met à jour les ratings après un match."""
    e_winner = expected_score(winner_elo, loser_elo)
    new_winner = winner_elo + k * (1.0 - e_winner)
    new_loser = loser_elo + k * (0.0 - (1.0 - e_winner))
    return new_winner, new_loser


def get_k_factor(matches_played: int) -> float:
    if matches_played < MATCHES_THRESHOLD:
        return K_FACTOR_NEW
    return K_FACTOR


# ── API ───────────────────────────────────────────────────────────────────────

async def _api_tennis_request(session: aiohttp.ClientSession, params: dict) -> dict:
    params["APIkey"] = APITENNIS_KEY
    try:
        async with session.get(
            APITENNIS_BASE,
            params=params,
            timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            if resp.status != 200:
                return {}
            data = await resp.json()
            if data.get("success") != 1:
                return {}
            return data
    except Exception as e:
        logger.debug(f"Erreur API-Tennis Elo: {e}")
        return {}


def _detect_surface(tournament_name: str) -> str:
    name = (tournament_name or "").lower()
    clay_keywords = ["roland garros", "french open", "monte carlo", "monte-carlo",
                     "madrid", "rome", "barcelona", "buenos aires", "rio",
                     "lyon", "hamburg", "bastad", "umag", "kitzbuhel",
                     "gstaad", "bucharest", "marrakech"]
    grass_keywords = ["wimbledon", "queens", "queen's", "halle",
                      "s-hertogenbosch", "eastbourne", "mallorca", "newport"]
    if any(t in name for t in clay_keywords):
        return "clay"
    if any(t in name for t in grass_keywords):
        return "grass"
    return "hard"


def _process_match(winner_key: int, winner_name: str,
                   loser_key: int, loser_name: str,
                   surface: str):
    """Traite un match et met à jour les ratings Elo."""
    if winner_key not in _elo_ratings:
        _elo_ratings[winner_key] = PlayerElo(name=winner_name, player_key=winner_key)
    if loser_key not in _elo_ratings:
        _elo_ratings[loser_key] = PlayerElo(name=loser_name, player_key=loser_key)

    winner = _elo_ratings[winner_key]
    loser = _elo_ratings[loser_key]

    # Elo Global
    k = (get_k_factor(winner.matches_played) + get_k_factor(loser.matches_played)) / 2
    new_w, new_l = update_elo(winner.elo_global, loser.elo_global, k)
    winner.elo_global = new_w
    loser.elo_global = new_l

    # Elo Surface
    if surface == "clay":
        new_w, new_l = update_elo(winner.elo_clay, loser.elo_clay, SURFACE_K_FACTOR)
        winner.elo_clay = new_w
        loser.elo_clay = new_l
    elif surface == "grass":
        new_w, new_l = update_elo(winner.elo_grass, loser.elo_grass, SURFACE_K_FACTOR)
        winner.elo_grass = new_w
        loser.elo_grass = new_l
    else:
        new_w, new_l = update_elo(winner.elo_hard, loser.elo_hard, SURFACE_K_FACTOR)
        winner.elo_hard = new_w
        loser.elo_hard = new_l

    winner.matches_played += 1
    loser.matches_played += 1


# ── Chargement ────────────────────────────────────────────────────────────────

async def load_elo_ratings():
    """
    Charge les résultats des X derniers jours et calcule les Elo.
    Chaque jour = 1 requête API.
    """
    global _elo_loaded
    if _elo_loaded:
        return

    logger.info(f"Calcul des ratings Elo — chargement des {DAYS_TO_LOAD} derniers jours...")

    today = datetime.now(timezone.utc).date()
    total_matches = 0
    days_loaded = 0

    async with aiohttp.ClientSession() as session:
        # Parcourir les jours du plus ancien au plus récent
        for i in range(DAYS_TO_LOAD, 0, -1):
            day = today - timedelta(days=i)
            date_str = day.strftime("%Y-%m-%d")

            data = await _api_tennis_request(session, {
                "method": "get_fixtures",
                "date_start": date_str,
                "date_stop": date_str,
            })

            results = data.get("result", [])
            if not results:
                continue

            day_matches = 0
            for match in results:
                if match.get("event_status") != "Finished":
                    continue
                winner = match.get("event_winner")
                if not winner:
                    continue

                first_key = match.get("first_player_key")
                second_key = match.get("second_player_key")
                first_name = match.get("event_first_player", "")
                second_name = match.get("event_second_player", "")
                tournament = match.get("tournament_name", "")

                if not first_key or not second_key:
                    continue

                # Ignorer les doubles
                event_type = match.get("event_type_type", "")
                if "double" in event_type.lower():
                    continue

                surface = _detect_surface(tournament)

                if winner == "First Player":
                    _process_match(first_key, first_name, second_key, second_name, surface)
                elif winner == "Second Player":
                    _process_match(second_key, second_name, first_key, first_name, surface)

                day_matches += 1

            total_matches += day_matches
            days_loaded += 1

    _elo_loaded = True
    logger.info(f"Elo calculé : {len(_elo_ratings)} joueurs, {total_matches} matchs sur {days_loaded} jours")

    # Log top 10
    top = sorted(_elo_ratings.values(), key=lambda p: p.elo_global, reverse=True)[:10]
    for i, p in enumerate(top, 1):
        logger.info(f"  #{i} {p.name}: Elo {p.elo_global:.0f} "
                    f"(H:{p.elo_hard:.0f} C:{p.elo_clay:.0f} G:{p.elo_grass:.0f})")


# ── Accès aux ratings ─────────────────────────────────────────────────────────

def get_player_elo(player_key: int) -> Optional[PlayerElo]:
    return _elo_ratings.get(player_key)


def get_elo_by_name(player_name: str) -> Optional[PlayerElo]:
    """Cherche un joueur par nom (correspondance partielle)."""
    name_lower = player_name.lower().strip()

    # Recherche exacte
    for elo in _elo_ratings.values():
        if elo.name.lower().strip() == name_lower:
            return elo

    # Recherche par nom de famille
    parts = name_lower.split()
    target_surname = parts[-1] if parts else ""
    for elo in _elo_ratings.values():
        elo_parts = elo.name.lower().split()
        elo_surname = elo_parts[-1] if elo_parts else ""
        if target_surname and len(target_surname) > 2 and target_surname == elo_surname:
            return elo

    # Recherche souple
    for elo in _elo_ratings.values():
        if len(target_surname) > 2 and target_surname in elo.name.lower():
            return elo

    return None


def get_surface_elo(player_key: int, surface: str) -> float:
    elo = _elo_ratings.get(player_key)
    if not elo:
        return DEFAULT_ELO
    surface = surface.lower()
    if surface == "clay":
        return elo.elo_clay
    elif surface == "grass":
        return elo.elo_grass
    return elo.elo_hard


def elo_win_probability(elo_a: float, elo_b: float) -> float:
    """Calcule la probabilité de victoire du joueur A basée sur le Elo."""
    return expected_score(elo_a, elo_b)
