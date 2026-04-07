"""
Module Tracking — Enregistre les value bets proposés et vérifie les résultats.
Calcule le ROI, win rate, et profit/perte.

Stockage en JSON local (data/tracker.json).
"""

import json
import os
import logging
import aiohttp
from datetime import datetime, timezone, timedelta
from typing import Optional

from config import APITENNIS_KEY, APITENNIS_BASE

logger = logging.getLogger(__name__)

TRACKER_FILE = "data/tracker.json"


def _load_tracker() -> list[dict]:
    """Charge l'historique des bets."""
    if not os.path.exists(TRACKER_FILE):
        return []
    try:
        with open(TRACKER_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _save_tracker(bets: list[dict]):
    """Sauvegarde l'historique."""
    os.makedirs("data", exist_ok=True)
    with open(TRACKER_FILE, "w") as f:
        json.dump(bets, f, indent=2, default=str)


def record_bet(bet_type: str, match_id: str, tournament: str,
               player: str, opponent: str, odds: float,
               edge: float, p_estimated: float, kelly_stake: float,
               commence_time: str, side: str = "ml",
               line: float = None):
    """
    Enregistre un value bet proposé.
    bet_type: "ml" (match winner) ou "over"/"under"
    """
    bets = _load_tracker()

    # Vérifier si déjà enregistré
    bet_key = f"{match_id}_{player}_{bet_type}_{line or ''}"
    for b in bets:
        if b.get("key") == bet_key:
            return  # Déjà enregistré

    bet = {
        "key": bet_key,
        "type": bet_type,
        "match_id": match_id,
        "tournament": tournament,
        "player": player,
        "opponent": opponent,
        "odds": odds,
        "edge": edge,
        "p_estimated": p_estimated,
        "kelly_stake": kelly_stake,
        "commence_time": commence_time,
        "side": side,
        "line": line,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "result": None,       # "won", "lost", "void", "pending"
        "profit": None,       # en unités (ex: +1.5 ou -1.0)
        "verified_at": None,
    }

    bets.append(bet)
    _save_tracker(bets)
    logger.info(f"Bet enregistré: {bet_type} {player} @ {odds:.2f} (edge {edge*100:+.1f}%)")


async def _api_tennis_request(session: aiohttp.ClientSession, params: dict) -> dict:
    params["APIkey"] = APITENNIS_KEY
    try:
        async with session.get(
            APITENNIS_BASE,
            params=params,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status != 200:
                return {}
            data = await resp.json()
            if data.get("success") != 1:
                return {}
            return data
    except Exception as e:
        logger.debug(f"Erreur API-Tennis tracker: {e}")
        return {}


async def verify_results():
    """
    Vérifie les résultats des bets en attente.
    Appelé par le scheduler ou manuellement.
    """
    bets = _load_tracker()
    pending = [b for b in bets if b.get("result") is None or b.get("result") == "pending"]

    if not pending:
        return 0

    now = datetime.now(timezone.utc)
    verified_count = 0

    async with aiohttp.ClientSession() as session:
        # Grouper par date pour limiter les requêtes API
        dates_to_check = set()
        for bet in pending:
            try:
                dt = datetime.fromisoformat(bet["commence_time"].replace("Z", "+00:00"))
                # Ne vérifier que les matchs qui auraient dû se terminer (> 4h après le début)
                if now - dt > timedelta(hours=4):
                    dates_to_check.add(dt.strftime("%Y-%m-%d"))
            except Exception:
                continue

        # Récupérer les résultats pour chaque date
        results_cache = {}
        for date_str in dates_to_check:
            data = await _api_tennis_request(session, {
                "method": "get_fixtures",
                "date_start": date_str,
                "date_stop": date_str,
            })
            for match in data.get("result", []):
                if match.get("event_status") in ["Finished", "Retired"]:
                    # Indexer par noms des joueurs
                    p1 = match.get("event_first_player", "").lower()
                    p2 = match.get("event_second_player", "").lower()
                    winner = match.get("event_winner")
                    scores = match.get("scores", [])
                    key = f"{p1}_{p2}"
                    results_cache[key] = {
                        "winner": winner,
                        "first_player": p1,
                        "second_player": p2,
                        "scores": scores,
                        "status": match.get("event_status"),
                    }
                    # Aussi avec l'ordre inversé
                    results_cache[f"{p2}_{p1}"] = results_cache[key]

    # Vérifier chaque bet
    for bet in pending:
        try:
            dt = datetime.fromisoformat(bet["commence_time"].replace("Z", "+00:00"))
            if now - dt < timedelta(hours=4):
                continue  # Trop tôt
        except Exception:
            continue

        player = bet["player"].lower()
        opponent = bet["opponent"].lower()

        # Chercher le résultat
        result_data = None
        for cache_key, data in results_cache.items():
            p1 = data["first_player"]
            p2 = data["second_player"]
            # Match trouvé si les noms correspondent (recherche souple)
            if (_name_match(player, p1) and _name_match(opponent, p2)) or \
               (_name_match(player, p2) and _name_match(opponent, p1)):
                result_data = data
                break

        if not result_data:
            # Match pas encore dans les résultats, on marque pending
            bet["result"] = "pending"
            continue

        # Déterminer le résultat
        if bet["type"] == "ml":
            # Match Winner
            winner_name = result_data["first_player"] if result_data["winner"] == "First Player" else result_data["second_player"]
            if _name_match(player, winner_name):
                bet["result"] = "won"
                bet["profit"] = round(bet["odds"] - 1, 2)  # Profit en unités
            else:
                bet["result"] = "lost"
                bet["profit"] = -1.0

        elif bet["type"] in ["over", "under"]:
            # Over/Under
            total_games = _count_total_games(result_data.get("scores", []))
            if total_games is not None and bet.get("line"):
                line = bet["line"]
                if bet["type"] == "over":
                    if total_games > line:
                        bet["result"] = "won"
                        bet["profit"] = round(bet["odds"] - 1, 2)
                    elif total_games == line:
                        bet["result"] = "void"
                        bet["profit"] = 0.0
                    else:
                        bet["result"] = "lost"
                        bet["profit"] = -1.0
                else:  # under
                    if total_games < line:
                        bet["result"] = "won"
                        bet["profit"] = round(bet["odds"] - 1, 2)
                    elif total_games == line:
                        bet["result"] = "void"
                        bet["profit"] = 0.0
                    else:
                        bet["result"] = "lost"
                        bet["profit"] = -1.0
            else:
                bet["result"] = "pending"
                continue

        bet["verified_at"] = now.isoformat()
        verified_count += 1
        logger.info(f"Résultat vérifié: {bet['type']} {bet['player']} → {bet['result']} ({bet['profit']:+.2f}u)")

    _save_tracker(bets)
    return verified_count


def _name_match(name1: str, name2: str) -> bool:
    """Vérifie si deux noms correspondent (correspondance souple par nom de famille)."""
    n1 = name1.lower().strip()
    n2 = name2.lower().strip()
    if n1 == n2:
        return True
    # Comparer les noms de famille
    parts1 = n1.split()
    parts2 = n2.split()
    surname1 = parts1[-1] if parts1 else ""
    surname2 = parts2[-1] if parts2 else ""
    if len(surname1) > 2 and surname1 == surname2:
        return True
    return False


def _count_total_games(scores: list) -> Optional[int]:
    """Compte le total de jeux à partir des scores de sets."""
    if not scores:
        return None
    total = 0
    for s in scores:
        try:
            # Les scores peuvent être "6", "7.6" (tiebreak)
            g1 = int(float(str(s.get("score_first", 0))))
            g2 = int(float(str(s.get("score_second", 0))))
            total += g1 + g2
        except (ValueError, TypeError):
            continue
    return total if total > 0 else None


def get_stats(days: int = 30) -> dict:
    """
    Calcule les statistiques de performance.
    """
    bets = _load_tracker()
    now = datetime.now(timezone.utc)

    # Filtrer par période
    if days > 0:
        cutoff = now - timedelta(days=days)
        filtered = []
        for b in bets:
            try:
                dt = datetime.fromisoformat(b["recorded_at"].replace("Z", "+00:00"))
                if dt >= cutoff:
                    filtered.append(b)
            except Exception:
                filtered.append(b)
    else:
        filtered = bets

    # Séparer par type
    ml_bets = [b for b in filtered if b["type"] == "ml" and b.get("result") in ["won", "lost"]]
    totals_bets = [b for b in filtered if b["type"] in ["over", "under"] and b.get("result") in ["won", "lost"]]
    pending = [b for b in filtered if b.get("result") in [None, "pending"]]

    def calc_stats(bet_list):
        if not bet_list:
            return {"count": 0, "won": 0, "lost": 0, "win_rate": 0, "profit": 0, "roi": 0}
        won = sum(1 for b in bet_list if b["result"] == "won")
        lost = sum(1 for b in bet_list if b["result"] == "lost")
        total_profit = sum(b.get("profit", 0) for b in bet_list)
        count = won + lost
        return {
            "count": count,
            "won": won,
            "lost": lost,
            "win_rate": won / count if count > 0 else 0,
            "profit": round(total_profit, 2),
            "roi": round(total_profit / count * 100, 1) if count > 0 else 0,
        }

    return {
        "ml": calc_stats(ml_bets),
        "totals": calc_stats(totals_bets),
        "all": calc_stats(ml_bets + totals_bets),
        "pending": len(pending),
        "total_recorded": len(filtered),
    }
