"""
Moteur d'analyse : calcul des probabilités estimées et détection des value bets
Intègre Elo + contexte tournoi + surface dynamique pondérée.
"""

import logging
import math
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional
from data_fetcher import Match, fetch_player_stats, fetch_h2h, get_average_odds
from elo import (
    get_elo_by_name, elo_win_probability, DEFAULT_ELO,
    get_weighted_surface_winrate, get_weighted_perf_stats
)
from context import compute_context_score
from config import FACTOR_WEIGHTS, MIN_EDGE, KELLY_FRACTION, BANKROLL

logger = logging.getLogger(__name__)

# ── Filtres de sécurité ───────────────────────────────────────────────────────
MAX_ODDS = 5.0
MIN_ODDS = 1.20
MAX_EDGE = 0.25
MIN_DATA_FACTORS = 2


@dataclass
class ValueBet:
    match: Match
    player: str
    opponent: str
    p_estimated: float
    p_implied: float
    best_odds: float
    edge: float
    kelly_stake: float
    factors: dict

    @property
    def edge_pct(self) -> str:
        return f"{self.edge * 100:+.1f}%"

    @property
    def confidence(self) -> str:
        if self.edge >= 0.15:
            return "🔥 Forte"
        elif self.edge >= 0.08:
            return "✅ Bonne"
        else:
            return "⚠️ Modérée"


# ── Démarginisation ───────────────────────────────────────────────────────────

def remove_margin(odds_dict: dict[str, float]) -> dict[str, float]:
    raw_probs = {player: 1 / cote for player, cote in odds_dict.items()}
    total = sum(raw_probs.values())
    if total == 0:
        return {p: 0.5 for p in odds_dict}
    return {player: p / total for player, p in raw_probs.items()}


# ── Scoring des facteurs ──────────────────────────────────────────────────────

def score_elo(player1_name: str, player2_name: str, surface: str) -> float:
    elo1 = get_elo_by_name(player1_name)
    elo2 = get_elo_by_name(player2_name)
    if not elo1 or not elo2:
        return 0.5
    surface_lower = surface.lower()
    if surface_lower == "clay":
        e1, e2 = elo1.elo_clay, elo2.elo_clay
    elif surface_lower == "grass":
        e1, e2 = elo1.elo_grass, elo2.elo_grass
    else:
        e1, e2 = elo1.elo_hard, elo2.elo_hard
    if abs(e1 - DEFAULT_ELO) < 10 or abs(e2 - DEFAULT_ELO) < 10:
        e1, e2 = elo1.elo_global, elo2.elo_global
    return elo_win_probability(e1, e2)


def score_ranking(stats1: dict, stats2: dict) -> float:
    pts1 = stats1.get("ranking_points") or 0
    pts2 = stats2.get("ranking_points") or 0
    if pts1 > 0 and pts2 > 0:
        log_pts1 = math.log(pts1 + 1)
        log_pts2 = math.log(pts2 + 1)
        total = log_pts1 + log_pts2
        if total == 0:
            return 0.5
        return log_pts1 / total
    r1 = stats1.get("ranking") or 999
    r2 = stats2.get("ranking") or 999
    score1 = 1 / (r1 + 5)
    score2 = 1 / (r2 + 5)
    total = score1 + score2
    if total == 0:
        return 0.5
    return score1 / total


def score_recent_form(stats1: dict, stats2: dict) -> float:
    form1 = stats1.get("recent_form", [])
    form2 = stats2.get("recent_form", [])
    rate1 = sum(form1) / len(form1) if form1 else 0.5
    rate2 = sum(form2) / len(form2) if form2 else 0.5
    total = rate1 + rate2
    if total == 0:
        return 0.5
    return rate1 / total


