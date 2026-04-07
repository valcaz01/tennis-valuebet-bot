"""
Module Contexte Tournoi — Score les facteurs contextuels :
  1. Niveau du tournoi (Grand Chelem, Masters, ATP 500/250)
  2. Avantage local (joueur du pays hôte)
  3. Points à défendre (pression/motivation)
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ── Mapping tournoi → niveau ──────────────────────────────────────────────────
# Score de motivation : les joueurs top performent mieux dans les gros tournois

GRAND_SLAMS = [
    "australian open", "roland garros", "french open",
    "wimbledon", "us open"
]

MASTERS_1000 = [
    "indian wells", "miami", "monte carlo", "monte-carlo",
    "madrid", "rome", "canadian open", "montreal", "toronto",
    "cincinnati", "shanghai", "paris", "paris masters"
]

ATP_500 = [
    "rotterdam", "rio", "rio de janeiro", "acapulco", "dubai",
    "barcelona", "hamburg", "halle", "queens", "queen's",
    "washington", "beijing", "tokyo", "vienna", "basel"
]

# ── Mapping tournoi → pays hôte ───────────────────────────────────────────────

TOURNAMENT_COUNTRY = {
    # Grand Chelems
    "australian open": "Australia",
    "roland garros": "France",
    "french open": "France",
    "wimbledon": "United Kingdom",
    "us open": "United States",
    # Masters 1000
    "indian wells": "United States",
    "miami": "United States",
    "monte carlo": "France",       # Monaco, mais joueurs français = locaux
    "monte-carlo": "France",
    "madrid": "Spain",
    "rome": "Italy",
    "canadian open": "Canada",
    "montreal": "Canada",
    "toronto": "Canada",
    "cincinnati": "United States",
    "shanghai": "China",
    "paris": "France",
    "paris masters": "France",
    # ATP 500
    "rotterdam": "Netherlands",
    "rio": "Brazil",
    "rio de janeiro": "Brazil",
    "acapulco": "Mexico",
    "dubai": "United Arab Emirates",
    "barcelona": "Spain",
    "hamburg": "Germany",
    "halle": "Germany",
    "queens": "United Kingdom",
    "queen's": "United Kingdom",
    "washington": "United States",
    "beijing": "China",
    "tokyo": "Japan",
    "vienna": "Austria",
    "basel": "Switzerland",
    # ATP 250 courants
    "brisbane": "Australia",
    "auckland": "New Zealand",
    "marseille": "France",
    "lyon": "France",
    "buenos aires": "Argentina",
    "santiago": "Chile",
    "estoril": "Portugal",
    "munich": "Germany",
    "geneva": "Switzerland",
    "stuttgart": "Germany",
    "eastbourne": "United Kingdom",
    "s-hertogenbosch": "Netherlands",
    "mallorca": "Spain",
    "newport": "United States",
    "atlanta": "United States",
    "bastad": "Sweden",
    "umag": "Croatia",
    "kitzbuhel": "Austria",
    "gstaad": "Switzerland",
    "winston-salem": "United States",
    "metz": "France",
    "sofia": "Bulgaria",
    "florence": "Italy",
    "antwerp": "Belgium",
    "stockholm": "Sweden",
}

# Mapping pays joueur → pays tournoi (pour l'avantage local)
# API-Tennis utilise le nom complet du pays
COUNTRY_ALIASES = {
    "usa": "United States",
    "united states": "United States",
    "uk": "United Kingdom",
    "united kingdom": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    "brasil": "Brazil",
    "uae": "United Arab Emirates",
}


# ── Fonctions de scoring ──────────────────────────────────────────────────────

def get_tournament_level(tournament_name: str) -> str:
    """Retourne le niveau du tournoi : 'grand_slam', 'masters', 'atp500', 'atp250'."""
    name = tournament_name.lower()
    if any(gs in name for gs in GRAND_SLAMS):
        return "grand_slam"
    if any(m in name for m in MASTERS_1000):
        return "masters"
    if any(a in name for a in ATP_500):
        return "atp500"
    return "atp250"


def score_tournament_level(tournament_name: str,
                           ranking1: int, ranking2: int) -> tuple[float, float]:
    """
    Score le contexte tournoi pour chaque joueur.
    
    Logique :
    - Grand Chelem/Masters : les favoris (top 20) sont plus motivés et performent 
      à leur niveau → léger bonus au favori
    - ATP 250/500 : les tops sont parfois en mode "relax" → léger bonus à l'outsider
    
    Retourne (bonus_joueur1, bonus_joueur2) entre -0.05 et +0.05
    """
    level = get_tournament_level(tournament_name)
    
    # Déterminer qui est le favori
    r1 = ranking1 or 999
    r2 = ranking2 or 999
    
    if level == "grand_slam":
        # Les tops sur-performent en Grand Chelem
        if r1 <= 10:
            return (0.03, -0.03)
        elif r2 <= 10:
            return (-0.03, 0.03)
        return (0.0, 0.0)
    
    elif level == "masters":
        # Léger avantage aux tops en Masters aussi
        if r1 <= 15:
            return (0.02, -0.02)
        elif r2 <= 15:
            return (-0.02, 0.02)
        return (0.0, 0.0)
    
    elif level == "atp250":
        # Les tops jouent parfois "relax" en ATP 250
        if r1 <= 20 and r2 > 50:
            return (-0.02, 0.02)  # Léger malus au favori
        elif r2 <= 20 and r1 > 50:
            return (0.02, -0.02)
        return (0.0, 0.0)
    
    return (0.0, 0.0)


def is_home_player(player_country: str, tournament_name: str) -> bool:
    """Vérifie si un joueur joue à domicile."""
    if not player_country:
        return False
    
    name_lower = tournament_name.lower()
    
    # Chercher le pays du tournoi
    tournament_country = None
    for t_name, t_country in TOURNAMENT_COUNTRY.items():
        if t_name in name_lower:
            tournament_country = t_country
            break
    
    if not tournament_country:
        return False
    
    # Normaliser le pays du joueur
    player_c = player_country.strip()
    normalized = COUNTRY_ALIASES.get(player_c.lower(), player_c)
    
    return normalized.lower() == tournament_country.lower()


def score_home_advantage(player1_country: str, player2_country: str,
                         tournament_name: str) -> tuple[float, float]:
    """
    Score l'avantage local.
    Un joueur local gagne environ +3% de probabilité grâce au public.
    
    Retourne (bonus_joueur1, bonus_joueur2)
    """
    home1 = is_home_player(player1_country, tournament_name)
    home2 = is_home_player(player2_country, tournament_name)
    
    bonus1, bonus2 = 0.0, 0.0
    
    if home1 and not home2:
        bonus1 = 0.03
        bonus2 = -0.01
    elif home2 and not home1:
        bonus1 = -0.01
        bonus2 = 0.03
    
    return (bonus1, bonus2)


def score_points_to_defend(player1_stats: dict, player2_stats: dict,
                           tournament_name: str) -> tuple[float, float]:
    """
    Estime l'impact des points à défendre.
    
    Si un joueur a beaucoup gagné la saison précédente (beaucoup de matchs gagnés),
    il est probablement en train de défendre des points → pression.
    Mais ça peut aussi le motiver.
    
    Approche simplifiée : on regarde le ratio wins/losses.
    Un joueur avec un très bon ratio a plus de points à défendre.
    """
    w1 = player1_stats.get("matches_won", 0)
    l1 = player1_stats.get("matches_lost", 0)
    w2 = player2_stats.get("matches_won", 0)
    l2 = player2_stats.get("matches_lost", 0)
    
    total1 = w1 + l1
    total2 = w2 + l2
    
    if total1 == 0 or total2 == 0:
        return (0.0, 0.0)
    
    ratio1 = w1 / total1
    ratio2 = w2 / total2
    
    # Si un joueur a un win rate très élevé (>75%), il défend beaucoup de points
    # Ça crée une légère pression (malus de -1 à -2%)
    bonus1, bonus2 = 0.0, 0.0
    
    if ratio1 > 0.75:
        bonus1 = -0.01  # Légère pression
    if ratio2 > 0.75:
        bonus2 = -0.01
    
    return (bonus1, bonus2)


def compute_context_score(
    player1_name: str, player2_name: str,
    player1_country: str, player2_country: str,
    player1_stats: dict, player2_stats: dict,
    tournament_name: str,
    ranking1: int, ranking2: int
) -> tuple[float, float]:
    """
    Calcule le score contextuel global pour les deux joueurs.
    
    Retourne (score_joueur1, score_joueur2) en [0, 1]
    Le score est centré sur 0.5 (neutre) avec des bonus/malus.
    """
    # 1. Niveau du tournoi
    level_b1, level_b2 = score_tournament_level(
        tournament_name, ranking1, ranking2
    )
    
    # 2. Avantage local
    home_b1, home_b2 = score_home_advantage(
        player1_country, player2_country, tournament_name
    )
    
    # 3. Points à défendre
    defend_b1, defend_b2 = score_points_to_defend(
        player1_stats, player2_stats, tournament_name
    )
    
    # Score total centré sur 0.5
    total_bonus1 = level_b1 + home_b1 + defend_b1
    total_bonus2 = level_b2 + home_b2 + defend_b2
    
    score1 = 0.5 + total_bonus1
    score2 = 0.5 + total_bonus2
    
    # Normaliser pour que score1 + score2 reste cohérent
    total = score1 + score2
    if total > 0:
        score1 = score1 / total
    else:
        score1 = 0.5
    
    # Clamp
    score1 = max(0.3, min(0.7, score1))
    
    logger.debug(
        f"Contexte {player1_name} vs {player2_name} @ {tournament_name}: "
        f"level={level_b1:+.2f}/{level_b2:+.2f} "
        f"home={home_b1:+.2f}/{home_b2:+.2f} "
        f"defend={defend_b1:+.2f}/{defend_b2:+.2f} "
        f"→ score={score1:.2f}"
    )
    
    return score1
