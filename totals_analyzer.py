"""
Analyse Over/Under jeux — Estime le nombre total de jeux
et détecte les value bets sur le marché totals.

Logique :
- Deux gros serveurs → peu de breaks → matchs plus courts → Under
- Deux bons relanceurs → beaucoup de breaks → matchs plus longs → Over
- Un serveur vs un relanceur → dépend de l'équilibre
- Surface rapide → favorise le service → Under
- Surface lente → favorise le retour → Over

Estimation du nombre de jeux :
- Match en 2 sets (Bo3) : 
  - Minimum : 12 jeux (6-0 6-0)
  - Moyenne ATP : ~22-23 jeux
  - Maximum : ~39 jeux (7-6 6-7 7-6)
"""

import logging
import math
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timezone, timedelta

from data_fetcher import Match
from elo import get_elo_by_name, get_weighted_perf_stats
from surface_speed import get_tournament_speed

logger = logging.getLogger(__name__)

# Bookmakers français à privilégier
FR_BOOKMAKERS = ["betclic", "winamax", "unibet", "unibet_eu", "pmu", "zebet",
                 "france_pari", "parionssport"]

# Moyenne de jeux par match ATP (Bo3)
AVG_GAMES_BO3 = 22.5
# Écart-type typique
STD_GAMES = 3.5


@dataclass
class TotalsBet:
    """Un pari over/under détecté."""
    match: Match
    side: str              # "over" ou "under"
    line: float            # ex: 22.5
    best_odds: float       # meilleure cote trouvée
    bookmaker: str         # bookmaker avec la meilleure cote
    estimated_games: float # nombre de jeux estimé
    edge: float            # edge calculé
    confidence: str        # description du niveau de confiance

    @property
    def edge_pct(self) -> str:
        return f"{self.edge * 100:+.1f}%"


def estimate_total_games(
    player1_name: str, player2_name: str,
    tournament_name: str, surface: str
) -> Optional[float]:
    """
    Estime le nombre total de jeux dans un match.
    
    Basé sur :
    1. Les stats de service/retour des deux joueurs
    2. La vitesse de la surface
    """
    perf1 = get_weighted_perf_stats(player1_name)
    perf2 = get_weighted_perf_stats(player2_name)

    if not perf1 or not perf2:
        return None

    # ── Hold % des deux joueurs ──
    # Plus le hold % est élevé → moins de breaks → moins de jeux
    hold1 = perf1.get("hold_pct")
    hold2 = perf2.get("hold_pct")

    # ── Break % des deux joueurs ──
    # Plus le break % est élevé → plus de breaks → plus de jeux
    break1 = perf1.get("break_pct")
    break2 = perf2.get("break_pct")

    if hold1 is None or hold2 is None or break1 is None or break2 is None:
        # Fallback sur service/return points won
        spw1 = perf1.get("service_points_won_pct") or 0.63
        spw2 = perf2.get("service_points_won_pct") or 0.63
        rpw1 = perf1.get("return_points_won_pct") or 0.37
        rpw2 = perf2.get("return_points_won_pct") or 0.37

        # Probabilité de hold pour chaque joueur
        # Hold ≈ service points won (simplifié)
        hold1 = spw1
        hold2 = spw2
        break1 = rpw1
        break2 = rpw2

    # ── Estimation des breaks par set ──
    # P(break) pour J1 face au service de J2 ≈ break1 * (1 - hold2)
    # Simplifié : on utilise directement le break %
    avg_hold = (hold1 + hold2) / 2
    avg_break = (break1 + break2) / 2

    # Plus le hold est élevé et le break est bas → match serré, tiebreaks probables
    # Un match "serré" (haut hold, bas break) tend vers 22-24 jeux (6-4, 7-5, tiebreak)
    # Un match "déséquilibré" (un très fort vs faible) → 18-20 jeux (6-2, 6-3)
    # Un match avec beaucoup de breaks → 24-26 jeux (sets longs, va-et-vient)

    # Score de "compétitivité" : si les deux joueurs sont proches en niveau
    elo1 = get_elo_by_name(player1_name)
    elo2 = get_elo_by_name(player2_name)

    competitiveness = 1.0
    if elo1 and elo2:
        elo_diff = abs(elo1.elo_global - elo2.elo_global)
        # Plus l'écart est grand, moins c'est compétitif → moins de jeux
        competitiveness = max(0.7, 1.0 - elo_diff / 500)

    # ── Ajustement par vitesse de surface ──
    speed = get_tournament_speed(tournament_name, surface)
    # Surface rapide → service dominant → moins de breaks → légèrement moins de jeux
    # Surface lente → retour favorisé → plus de breaks → plus de jeux
    speed_adjustment = (1.0 - speed) * 2.0  # Terre lente +1-2 jeux, indoor rapide -1-2 jeux

    # ── Calcul final ──
    # Base : moyenne ATP
    estimated = AVG_GAMES_BO3

    # Ajustement compétitivité : match serré → plus de jeux
    estimated += (competitiveness - 0.85) * 8

    # Ajustement breaks : beaucoup de breaks → plus de jeux
    break_factor = (avg_break - 0.25) * 10  # Centré sur 25% de break moyen
    estimated += break_factor

    # Ajustement surface
    estimated += speed_adjustment

    # Clamp entre 18 et 30
    estimated = max(18.0, min(30.0, estimated))

    logger.debug(
        f"Totals {player1_name} vs {player2_name}: "
        f"hold={avg_hold:.2f} break={avg_break:.2f} "
        f"compet={competitiveness:.2f} speed_adj={speed_adjustment:+.1f} "
        f"→ estimated={estimated:.1f} jeux"
    )

    return estimated


