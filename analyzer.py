"""
Moteur d'analyse : calcul des probabilités estimées et détection des value bets
"""

import logging
import math
from dataclasses import dataclass
from typing import Optional
from data_fetcher import Match, fetch_player_stats, fetch_h2h, get_average_odds
from config import FACTOR_WEIGHTS, MIN_EDGE, KELLY_FRACTION, BANKROLL

logger = logging.getLogger(__name__)


@dataclass
class ValueBet:
    """Résultat d'une analyse : un value bet détecté"""
    match: Match
    player: str          # Joueur sur lequel parier
    opponent: str
    p_estimated: float   # Probabilité estimée (modèle)
    p_implied: float     # Probabilité implicite du marché (sans marge)
    best_odds: float     # Meilleure cote disponible
    edge: float          # Edge = (p_est × cote) − 1
    kelly_stake: float   # Mise Kelly en €
    factors: dict        # Détail des scores par facteur

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
    """
    Convertit les cotes en probabilités réelles en retirant la marge du bookmaker.
    Méthode : normalisation (chaque P_impl / Σ P_impl).
    """
    raw_probs = {player: 1 / cote for player, cote in odds_dict.items()}
    total = sum(raw_probs.values())
    if total == 0:
        return {p: 0.5 for p in odds_dict}
    return {player: p / total for player, p in raw_probs.items()}


# ── Scoring des facteurs ──────────────────────────────────────────────────────

def score_ranking(stats1: dict, stats2: dict) -> float:
    """
    Score [0-1] pour le joueur 1 basé sur le ranking.
    Plus le ranking est bas (meilleur), plus le score est élevé.
    On utilise les points ATP si disponibles, sinon la position.
    """
    r1 = stats1.get("ranking") or 999
    r2 = stats2.get("ranking") or 999

    # Score basé sur les points ATP (plus fiable)
    pts1 = stats1.get("ranking_points") or max(0, 2000 - r1 * 5)
    pts2 = stats2.get("ranking_points") or max(0, 2000 - r2 * 5)

    total = pts1 + pts2
    if total == 0:
        return 0.5
    return pts1 / total


def score_recent_form(stats1: dict, stats2: dict) -> float:
    """Score basé sur le win rate des 5 derniers matchs."""
    form1 = stats1.get("recent_form", [])
    form2 = stats2.get("recent_form", [])

    rate1 = sum(form1) / len(form1) if form1 else 0.5
    rate2 = sum(form2) / len(form2) if form2 else 0.5

    total = rate1 + rate2
    if total == 0:
        return 0.5
    return rate1 / total


def score_surface(stats1: dict, stats2: dict, surface: str) -> float:
    """Score basé sur le win rate sur la surface du tournoi."""
    surface_key = surface.lower()
    wr1 = stats1.get("surface_win_rates", {}).get(surface_key, 0.5)
    wr2 = stats2.get("surface_win_rates", {}).get(surface_key, 0.5)

    total = wr1 + wr2
    if total == 0:
        return 0.5
    return wr1 / total


def score_h2h(h2h: dict) -> float:
    """Score H2H pour le joueur 1. Retourne 0.5 si pas d'historique."""
    total = h2h.get("total", 0)
    if total < 3:
        # Pas assez d'historique → neutre
        return 0.5
    p1_wins = h2h.get("p1_wins", 0)
    # Légère régression vers la moyenne pour éviter les extrêmes
    return (p1_wins + 1) / (total + 2)  # Lissage bayésien simple


def score_fatigue(stats1: dict, stats2: dict) -> float:
    """Score inversement proportionnel au nombre de matchs récents."""
    fat1 = stats1.get("fatigue_score", 0)
    fat2 = stats2.get("fatigue_score", 0)
    # Plus de matchs récents = plus fatigué = score plus bas
    score1 = max(0, 1 - fat1 * 0.15)
    score2 = max(0, 1 - fat2 * 0.15)
    total = score1 + score2
    if total == 0:
        return 0.5
    return score1 / total


# ── Modèle principal ──────────────────────────────────────────────────────────

