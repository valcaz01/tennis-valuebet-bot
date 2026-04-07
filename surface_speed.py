"""
Module Vitesse de Surface — Mapping des vitesses par tournoi
et scoring de la compatibilité joueur/surface.

Source : Tennis Abstract Surface Speed Ratings
Un rating > 1.0 = plus rapide que la moyenne
Un rating < 1.0 = plus lent que la moyenne

Un joueur serveur (ace rate élevé) → avantagé sur surface rapide
Un joueur défenseur (bon retour) → avantagé sur surface lente
"""

import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)

# ── Speed ratings par tournoi ─────────────────────────────────────────────────
# Basé sur Tennis Abstract 2024-2026 (ace rate ajusté)
# Valeurs arrondies, mises à jour manuellement

TOURNAMENT_SPEED: dict[str, float] = {
    # ── Terre battue lente (< 0.75) ──
    "roland garros":        0.62,
    "french open":          0.62,
    "rome":                 0.68,
    "barcelona":            0.70,
    "hamburg":              0.72,
    "buenos aires":         0.65,
    "rio":                  0.70,
    "bucharest":            0.68,
    "bastad":               0.73,
    "umag":                 0.71,
    "kitzbuhel":            0.69,
    "gstaad":               0.74,

    # ── Terre battue medium (0.75 - 0.90) ──
    "monte carlo":          0.78,
    "monte-carlo":          0.78,
    "marrakech":            0.80,
    "lyon":                 0.82,
    "geneva":               0.79,
    "estoril":              0.81,
    "munich":               0.83,

    # ── Terre battue rapide (> 0.90) ──
    "madrid":               0.95,  # Altitude 650m → balle plus rapide

    # ── Dur lent (0.80 - 0.95) ──
    "indian wells":         0.85,
    "miami":                0.88,
    "canadian open":        0.90,
    "montreal":             0.90,
    "toronto":              0.90,
    "cincinnati":           0.92,
    "us open":              0.93,

    # ── Dur medium (0.95 - 1.10) ──
    "australian open":      1.02,
    "dubai":                1.00,
    "doha":                 0.98,
    "beijing":              1.00,
    "shanghai":             1.03,
    "washington":           0.96,
    "acapulco":             0.97,

    # ── Dur rapide indoor (> 1.10) ──
    "paris":                1.25,
    "paris masters":        1.25,
    "vienna":               1.30,
    "basel":                1.28,
    "rotterdam":            1.22,
    "marseille":            1.35,
    "montpellier":          1.48,
    "sofia":                1.20,
    "metz":                 1.32,
    "stockholm":            1.18,
    "antwerp":              1.15,
    "atp finals":           1.15,
    "nitto atp finals":     1.15,

    # ── Gazon (toujours rapide, > 1.15) ──
    "wimbledon":            1.20,
    "halle":                1.30,
    "queens":               1.28,
    "queen's":              1.28,
    "s-hertogenbosch":      1.25,
    "eastbourne":           1.18,
    "mallorca":             1.22,
    "newport":              1.15,
    "stuttgart":             1.26,
}

# Vitesses par défaut si tournoi inconnu
DEFAULT_SPEEDS = {
    "clay":  0.75,
    "hard":  1.00,
    "grass": 1.25,
}


def get_tournament_speed(tournament_name: str, surface: str) -> float:
    """
    Retourne le speed rating d'un tournoi.
    > 1.0 = rapide, < 1.0 = lent.
    """
    name_lower = tournament_name.lower()

    # Chercher dans le mapping
    for t_name, speed in TOURNAMENT_SPEED.items():
        if t_name in name_lower:
            return speed

    # Fallback par type de surface
    return DEFAULT_SPEEDS.get(surface.lower(), 1.0)


def get_player_speed_profile(perf_stats: dict) -> Optional[float]:
    """
    Calcule le profil de vitesse d'un joueur basé sur ses stats.
    
    Score > 1.0 = joueur serveur/attaquant (préfère surface rapide)
    Score < 1.0 = joueur défenseur/relanceur (préfère surface lente)
    Score = 1.0 = polyvalent
    
    On utilise le ratio service/retour :
    - Un bon serveur a un % service points won élevé
    - Un bon relanceur a un % return points won élevé
    """
    if not perf_stats:
        return None

    spw = perf_stats.get("service_points_won_pct")
    rpw = perf_stats.get("return_points_won_pct")

    if spw is None or rpw is None:
        return None

    # Ratio service/retour
    # Moyenne ATP : ~63% service, ~37% retour → ratio ~1.7
    # Un serveur : ~68% service, ~33% retour → ratio ~2.06
    # Un défenseur : ~58% service, ~42% retour → ratio ~1.38
    if rpw == 0:
        return 1.5  # Très serveur

    ratio = spw / rpw
    avg_ratio = 0.63 / 0.37  # ~1.70

    # Normaliser : > 1.0 = serveur, < 1.0 = défenseur
    return ratio / avg_ratio


def score_speed_compatibility(player_speed: float, tournament_speed: float) -> float:
    """
    Score de compatibilité joueur/surface.
    
    Un serveur (profil > 1.0) sur surface rapide (speed > 1.0) → bonus
    Un défenseur (profil < 1.0) sur surface lente (speed < 1.0) → bonus
    Un serveur sur surface lente → malus
    Un défenseur sur surface rapide → malus
    
    Retourne un score entre -0.05 et +0.05.
    """
    # Les deux > 1 (serveur + rapide) ou les deux < 1 (défenseur + lent) = match
    # L'un > 1 et l'autre < 1 = mismatch

    # Calcul de compatibilité
    # Si les deux vont dans le même sens → positif
    # Si opposés → négatif
    player_deviation = player_speed - 1.0   # > 0 = serveur, < 0 = défenseur
    surface_deviation = tournament_speed - 1.0  # > 0 = rapide, < 0 = lent

    # Produit : positif si même direction, négatif si opposé
    compatibility = player_deviation * surface_deviation

    # Normaliser entre -0.05 et +0.05
    score = max(-0.05, min(0.05, compatibility * 0.3))

    return score


def compute_speed_factor(
    player1_name: str, player2_name: str,
    player1_perf: dict, player2_perf: dict,
    tournament_name: str, surface: str
) -> float:
    """
    Calcule le facteur vitesse de surface pour la confrontation.
    
    Retourne un score [0-1] centré sur 0.5.
    > 0.5 = le joueur 1 est plus adapté à cette vitesse
    < 0.5 = le joueur 2 est plus adapté
    """
    t_speed = get_tournament_speed(tournament_name, surface)

    p1_speed = get_player_speed_profile(player1_perf)
    p2_speed = get_player_speed_profile(player2_perf)

    if p1_speed is None and p2_speed is None:
        return 0.5  # Pas de données → neutre

    # Calculer la compatibilité de chaque joueur
    compat1 = score_speed_compatibility(p1_speed or 1.0, t_speed)
    compat2 = score_speed_compatibility(p2_speed or 1.0, t_speed)

    # Convertir en score relatif centré sur 0.5
    diff = compat1 - compat2
    score = 0.5 + diff

    # Clamp entre 0.35 et 0.65
    score = max(0.35, min(0.65, score))

    logger.debug(
        f"Speed: {player1_name} (profil={p1_speed:.2f}) vs {player2_name} (profil={p2_speed:.2f}) "
        f"@ {tournament_name} (speed={t_speed:.2f}) → score={score:.3f}"
    )

    return score