def prob_over(estimated_games: float, line: float) -> float:
    """
    Calcule la probabilité que le total de jeux dépasse la ligne.
    Utilise une distribution normale centrée sur estimated_games.
    """
    z = (line - estimated_games) / STD_GAMES
    # CDF de la distribution normale
    p_under = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    return 1.0 - p_under


def analyze_totals(match: Match, surface: str) -> list[TotalsBet]:
    """
    Analyse le marché over/under pour un match.
    Retourne les value bets détectés sur les bookmakers FR.
    """
    if not match.totals_odds:
        return []

    estimated = estimate_total_games(
        match.player1, match.player2,
        match.tournament, surface
    )
    if estimated is None:
        return []

    bets: list[TotalsBet] = []

    # Chercher la meilleure cote pour chaque ligne, en privilégiant les bookmakers FR
    all_lines = set()
    for bm_data in match.totals_odds.values():
        for line in bm_data:
            all_lines.add(line)

    for line in all_lines:
        p_over = prob_over(estimated, line)
        p_under = 1.0 - p_over

        # Chercher la meilleure cote Over (bookmakers FR en priorité)
        best_over_odds = None
        best_over_bm = None
        for bm, bm_data in match.totals_odds.items():
            if line in bm_data and "over" in bm_data[line]:
                odds = bm_data[line]["over"]
                is_fr = any(fr in bm.lower() for fr in FR_BOOKMAKERS)
                if best_over_odds is None or odds > best_over_odds or (is_fr and odds >= (best_over_odds or 0) * 0.95):
                    best_over_odds = odds
                    best_over_bm = bm

        # Chercher la meilleure cote Under (bookmakers FR en priorité)
        best_under_odds = None
        best_under_bm = None
        for bm, bm_data in match.totals_odds.items():
            if line in bm_data and "under" in bm_data[line]:
                odds = bm_data[line]["under"]
                is_fr = any(fr in bm.lower() for fr in FR_BOOKMAKERS)
                if best_under_odds is None or odds > best_under_odds or (is_fr and odds >= (best_under_odds or 0) * 0.95):
                    best_under_odds = odds
                    best_under_bm = bm

        # Calculer les edges
        if best_over_odds and p_over > 0:
            edge_over = (p_over * best_over_odds) - 1
            if 0.03 <= edge_over <= 0.30:
                confidence = "🔥 Forte" if edge_over >= 0.12 else ("✅ Bonne" if edge_over >= 0.06 else "⚠️ Modérée")
                bets.append(TotalsBet(
                    match=match, side="over", line=line,
                    best_odds=best_over_odds, bookmaker=best_over_bm,
                    estimated_games=estimated, edge=edge_over,
                    confidence=confidence,
                ))

        if best_under_odds and p_under > 0:
            edge_under = (p_under * best_under_odds) - 1
            if 0.03 <= edge_under <= 0.30:
                confidence = "🔥 Forte" if edge_under >= 0.12 else ("✅ Bonne" if edge_under >= 0.06 else "⚠️ Modérée")
                bets.append(TotalsBet(
                    match=match, side="under", line=line,
                    best_odds=best_under_odds, bookmaker=best_under_bm,
                    estimated_games=estimated, edge=edge_under,
                    confidence=confidence,
                ))

    # Trier par edge décroissant et garder les meilleurs
    bets.sort(key=lambda b: b.edge, reverse=True)
    return bets[:2]  # Max 2 par match (le meilleur over et le meilleur under)


def is_today_or_tomorrow(commence_time: str) -> bool:
    try:
        dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).date()
        return dt.date() == now.date() or dt.date() == tomorrow
    except Exception:
        return True


def is_tomorrow(commence_time: str) -> bool:
    try:
        dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).date()
        return dt.date() == tomorrow
    except Exception:
        return False