def estimate_probability(
    stats1: dict, stats2: dict,
    h2h: dict, surface: str
) -> tuple[float, dict]:
    """
    Calcule la probabilité estimée que le joueur 1 gagne.
    Retourne (probabilité, dict des scores par facteur).
    """
    w = FACTOR_WEIGHTS

    factors = {
        "ranking":     score_ranking(stats1, stats2),
        "recent_form": score_recent_form(stats1, stats2),
        "surface":     score_surface(stats1, stats2, surface),
        "h2h":         score_h2h(h2h),
        "fatigue":     score_fatigue(stats1, stats2),
    }

    p_est = sum(factors[k] * w[k] for k in factors)

    # Clamp entre 5% et 95% pour éviter les extrêmes
    p_est = max(0.05, min(0.95, p_est))

    return p_est, factors


def calculate_edge(p_estimated: float, odds: float) -> float:
    """
    Edge = valeur espérée − 1
    Positif → value bet, négatif → pari désavantageux
    """
    return (p_estimated * odds) - 1


def kelly_stake(p_estimated: float, odds: float) -> float:
    """
    Fraction Kelly = (p × cote − 1) / (cote − 1)
    Applique KELLY_FRACTION pour réduire la volatilité.
    Retourne la mise en € sur la BANKROLL configurée.
    """
    if odds <= 1:
        return 0
    f = (p_estimated * odds - 1) / (odds - 1)
    f = max(0, f)  # Jamais négatif
    return round(f * KELLY_FRACTION * BANKROLL, 2)


# ── Détection des value bets ──────────────────────────────────────────────────

def get_surface_from_tournament(tournament_name: str) -> str:
    """Déduit la surface à partir du nom du tournoi."""
    name = tournament_name.lower()
    if any(t in name for t in ["french open", "roland garros", "clay",
                                 "monte carlo", "madrid", "rome", "barcelona"]):
        return "clay"
    if any(t in name for t in ["wimbledon", "grass", "queens", "halle"]):
        return "grass"
    # Par défaut : dur (indoor ou outdoor hard)
    return "hard"


async def analyze_match(match: Match) -> list[ValueBet]:
    """
    Analyse complète d'un match.
    Retourne la liste des value bets détectés (0, 1 ou 2 joueurs).
    """
    value_bets: list[ValueBet] = []

    if not match.odds:
        logger.debug(f"Pas de cotes pour {match.player1} vs {match.player2}")
        return []

    # Récupérer les stats et le H2H en parallèle
    import asyncio
    stats1, stats2, h2h = await asyncio.gather(
        fetch_player_stats(match.player1),
        fetch_player_stats(match.player2),
        fetch_h2h(match.player1, match.player2),
    )

    surface = get_surface_from_tournament(match.tournament)

    # Cotes moyennes sur les bookmakers de référence
    odds1 = get_average_odds(match, match.player1)
    odds2 = get_average_odds(match, match.player2)

    if not odds1 or not odds2:
        logger.warning(f"Cotes manquantes pour {match.player1} vs {match.player2}")
        return []

    # Probabilités implicites démarginisées
    implied = remove_margin({match.player1: odds1, match.player2: odds2})
    p_implied1 = implied[match.player1]

    # Probabilité estimée par notre modèle
    p_est1, factors = estimate_probability(stats1, stats2, h2h, surface)
    p_est2 = 1 - p_est1

    # Calcul des edges
    for player, p_est, p_implied, odds in [
        (match.player1, p_est1, p_implied1,       odds1),
        (match.player2, p_est2, 1 - p_implied1,   odds2),
    ]:
        opponent = match.player2 if player == match.player1 else match.player1
        edge = calculate_edge(p_est, odds)

        if edge >= MIN_EDGE:
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
    """Lance l'analyse sur tous les matchs récupérés."""
    import asyncio
    all_vbs: list[ValueBet] = []

    tasks = [analyze_match(m) for m in matches]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for res in results:
        if isinstance(res, Exception):
            logger.error(f"Erreur analyse match: {res}")
        else:
            all_vbs.extend(res)

    # Trier par edge décroissant
    all_vbs.sort(key=lambda vb: vb.edge, reverse=True)
    logger.info(f"Scan terminé : {len(all_vbs)} value bet(s) détecté(s) sur {len(matches)} matchs")
    return all_vbs