def score_surface(player1_name: str, player2_name: str,
                  stats1: dict, stats2: dict, surface: str) -> float:
    """
    Score surface dynamique avec pondération récente.
    Utilise d'abord le win rate pondéré des 90 derniers jours (elo module).
    Fallback sur les stats API-Tennis si pas assez de données récentes.
    """
    # Essayer le win rate pondéré récent (depuis le module elo)
    elo1 = get_elo_by_name(player1_name)
    elo2 = get_elo_by_name(player2_name)

    wr1 = None
    wr2 = None

    if elo1:
        wr1 = get_weighted_surface_winrate(elo1.player_key, surface)
    if elo2:
        wr2 = get_weighted_surface_winrate(elo2.player_key, surface)

    # Fallback sur les stats API-Tennis si pas de données récentes
    if wr1 is None:
        wr1 = stats1.get("surface_win_rates", {}).get(surface.lower(), 0.5)
    if wr2 is None:
        wr2 = stats2.get("surface_win_rates", {}).get(surface.lower(), 0.5)

    total = wr1 + wr2
    if total == 0:
        return 0.5
    return wr1 / total


def score_h2h(h2h: dict) -> float:
    total = h2h.get("total", 0)
    if total < 3:
        return 0.5
    p1_wins = h2h.get("p1_wins", 0)
    return (p1_wins + 1) / (total + 2)


def score_fatigue(stats1: dict, stats2: dict) -> float:
    fat1 = stats1.get("fatigue_score", 0)
    fat2 = stats2.get("fatigue_score", 0)
    score1 = max(0, 1 - fat1 * 0.15)
    score2 = max(0, 1 - fat2 * 0.15)
    total = score1 + score2
    if total == 0:
        return 0.5
    return score1 / total


def score_performance(player1_name: str, player2_name: str) -> float:
    """
    Score [0-1] basé sur les stats de performance pondérées :
    - % points gagnés au service (hold strength)
    - % points gagnés au retour (break potential)
    - % break points sauvés (mental au service)
    - % break points convertis (clutch au retour)
    
    On combine ces 4 métriques en un score composite.
    """
    perf1 = get_weighted_perf_stats(player1_name)
    perf2 = get_weighted_perf_stats(player2_name)

    if not perf1 or not perf2:
        return 0.5

    # Calculer un score composite pour chaque joueur
    # Pondération : service 35%, retour 35%, BP saved 15%, BP converted 15%
    def composite(p):
        spw = p.get("service_points_won_pct") or 0.6  # moyenne ATP ~63%
        rpw = p.get("return_points_won_pct") or 0.35   # moyenne ATP ~37%
        bps = p.get("bp_saved_pct") or 0.6              # moyenne ATP ~62%
        bpc = p.get("bp_converted_pct") or 0.4          # moyenne ATP ~42%
        return spw * 0.35 + rpw * 0.35 + bps * 0.15 + bpc * 0.15

    c1 = composite(perf1)
    c2 = composite(perf2)

    total = c1 + c2
    if total == 0:
        return 0.5
    return c1 / total


# ── Modèle principal ──────────────────────────────────────────────────────────

def estimate_probability(
    stats1: dict, stats2: dict,
    h2h: dict, surface: str,
    player1_name: str, player2_name: str,
    tournament_name: str
) -> tuple[float, dict]:
    """
    Calcule la probabilité estimée que le joueur 1 gagne.
    8 facteurs pondérés incluant Elo, surface dynamique, contexte et performance.
    """
    w = FACTOR_WEIGHTS

    ctx_score = compute_context_score(
        player1_name, player2_name,
        stats1.get("country", ""), stats2.get("country", ""),
        stats1, stats2,
        tournament_name,
        stats1.get("ranking") or 999,
        stats2.get("ranking") or 999,
    )

    factors = {
        "elo":          score_elo(player1_name, player2_name, surface),
        "ranking":      score_ranking(stats1, stats2),
        "recent_form":  score_recent_form(stats1, stats2),
        "surface":      score_surface(player1_name, player2_name, stats1, stats2, surface),
        "h2h":          score_h2h(h2h),
        "fatigue":      score_fatigue(stats1, stats2),
        "context":      ctx_score,
        "performance":  score_performance(player1_name, player2_name),
    }

    p_est = sum(factors[k] * w.get(k, 0) for k in factors)
    p_est = max(0.05, min(0.95, p_est))

    return p_est, factors


