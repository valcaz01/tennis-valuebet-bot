"""
Collecte de données :
  - Cotes → The Odds API
  - Stats joueurs, rankings, H2H → API-Tennis.com
"""

import logging
import aiohttp
from dataclasses import dataclass, field
from typing import Optional
from config import (
    ODDS_API_KEY, ODDS_API_BASE,
    APITENNIS_KEY, APITENNIS_BASE,
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
    odds: dict = field(default_factory=dict)        # h2h: {bookmaker: {player: cote}}
    totals_odds: dict = field(default_factory=dict)  # totals: {bookmaker: {line: {over: cote, under: cote}}}
    stats: dict = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════════════
#  THE ODDS API — Récupération des matchs et cotes
# ══════════════════════════════════════════════════════════════════════════════

async def fetch_upcoming_matches() -> list[Match]:
    """Récupère tous les matchs à venir avec leurs cotes."""
    matches: list[Match] = []

    async with aiohttp.ClientSession() as session:
        for sport in TENNIS_SPORTS:
            url = f"{ODDS_API_BASE}/sports/{sport}/odds"
            params = {
                "apiKey":     ODDS_API_KEY,
                "regions":    ODDS_REGIONS,
                "markets":    "h2h,totals",
                "oddsFormat": "decimal",
            }

            try:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 404:
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
                        for bm in event.get("bookmakers", []):
                            bm_key = bm["key"]
                            for market in bm.get("markets", []):
                                if market["key"] == "h2h":
                                    match.odds[bm_key] = {
                                        o["name"]: o["price"]
                                        for o in market["outcomes"]
                                    }
                                elif market["key"] == "totals":
                                    # Stocker over/under par ligne
                                    for o in market["outcomes"]:
                                        line = o.get("point")
                                        if line is not None:
                                            if bm_key not in match.totals_odds:
                                                match.totals_odds[bm_key] = {}
                                            if line not in match.totals_odds[bm_key]:
                                                match.totals_odds[bm_key][line] = {}
                                            match.totals_odds[bm_key][line][o["name"].lower()] = o["price"]
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
    if not values:
        for bm_odds in match.odds.values():
            cote = bm_odds.get(player)
            if cote:
                values.append(cote)
    return sum(values) / len(values) if values else None


# ══════════════════════════════════════════════════════════════════════════════
#  API-TENNIS.COM — Stats joueurs, rankings, H2H
# ══════════════════════════════════════════════════════════════════════════════

# Cache des player_key pour éviter les appels répétés
_player_key_cache: dict[str, Optional[int]] = {}
_rankings_cache: dict[str, list[dict]] = {}


async def _api_tennis_request(session: aiohttp.ClientSession, params: dict) -> dict:
    """Appel générique à l'API-Tennis.com."""
    params["APIkey"] = APITENNIS_KEY
    try:
        async with session.get(
            APITENNIS_BASE,
            params=params,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status != 200:
                logger.warning(f"API-Tennis HTTP {resp.status} pour {params.get('method')}")
                return {}
            data = await resp.json()
            if data.get("success") != 1:
                logger.warning(f"API-Tennis erreur : {data}")
                return {}
            return data
    except aiohttp.ClientError as e:
        logger.error(f"Erreur réseau API-Tennis ({params.get('method')}): {e}")
        return {}


async def load_rankings(event_type: str = "ATP") -> list[dict]:
    """
    Charge le classement ATP ou WTA.
    Retourne une liste de {place, player, player_key, points, country}.
    Résultat mis en cache.
    """
    if event_type in _rankings_cache:
        return _rankings_cache[event_type]

    async with aiohttp.ClientSession() as session:
        data = await _api_tennis_request(session, {
            "method": "get_standings",
            "event_type": event_type,
        })

    rankings = data.get("result", [])
    _rankings_cache[event_type] = rankings
    logger.info(f"Rankings {event_type} chargés : {len(rankings)} joueurs")
    return rankings


async def find_player_key(player_name: str) -> Optional[int]:
    """
    Trouve le player_key à partir du nom du joueur.
    Cherche d'abord dans le cache, puis dans les rankings ATP et WTA.
    """
    name_lower = player_name.lower().strip()

    # Vérifier le cache
    if name_lower in _player_key_cache:
        return _player_key_cache[name_lower]

    # Charger les rankings si pas encore fait
    for event_type in ["ATP", "WTA"]:
        rankings = await load_rankings(event_type)
        for r in rankings:
            r_name = r.get("player", "").lower().strip()
            r_key = r.get("player_key")
            # Cache tous les joueurs au passage
            if r_name and r_key:
                _player_key_cache[r_name] = int(r_key)

    # Chercher par correspondance exacte
    if name_lower in _player_key_cache:
        return _player_key_cache[name_lower]

    # Chercher par correspondance partielle (nom de famille)
    parts = name_lower.split()
    for cached_name, cached_key in _player_key_cache.items():
        # Match sur le nom de famille
        if parts[-1] in cached_name or cached_name.split()[-1] in name_lower:
            _player_key_cache[name_lower] = cached_key
            return cached_key

    logger.warning(f"Joueur non trouvé : {player_name}")
    _player_key_cache[name_lower] = None
    return None


async def fetch_player_stats(player_name: str) -> dict:
    """
    Récupère les stats d'un joueur via API-Tennis.com.
    Retourne un dict avec ranking, points, recent_form, surface_win_rates, etc.
    """
    stats = {
        "ranking": None,
        "ranking_points": None,
        "country": "",
        "recent_form": [],
        "surface_win_rates": {},
        "fatigue_score": 0,
        "matches_won": 0,
        "matches_lost": 0,
    }

    player_key = await find_player_key(player_name)
    if not player_key:
        return stats

    # ── Ranking depuis le cache ──
    for event_type in ["ATP", "WTA"]:
        rankings = await load_rankings(event_type)
        for r in rankings:
            if int(r.get("player_key", 0)) == player_key:
                stats["ranking"] = int(r.get("place", 999))
                stats["ranking_points"] = int(r.get("points", 0))
                break
        if stats["ranking"]:
            break

    # ── Stats détaillées du joueur ──
    async with aiohttp.ClientSession() as session:
        data = await _api_tennis_request(session, {
            "method": "get_players",
            "player_key": player_key,
        })

    results = data.get("result", [])
    if not results:
        return stats

    player_data = results[0]
    player_stats = player_data.get("stats", [])
    stats["country"] = player_data.get("player_country", "")

    # Trouver les stats singles de la saison en cours et précédente
    current_year = "2026"
    prev_year = "2025"
    singles_stats = [
        s for s in player_stats
        if s.get("type") == "singles" and s.get("season") in [current_year, prev_year]
    ]

    if not singles_stats:
        # Fallback : prendre les stats singles les plus récentes
        singles_stats = [
            s for s in player_stats if s.get("type") == "singles"
        ]
        singles_stats.sort(key=lambda s: s.get("season", "0"), reverse=True)
        singles_stats = singles_stats[:2]

    # Calculer les win rates par surface
    total_won = 0
    total_lost = 0
    for s in singles_stats:
        for surface in ["hard", "clay", "grass"]:
            won = int(s.get(f"{surface}_won") or 0)
            lost = int(s.get(f"{surface}_lost") or 0)
            total = won + lost
            if total > 0:
                if surface not in stats["surface_win_rates"]:
                    stats["surface_win_rates"][surface] = {"won": 0, "lost": 0}
                stats["surface_win_rates"][surface]["won"] += won
                stats["surface_win_rates"][surface]["lost"] += lost

        season_won = int(s.get("matches_won") or 0)
        season_lost = int(s.get("matches_lost") or 0)
        total_won += season_won
        total_lost += season_lost

    # Convertir en taux
    for surface, data_s in stats["surface_win_rates"].items():
        total = data_s["won"] + data_s["lost"]
        stats["surface_win_rates"][surface] = data_s["won"] / total if total > 0 else 0.5

    stats["matches_won"] = total_won
    stats["matches_lost"] = total_lost

    # Forme récente : ratio victoires/total sur la saison en cours
    if singles_stats:
        latest = singles_stats[0]
        w = int(latest.get("matches_won") or 0)
        l = int(latest.get("matches_lost") or 0)
        total = w + l
        if total > 0:
            # Simuler une forme récente (True = victoire)
            recent_count = min(10, total)
            wins_in_recent = round(w / total * recent_count)
            stats["recent_form"] = [True] * wins_in_recent + [False] * (recent_count - wins_in_recent)

    # Fatigue : estimation basée sur le nombre de matchs cette saison
    if singles_stats:
        latest = singles_stats[0]
        total_matches = int(latest.get("matches_won") or 0) + int(latest.get("matches_lost") or 0)
        # Approximation grossière de la fatigue
        stats["fatigue_score"] = min(5, total_matches // 10)

    return stats


async def fetch_h2h(player1_name: str, player2_name: str) -> dict:
    """Récupère l'historique des confrontations directes via API-Tennis.com."""
    key1 = await find_player_key(player1_name)
    key2 = await find_player_key(player2_name)

    if not key1 or not key2:
        return {"p1_wins": 0, "p2_wins": 0, "total": 0}

    async with aiohttp.ClientSession() as session:
        data = await _api_tennis_request(session, {
            "method": "get_H2H",
            "first_player_key": key1,
            "second_player_key": key2,
        })

    result = data.get("result", {})
    h2h_matches = result.get("H2H", [])

    if not h2h_matches:
        return {"p1_wins": 0, "p2_wins": 0, "total": 0}

    p1_wins = 0
    p2_wins = 0

    for match in h2h_matches:
        winner = match.get("event_winner")
        first_key = match.get("first_player_key")

        if winner == "First Player":
            if first_key == key1:
                p1_wins += 1
            else:
                p2_wins += 1
        elif winner == "Second Player":
            if first_key == key1:
                p2_wins += 1
            else:
                p1_wins += 1

    total = p1_wins + p2_wins
    logger.info(f"H2H {player1_name} vs {player2_name}: {p1_wins}-{p2_wins} ({total} matchs)")

    return {
        "p1_wins": p1_wins,
        "p2_wins": p2_wins,
        "total": total,
    }
