"""
Module Elo — Calcul des ratings Elo pour les joueurs ATP/WTA
Utilise les résultats de matchs via API-Tennis.com pour calculer un Elo global
et un Elo par surface (hard, clay, grass).

Formule Elo standard :
  - Expected score : E = 1 / (1 + 10^((Rb - Ra) / 400))
  - New rating : Ra' = Ra + K * (S - E)
  où S = 1 (victoire) ou 0 (défaite), K = facteur d'ajustement
"""

import logging
import aiohttp
from dataclasses import dataclass, field
from typing import Optional

from config import APITENNIS_KEY, APITENNIS_BASE

logger = logging.getLogger(__name__)

# ── Constantes Elo ────────────────────────────────────────────────────────────
DEFAULT_ELO = 1500         # Rating de départ
K_FACTOR = 32              # Facteur K standard (sensibilité aux résultats)
K_FACTOR_NEW = 48          # K plus élevé pour les joueurs avec peu de matchs (<30)
MATCHES_THRESHOLD = 30     # Seuil pour passer de K_FACTOR_NEW à K_FACTOR
SURFACE_K_FACTOR = 40      # K pour le Elo par surface (plus réactif)

# Saisons à charger pour construire le Elo
SEASONS_TO_LOAD = ["2024", "2025", "2026"]


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


# ── Cache global ──────────────────────────────────────────────────────────────
# {player_key: PlayerElo}
_elo_ratings: dict[int, PlayerElo] = {}
_elo_loaded: bool = False


# ── Calcul Elo ────────────────────────────────────────────────────────────────