def calculate_edge(p_estimated: float, odds: float) -> float:
    return (p_estimated * odds) - 1


def kelly_stake(p_estimated: float, odds: float) -> float:
    if odds <= 1:
        return 0
    f = (p_estimated * odds - 1) / (odds - 1)
    f = max(0, f)
    return round(f * KELLY_FRACTION * BANKROLL, 2)


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_today(commence_time: str) -> bool:
    try:
        dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return dt.date() == now.date()
    except Exception:
        return True


def has_enough_data(factors: dict) -> bool:
    non_neutral = sum(1 for v in factors.values() if abs(v - 0.5) > 0.02)
    return non_neutral >= MIN_DATA_FACTORS


def get_surface_from_tournament(tournament_name: str) -> str:
    name = tournament_name.lower()
    if any(t in name for t in ["french open", "roland garros", "clay",
                                 "monte carlo", "madrid", "rome", "barcelona"]):
        return "clay"
    if any(t in name for t in ["wimbledon", "grass", "queens", "halle"]):
        return "grass"
    return "hard"


# ── Détection des value bets ──────────────────────────────────────────────────

async def analyze_match(match: Match) -> list[ValueBet]:
    value_bets: list[ValueBet] = []

    if not is_today(match.commence_time):
        return []

    if not match.odds:
        logger.debug(f"Pas de cotes pour {match.player1} vs {match.player2}")
        return []

    import asyncio
    stats1, stats2, h2h = await asyncio.gather(
        fetch_player_stats(match.player1),
        fetch_player_stats(match.player2),
        fetch_h2h(match.player1, match.player2),
    )

    surface = get_surface_from_tournament(match.tournament)

    odds1 = get_average_odds(match, match.player1)
    odds2 = get_average_odds(match, match.player2)

    if not odds1 or not odds2:
        logger.warning(f"Cotes manquantes pour {match.player1} vs {match.player2}")
        return []

    implied = remove_margin({match.player1: odds1, match.player2: odds2})
    p_implied1 = implied[match.player1]

    p_est1, factors = estimate_probability(
        stats1, stats2, h2h, surface,
        match.player1, match.player2,
        match.tournament
    )
    p_est2 = 1 - p_est1

    if not has_enough_data(factors):
        logger.info(f"Pas assez de données pour {match.player1} vs {match.player2}, skip")
        return []

    for player, p_est, p_implied, odds in [
        (match.player1, p_est1, p_implied1,       odds1),
        (match.player2, p_est2, 1 - p_implied1,   odds2),
    ]:
        if odds > MAX_ODDS or odds < MIN_ODDS:
            continue

        opponent = match.player2 if player == match.player1 else match.player1
        edge = calculate_edge(p_est, odds)

        if edge >= MIN_EDGE and edge <= MAX_EDGE:
            stake = kelly_stake(p_est, odds)
            value_bets.append(ValueBet(
                match=match,
                player=player,
                opponent=opponent,
                p_estimated=p_est,
                p_implied=p_implied,
                best_odds=odds,
                edge=edge,
                kelly_stake=stake,
                factors=factors if player == match.player1
                         else {k: 1 - v for k, v in factors.items()},
            ))

    if value_bets:
        names = [f"{vb.player} (edge {vb.edge_pct})" for vb in value_bets]
        logger.info(f"Value bet(s) trouvé(s) : {', '.join(names)}")

    return value_bets


async def scan_all_matches(matches: list[Match]) -> list[ValueBet]:
    import asyncio
    all_vbs: list[ValueBet] = []

    tasks = [analyze_match(m) for m in matches]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for res in results:
        if isinstance(res, Exception):
            logger.error(f"Erreur analyse match: {res}")
        else:
            all_vbs.extend(res)

    all_vbs.sort(key=lambda vb: vb.edge, reverse=True)
    logger.info(f"Scan terminé : {len(all_vbs)} value bet(s) détecté(s) sur {len(matches)} matchs")
    return all_vbs
