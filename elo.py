"""
Module Elo — Calcul des ratings Elo + stats surface pondérées
Charge les résultats jour par jour sur les derniers mois via API-Tennis.com.

En plus du Elo, on track le win rate par surface avec pondération temporelle :
les matchs récents pèsent plus que les anciens.
"""

import logging
import math
import aiohttp
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional

from config import APITENNIS_KEY, APITENNIS_BASE

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────
DEFAULT_ELO = 1500
K_FACTOR = 32
K_FACTOR_NEW = 48
MATCHES_THRESHOLD = 30
SURFACE_K_FACTOR = 40
DAYS_TO_LOAD = 90


@dataclass
class SurfaceResult:
    """Un résultat de match sur une surface avec sa date."""
    won: bool
    days_ago: int


@dataclass
class MatchPerf:
    """Stats de performance d'un match."""
    days_ago: int
    service_points_won: int = 0
    service_points_total: int = 0
    return_points_won: int = 0
    return_points_total: int = 0
    break_points_saved: int = 0
    break_points_faced: int = 0
    break_points_converted: int = 0
    break_points_chances: int = 0
    service_games_won: int = 0
    service_games_total: int = 0
    return_games_won: int = 0
    return_games_total: int = 0


@dataclass
class PlayerElo:
    """Ratings Elo + historique surface + retraits + perf stats d'un joueur."""
    name: str
    player_key: int
    elo_global: float = DEFAULT_ELO
    elo_hard: float = DEFAULT_ELO
    elo_clay: float = DEFAULT_ELO
    elo_grass: float = DEFAULT_ELO
    matches_played: int = 0
    surface_results: dict = field(default_factory=lambda: {
        "hard": [], "clay": [], "grass": []
    })
    retirements: list = field(default_factory=list)
    # Stats de performance par match (pour moyennes pondérées)
    perf_history: list = field(default_factory=list)  # [MatchPerf]


# Cache global
_elo_ratings: dict[int, PlayerElo] = {}
_elo_loaded: bool = False


# ── Calcul Elo ────────────────────────────────────────────────────────────────

def expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def update_elo(winner_elo: float, loser_elo: float, k: float) -> tuple[float, float]:
    e_winner = expected_score(winner_elo, loser_elo)
    new_winner = winner_elo + k * (1.0 - e_winner)
    new_loser = loser_elo + k * (0.0 - (1.0 - e_winner))
    return new_winner, new_loser


def get_k_factor(matches_played: int) -> float:
    if matches_played < MATCHES_THRESHOLD:
        return K_FACTOR_NEW
    return K_FACTOR


# ── Win rate surface pondéré ──────────────────────────────────────────────────

def get_weighted_surface_winrate(player_key: int, surface: str) -> Optional[float]:
    """
    Calcule le win rate pondéré sur une surface.
    Les matchs récents pèsent plus grâce à un decay exponentiel.
    
    Pondération : weight = e^(-days_ago / 60)
    → Un match d'hier a un poids de ~0.98
    → Un match d'il y a 30 jours : ~0.61
    → Un match d'il y a 60 jours : ~0.37
    → Un match d'il y a 90 jours : ~0.22
    """
    elo = _elo_ratings.get(player_key)
    if not elo:
        return None

    surface_lower = surface.lower()
    results = elo.surface_results.get(surface_lower, [])

    if len(results) < 3:
        return None  # Pas assez de matchs sur cette surface

    DECAY_CONSTANT = 60.0  # Plus petit = plus de poids aux matchs récents

    weighted_wins = 0.0
    total_weight = 0.0

    for r in results:
        weight = math.exp(-r.days_ago / DECAY_CONSTANT)
        if r.won:
            weighted_wins += weight
        total_weight += weight

    if total_weight == 0:
        return None

    return weighted_wins / total_weight


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
                   surface: str, days_ago: int):
    """Traite un match : met à jour Elo + historique surface."""
    if winner_key not in _elo_ratings:
        _elo_ratings[winner_key] = PlayerElo(name=winner_name, player_key=winner_key)
    if loser_key not in _elo_ratings:
        _elo_ratings[loser_key] = PlayerElo(name=loser_name, player_key=loser_key)

    winner = _elo_ratings[winner_key]
    loser = _elo_ratings[loser_key]

    # ── Elo Global ──
    k = (get_k_factor(winner.matches_played) + get_k_factor(loser.matches_played)) / 2
    new_w, new_l = update_elo(winner.elo_global, loser.elo_global, k)
    winner.elo_global = new_w
    loser.elo_global = new_l

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

    # ── Historique surface (pour win rate pondéré) ──
    surface_lower = surface.lower()
    if surface_lower in winner.surface_results:
        winner.surface_results[surface_lower].append(
            SurfaceResult(won=True, days_ago=days_ago)
        )
    if surface_lower in loser.surface_results:
        loser.surface_results[surface_lower].append(
            SurfaceResult(won=False, days_ago=days_ago)
        )

    winner.matches_played += 1
    loser.matches_played += 1


