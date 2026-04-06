"""
Collecte de données : cotes (The Odds API) + stats joueurs (API-Sports)
"""

import logging
import aiohttp
from dataclasses import dataclass, field
from typing import Optional
from config import (
    ODDS_API_KEY, ODDS_API_BASE,
    APISPORTS_KEY, APISPORTS_BASE,
    TENNIS_SPORTS, ODDS_REGIONS, REFERENCE_BOOKMAKERS
)

logger = logging.getLogger(__name__)


@dataclass
class Match:
    """Représente un match avec ses cotes et ses stats"""
    id: str
    tournament: str
    player1: str
    player2: str
    commence_time: str
    # Cotes brutes {bookmaker: {player: cote}}
    odds: dict = field(default_factory=dict)
    # Stats joueurs {player: {stat: valeur}}
    stats: dict = field(default_factory=dict)


# ── The Odds API ──────────────────────────────────────────────────────────────

async def fetch_upcoming_matches() -> list[Match]:
    """Récupère tous les matchs à venir avec leurs cotes."""
    matches: list[Match] = []

    async with aiohttp.ClientSession() as session:
        for sport in TENNIS_SPORTS:
            url = f"{ODDS_API_BASE}/sports/{sport}/odds"
            params = {
                "apiKey":     ODDS_API_KEY,
                "regions":    ODDS_REGIONS,
                "markets":    "h2h",
                "oddsFormat": "decimal",
            }

            try:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 404:
                        # Tournoi pas en cours actuellement
                        continue
                    if resp.status != 200:
                        logger.warning(f"Odds API {sport}: HTTP {resp.status}")
                        continue

                    data = await resp.json()
                    remaining = resp.headers.get("x-requests-remaining", "?")
                    logger.info(f"{sport}: {len(data)} matchs trouvés | {remaining} requêtes restantes")

                    for event in data:
                        match = Match(
                            id=event["id"],
                            tournament=event.get("sport_title", sport),
                            player1=event["home_team"],
                            player2=event["away_team"],
                            commence_time=event["commence_time"],
                        )
                        # Extraire les cotes par bookmaker
                        for bm in event.get("bookmakers", []):
                            bm_key = bm["key"]
                            for market in bm.get("markets", []):
                                if market["key"] == "h2h":
                                    match.odds[bm_key] = {
                                        o["name"]: o["price"]
                                        for o in market["outcomes"]
                                    }
                        matches.append(match)

            except aiohttp.ClientError as e:
                logger.error(f"Erreur réseau Odds API ({sport}): {e}")

    logger.info(f"Total matchs récupérés : {len(matches)}")
    return matches


def get_best_odds(match: Match, player: str) -> Optional[float]:
    """Retourne la meilleure cote disponible pour un joueur."""
    best = None
    for bm_odds in match.odds.values():
        cote = bm_odds.get(player)
        if cote and (best is None or cote > best):
            best = cote
    return best


def get_average_odds(match: Match, player: str,
                     bookmakers: list[str] | None = None) -> Optional[float]:
    """Retourne la cote moyenne sur les bookmakers de référence."""
    target = bookmakers or REFERENCE_BOOKMAKERS
    values = []
    for bm, bm_odds in match.odds.items():
        if bm in target and player in bm_odds:
            values.append(bm_odds[player])
    # Fallback sur tous les bookmakers si aucun de référence trouvé
    if not values:
        for bm_odds in match.odds.values():
            cote = bm_odds.get(player)
            if cote:
                values.append(cote)
    return sum(values) / len(values) if values else None


# ── API-Sports (tennis stats) ─────────────────────────────────────────────────

async def fetch_player_stats(player_name: str) -> dict:
    """
    Récupère les stats d'un joueur via API-Sports.
    Retourne un dict avec ranking, recent_form, surface_win_rates, h2h dispo.
    """
    headers = {"x-apisports-key": APISPORTS_KEY}

    async with aiohttp.ClientSession(headers=headers) as session:
        # 1. Recherche du joueur
        player_id = await _get_player_id(session, player_name)
        if not player_id:
            logger.warning(f"Joueur non trouvé : {player_name}")
            return {}

        # 2. Stats générales
        stats = await _get_player_ranking_stats(session, player_id)

        return stats


async def _get_player_id(session: aiohttp.ClientSession, name: str) -> Optional[int]:
    """Cherche l'ID d'un joueur par son nom."""
    try:
        async with session.get(
            f"{APISPORTS_BASE}/players",
            params={"search": name},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            results = data.get("response", [])
            if results:
                return results[0]["id"]
    except aiohttp.ClientError as e:
        logger.error(f"Erreur API-Sports player search: {e}")
    return None


async def _get_player_ranking_stats(session: aiohttp.ClientSession,
                                     player_id: int) -> dict:
    """Récupère le ranking et les statistiques récentes d'un joueur."""
    stats = {
        "ranking": None,
        "ranking_points": None,
        "recent_form": [],      # Liste des résultats récents (True=victoire)
        "surface_win_rates": {},  # {"clay": 0.7, "hard": 0.6, ...}
        "fatigue_score": 0,     # Nb de matchs joués dans les 7 derniers jours
    }

    try:
        async with session.get(
            f"{APISPORTS_BASE}/rankings",
            params={"player": player_id},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                results = data.get("response", [])
                if results:
                    latest = results[0]
                    stats["ranking"] = latest.get("position")
                    stats["ranking_points"] = latest.get("points")

        # Stats par surface (si disponibles)
        for surface in ["clay", "hard", "grass", "carpet"]:
            async with session.get(
                f"{APISPORTS_BASE}/statistics",
                params={"player": player_id, "surface": surface},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("response", [])
                    if results:
                        r = results[0]
                        wins = r.get("wins", 0)
                        losses = r.get("losses", 0)
                        total = wins + losses
                        if total > 0:
                            stats["surface_win_rates"][surface] = wins / total

    except aiohttp.ClientError as e:
        logger.error(f"Erreur API-Sports stats: {e}")

    return stats


async def fetch_h2h(player1_name: str, player2_name: str) -> dict:
    """Récupère l'historique des confrontations directes entre deux joueurs."""
    headers = {"x-apisports-key": APISPORTS_KEY}

    async with aiohttp.ClientSession(headers=headers) as session:
        id1 = await _get_player_id(session, player1_name)
        id2 = await _get_player_id(session, player2_name)

        if not id1 or not id2:
            return {"p1_wins": 0, "p2_wins": 0, "total": 0}

        try:
            async with session.get(
                f"{APISPORTS_BASE}/h2h",
                params={"h2h": f"{id1}-{id2}"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return {"p1_wins": 0, "p2_wins": 0, "total": 0}
                data = await resp.json()
                games = data.get("response", [])

                p1_wins = sum(
                    1 for g in games
                    if g.get("winner", {}).get("id") == id1
                )
                return {
                    "p1_wins": p1_wins,
                    "p2_wins": len(games) - p1_wins,
                    "total": len(games)
                }
        except aiohttp.ClientError as e:
            logger.error(f"Erreur API-Sports H2H: {e}")
            return {"p1_wins": 0, "p2_wins": 0, "total": 0}