def expected_score(rating_a: float, rating_b: float) -> float:
    """Probabilité attendue que le joueur A batte le joueur B."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def update_elo(winner_elo: float, loser_elo: float, k: float) -> tuple[float, float]:
    """
    Met à jour les ratings après un match.
    Retourne (new_winner_elo, new_loser_elo).
    """
    e_winner = expected_score(winner_elo, loser_elo)
    e_loser = 1.0 - e_winner

    new_winner = winner_elo + k * (1.0 - e_winner)
    new_loser = loser_elo + k * (0.0 - e_loser)

    return new_winner, new_loser


def get_k_factor(matches_played: int) -> float:
    """K-factor adaptatif : plus élevé pour les nouveaux joueurs."""
    if matches_played < MATCHES_THRESHOLD:
        return K_FACTOR_NEW
    return K_FACTOR


# ── Chargement des résultats et calcul ────────────────────────────────────────

async def _api_tennis_request(session: aiohttp.ClientSession, params: dict) -> dict:
    """Appel générique à l'API-Tennis.com."""
    params["APIkey"] = APITENNIS_KEY
    try:
        async with session.get(
            APITENNIS_BASE,
            params=params,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            if resp.status != 200:
                logger.warning(f"API-Tennis HTTP {resp.status} pour {params.get('method')}")
                return {}
            data = await resp.json()
            if data.get("success") != 1:
                return {}
            return data
    except aiohttp.ClientError as e:
        logger.error(f"Erreur réseau API-Tennis Elo: {e}")
        return {}


def _detect_surface(tournament_name: str) -> str:
    """Détecte la surface à partir du nom du tournoi."""
    name = tournament_name.lower() if tournament_name else ""
    if any(t in name for t in ["roland garros", "french open", "monte carlo",
                                 "madrid", "rome", "barcelona", "buenos aires",
                                 "rio", "lyon", "hamburg", "bastad", "umag",
                                 "kitzbuhel", "gstaad", "bucharest"]):
        return "clay"
    if any(t in name for t in ["wimbledon", "queens", "halle", "s-hertogenbosch",
                                 "eastbourne", "mallorca", "stuttgart grass",
                                 "newport"]):
        return "grass"
    return "hard"


def _process_match(winner_key: int, winner_name: str,
                   loser_key: int, loser_name: str,
                   surface: str):
    """Traite un match et met à jour les ratings Elo."""
    # Initialiser les joueurs si nécessaire
    if winner_key not in _elo_ratings:
        _elo_ratings[winner_key] = PlayerElo(
            name=winner_name, player_key=winner_key
        )
    if loser_key not in _elo_ratings:
        _elo_ratings[loser_key] = PlayerElo(
            name=loser_name, player_key=loser_key
        )

    winner = _elo_ratings[winner_key]
    loser = _elo_ratings[loser_key]

    # ── Elo Global ──
    k_w = get_k_factor(winner.matches_played)
    k_l = get_k_factor(loser.matches_played)
    k = (k_w + k_l) / 2  # K moyen entre les deux joueurs

    new_w_global, new_l_global = update_elo(winner.elo_global, loser.elo_global, k)
    winner.elo_global = new_w_global
    loser.elo_global = new_l_global

    # ── Elo Surface ──
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


async def load_elo_ratings():
    """
    Charge les résultats des dernières saisons et calcule les Elo.
    Appelé une fois au démarrage du bot.
    """
    global _elo_loaded
    if _elo_loaded:
        return

    logger.info("Calcul des ratings Elo en cours...")

    async with aiohttp.ClientSession() as session:
        total_matches = 0

        for season in SEASONS_TO_LOAD:
            # Récupérer les résultats ATP de la saison
            for event_type in ["ATP", "WTA"]:
                page = 1
                while page <= 5:  # Max 5 pages par saison pour limiter les requêtes
                    data = await _api_tennis_request(session, {
                        "method": "get_fixtures",
                        "date_start": f"{season}-01-01",
                        "date_stop": f"{season}-12-31",
                        "event_type": event_type,
                        "page": str(page),
                    })

                    results = data.get("result", [])
                    if not results:
                        break

                    for match in results:
                        # Ignorer les matchs non terminés
                        if match.get("event_status") != "Finished":
                            continue
                        if not match.get("event_winner"):
                            continue

                        first_key = match.get("first_player_key")
                        second_key = match.get("second_player_key")
                        first_name = match.get("event_first_player", "")
                        second_name = match.get("event_second_player", "")
                        tournament = match.get("tournament_name", "")
                        winner = match.get("event_winner")

                        if not first_key or not second_key:
                            continue

                        surface = _detect_surface(tournament)

                        if winner == "First Player":
                            _process_match(first_key, first_name,
                                          second_key, second_name, surface)
                        elif winner == "Second Player":
                            _process_match(second_key, second_name,
                                          first_key, first_name, surface)

                        total_matches += 1

                    page += 1

    _elo_loaded = True
    logger.info(f"Elo calculé : {len(_elo_ratings)} joueurs, {total_matches} matchs traités")

    # Log top 10
    top = sorted(_elo_ratings.values(), key=lambda p: p.elo_global, reverse=True)[:10]
    for i, p in enumerate(top, 1):
        logger.info(f"  #{i} {p.name}: Elo {p.elo_global:.0f} "
                    f"(H:{p.elo_hard:.0f} C:{p.elo_clay:.0f} G:{p.elo_grass:.0f})")


# ── Accès aux ratings ─────────────────────────────────────────────────────────

def get_player_elo(player_key: int) -> Optional[PlayerElo]:
    """Récupère les ratings Elo d'un joueur."""
    return _elo_ratings.get(player_key)


def get_elo_by_name(player_name: str) -> Optional[PlayerElo]:
    """Cherche un joueur par nom (correspondance partielle)."""
    name_lower = player_name.lower().strip()

    # Recherche exacte
    for elo in _elo_ratings.values():
        if elo.name.lower().strip() == name_lower:
            return elo

    # Recherche partielle (nom de famille)
    parts = name_lower.split()
    target_surname = parts[-1] if parts else ""
    for elo in _elo_ratings.values():
        elo_parts = elo.name.lower().split()
        elo_surname = elo_parts[-1] if elo_parts else ""
        if target_surname and target_surname == elo_surname:
            return elo

    # Recherche plus souple (contient)
    for elo in _elo_ratings.values():
        if target_surname in elo.name.lower():
            return elo

    return None


def get_surface_elo(player_key: int, surface: str) -> float:
    """Retourne le Elo sur une surface spécifique."""
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