# ── Chargement ────────────────────────────────────────────────────────────────

async def load_elo_ratings():
    """Charge les résultats des X derniers jours et calcule les Elo."""
    global _elo_loaded
    if _elo_loaded:
        return

    logger.info(f"Calcul des ratings Elo — chargement des {DAYS_TO_LOAD} derniers jours...")

    today = datetime.now(timezone.utc).date()
    total_matches = 0
    days_loaded = 0

    async with aiohttp.ClientSession() as session:
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
                status = match.get("event_status", "")
                first_key = match.get("first_player_key")
                second_key = match.get("second_player_key")
                first_name = match.get("event_first_player", "")
                second_name = match.get("event_second_player", "")
                tournament = match.get("tournament_name", "")

                if not first_key or not second_key:
                    continue

                event_type = match.get("event_type_type", "")
                if "double" in event_type.lower():
                    continue

                # ── Tracker les retraits et walkovers ──
                if status == "Retired":
                    # Le perdant est celui qui a abandonné
                    winner = match.get("event_winner")
                    if winner == "First Player":
                        _ensure_player(second_key, second_name)
                        _elo_ratings[second_key].retirements.append((i, "retired"))
                    elif winner == "Second Player":
                        _ensure_player(first_key, first_name)
                        _elo_ratings[first_key].retirements.append((i, "retired"))

                elif status == "Walk Over":
                    # Le perdant est celui qui a déclaré forfait
                    winner = match.get("event_winner")
                    if winner == "First Player":
                        _ensure_player(second_key, second_name)
                        _elo_ratings[second_key].retirements.append((i, "walkover"))
                    elif winner == "Second Player":
                        _ensure_player(first_key, first_name)
                        _elo_ratings[first_key].retirements.append((i, "walkover"))

                # ── Traitement normal des matchs terminés ──
                if status != "Finished" and status != "Retired":
                    continue
                winner = match.get("event_winner")
                if not winner:
                    continue

                surface = _detect_surface(tournament)

                if winner == "First Player":
                    _process_match(first_key, first_name, second_key, second_name, surface, i)
                elif winner == "Second Player":
                    _process_match(second_key, second_name, first_key, first_name, surface, i)

                # ── Extraire les stats de performance ──
                stats_data = match.get("statistics", [])
                if stats_data:
                    _extract_perf_stats(first_key, second_key, stats_data, i)

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


def _extract_perf_stats(first_key: int, second_key: int,
                        stats_data: list, days_ago: int):
    """Extrait les stats de performance d'un match pour les deux joueurs."""
    # Organiser les stats par joueur (utiliser seulement les stats "match" globales)
    player_stats = {}
    for stat in stats_data:
        pk = stat.get("player_key")
        period = stat.get("stat_period", "")
        if period != "match":  # On ne prend que les stats du match complet
            continue
        if pk not in player_stats:
            player_stats[pk] = {}
        name = stat.get("stat_name", "")
        player_stats[pk][name] = {
            "won": stat.get("stat_won"),
            "total": stat.get("stat_total"),
            "value": stat.get("stat_value", ""),
        }

    for pk in [first_key, second_key]:
        if pk not in player_stats:
            continue
        if pk not in _elo_ratings:
            continue

        ps = player_stats[pk]
        perf = MatchPerf(days_ago=days_ago)

        # Service Points Won
        spw = ps.get("Service Points Won", {})
        if spw.get("won") is not None and spw.get("total"):
            perf.service_points_won = int(spw["won"])
            perf.service_points_total = int(spw["total"])

        # Return Points Won
        rpw = ps.get("Return Points Won", {})
        if rpw.get("won") is not None and rpw.get("total"):
            perf.return_points_won = int(rpw["won"])
            perf.return_points_total = int(rpw["total"])

        # Break Points Saved
        bps = ps.get("Break Points Saved", {})
        bps_val = bps.get("value", "")
        if "/" in str(bps_val):
            parts = str(bps_val).split("/")
            try:
                perf.break_points_saved = int(parts[0])
                perf.break_points_faced = int(parts[1])
            except (ValueError, IndexError):
                pass

        # Break Points Converted
        bpc = ps.get("Break Points Converted", {})
        bpc_val = bpc.get("value", "")
        if "/" in str(bpc_val):
            parts = str(bpc_val).split("/")
            try:
                perf.break_points_converted = int(parts[0])
                perf.break_points_chances = int(parts[1])
            except (ValueError, IndexError):
                pass

        # Service games won
        sgw = ps.get("Service games won", {})
        if sgw.get("won") is not None and sgw.get("total"):
            perf.service_games_won = int(sgw["won"])
            perf.service_games_total = int(sgw["total"])

        # Return games won
        rgw = ps.get("Return games won", {})
        if rgw.get("won") is not None and rgw.get("total"):
            perf.return_games_won = int(rgw["won"])
            perf.return_games_total = int(rgw["total"])

        # Ajouter si on a des données significatives
        if perf.service_points_total > 0 or perf.return_points_total > 0:
            _elo_ratings[pk].perf_history.append(perf)


def get_weighted_perf_stats(player_name: str) -> Optional[dict]:
    """
    Calcule les stats de performance moyennes pondérées par récence.
    
    Retourne un dict avec :
    - service_points_won_pct : % points gagnés au service
    - return_points_won_pct : % points gagnés au retour
    - bp_saved_pct : % break points sauvés
    - bp_converted_pct : % break points convertis
    - hold_pct : % jeux de service gardés
    - break_pct : % jeux de retour breakés
    """
    elo = get_elo_by_name(player_name)
    if not elo or not elo.perf_history:
        return None

    DECAY = 60.0

    # Accumulateurs pondérés
    w_spw, w_spt = 0.0, 0.0
    w_rpw, w_rpt = 0.0, 0.0
    w_bps, w_bpf = 0.0, 0.0
    w_bpc, w_bpch = 0.0, 0.0
    w_sgw, w_sgt = 0.0, 0.0
    w_rgw, w_rgt = 0.0, 0.0

    for perf in elo.perf_history:
        weight = math.exp(-perf.days_ago / DECAY)

        w_spw += perf.service_points_won * weight
        w_spt += perf.service_points_total * weight
        w_rpw += perf.return_points_won * weight
        w_rpt += perf.return_points_total * weight
        w_bps += perf.break_points_saved * weight
        w_bpf += perf.break_points_faced * weight
        w_bpc += perf.break_points_converted * weight
        w_bpch += perf.break_points_chances * weight
        w_sgw += perf.service_games_won * weight
        w_sgt += perf.service_games_total * weight
        w_rgw += perf.return_games_won * weight
        w_rgt += perf.return_games_total * weight

    result = {
        "service_points_won_pct": w_spw / w_spt if w_spt > 0 else None,
        "return_points_won_pct": w_rpw / w_rpt if w_rpt > 0 else None,
        "bp_saved_pct": w_bps / w_bpf if w_bpf > 0 else None,
        "bp_converted_pct": w_bpc / w_bpch if w_bpch > 0 else None,
        "hold_pct": w_sgw / w_sgt if w_sgt > 0 else None,
        "break_pct": w_rgw / w_rgt if w_rgt > 0 else None,
        "matches_with_stats": len(elo.perf_history),
    }

    return result


def get_elo_by_name(player_name: str) -> Optional[PlayerElo]:
    """Cherche un joueur par nom (correspondance partielle)."""
    name_lower = player_name.lower().strip()

    for elo in _elo_ratings.values():
        if elo.name.lower().strip() == name_lower:
            return elo

    parts = name_lower.split()
    target_surname = parts[-1] if parts else ""
    for elo in _elo_ratings.values():
        elo_parts = elo.name.lower().split()
        elo_surname = elo_parts[-1] if elo_parts else ""
        if target_surname and len(target_surname) > 2 and target_surname == elo_surname:
            return elo

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
    return expected_score(elo_a, elo_b)


def _ensure_player(player_key: int, player_name: str):
    """Crée un joueur dans le cache s'il n'existe pas encore."""
    if player_key not in _elo_ratings:
        _elo_ratings[player_key] = PlayerElo(name=player_name, player_key=player_key)


def get_player_withdrawals(player_name: str) -> dict:
    """
    Retourne l'historique des retraits/walkovers d'un joueur.
    {
        "total": int,
        "retirements": int,
        "walkovers": int,
        "last_withdrawal": {"days_ago": int, "type": str} ou None,
        "has_recent": bool  (dans les 14 derniers jours)
    }
    """
    elo = get_elo_by_name(player_name)
    if not elo or not elo.retirements:
        return {
            "total": 0,
            "retirements": 0,
            "walkovers": 0,
            "last_withdrawal": None,
            "has_recent": False,
        }

    retirements = [(d, t) for d, t in elo.retirements if t == "retired"]
    walkovers = [(d, t) for d, t in elo.retirements if t == "walkover"]

    # Trouver le plus récent
    all_sorted = sorted(elo.retirements, key=lambda x: x[0])
    last = all_sorted[0] if all_sorted else None

    return {
        "total": len(elo.retirements),
        "retirements": len(retirements),
        "walkovers": len(walkovers),
        "last_withdrawal": {"days_ago": last[0], "type": last[1]} if last else None,
        "has_recent": last[0] <= 14 if last else False,
    }
