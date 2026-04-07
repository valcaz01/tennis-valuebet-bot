"""
Formatage des messages Telegram (Markdown v2)
"""

from datetime import datetime, timezone
from analyzer import ValueBet
from data_fetcher import Match


def fmt_valuebet_alert(vb: ValueBet) -> str:
    """Message d'alerte pour un value bet détecté."""
    dt = datetime.fromisoformat(vb.match.commence_time.replace("Z", "+00:00"))
    match_time = dt.strftime("%d/%m %H:%M UTC")

    bar = _edge_bar(vb.edge)

    lines = [
        f"🎾 *VALUE BET DÉTECTÉ*",
        f"",
        f"🏆 {escape(vb.match.tournament)}",
        f"📅 {escape(match_time)}",
        f"",
        f"👤 *Joueur :* {escape(vb.player)}",
        f"🆚 contre {escape(vb.opponent)}",
        f"",
        f"📊 *Analyse*",
        f"├ Cote : `{vb.best_odds:.2f}`",
        f"├ P\\. estimée : `{vb.p_estimated * 100:.1f}%`",
        f"├ P\\. marché : `{vb.p_implied * 100:.1f}%`",
        f"└ Edge : `{vb.edge_pct}` {bar}",
        f"",
        f"💡 *Confiance :* {vb.confidence}",
        f"💶 *Mise Kelly* \\(¼\\) : `{vb.kelly_stake:.0f} €`",
        f"",
        f"📈 *Facteurs*",
    ] + _fmt_factors(vb.factors) + [
        f"",
        f"⚠️ _Pari à tes risques\\. Joue responsable\\._",
    ]

    return "\n".join(lines)


def fmt_scan_summary(vbs: list[ValueBet], matches_count: int) -> str:
    """Résumé après un scan."""
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
    if not vbs:
        return (
            f"🔍 *Scan terminé* \\({escape(ts)}\\)\n"
            f"Matchs analysés : {matches_count}\n"
            f"Aucun value bet détecté au\\-dessus du seuil\\."
        )

    lines = [
        f"🔍 *Scan terminé* \\({escape(ts)}\\)",
        f"Matchs analysés : `{matches_count}`",
        f"Value bets trouvés : `{len(vbs)}`",
        f"",
    ]
    for i, vb in enumerate(vbs, 1):
        lines.append(
            f"{i}\\. {escape(vb.player)} vs {escape(vb.opponent)} "
            f"— cote `{vb.best_odds:.2f}` — edge `{vb.edge_pct}`"
        )

    return "\n".join(lines)


def fmt_match_list(matches: list[Match]) -> str:
    """Liste des matchs récupérés."""
    if not matches:
        return "Aucun match à venir trouvé\\."

    lines = [f"📋 *{len(matches)} matchs du jour*\n"]
    for m in matches[:15]:
        dt = datetime.fromisoformat(m.commence_time.replace("Z", "+00:00"))
        time_str = dt.strftime("%d/%m %H:%M")
        bms = len(m.odds)
        lines.append(
            f"• {escape(m.player1)} vs {escape(m.player2)}\n"
            f"  {escape(time_str)} \\| {bms} bookmakers"
        )

    if len(matches) > 15:
        lines.append(f"\n_\\.\\.\\. et {len(matches) - 15} autres matchs_")

    return "\n".join(lines)


def fmt_status(config: dict) -> str:
    """Affiche la configuration actuelle."""
    lines = [
        "⚙️ *Configuration actuelle*",
        f"",
        f"Edge minimum : `{config['min_edge'] * 100:.0f}%`",
        f"Fraction Kelly : `{config['kelly_fraction'] * 100:.0f}%`",
        f"Bankroll : `{config['bankroll']:.0f} €`",
        f"Scan toutes les : `{config['scan_interval']} min`",
        f"",
        f"*Poids des facteurs*",
    ]
    for factor, weight in config["weights"].items():
        lines.append(f"├ {escape(factor)} : `{weight * 100:.0f}%`")

    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def escape(text: str) -> str:
    """Échappe les caractères spéciaux Markdown v2."""
    special = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in str(text))


def _edge_bar(edge: float) -> str:
    """Barre visuelle de l'edge."""
    blocks = min(10, int(edge * 100 / 3))
    bar = "█" * blocks + "░" * (10 - blocks)
    return f"`{bar}`"


def _fmt_factors(factors: dict) -> list[str]:
    """Affiche le détail des facteurs sous forme de mini-barres."""
    labels = {
        "elo":         "Elo",
        "ranking":     "Ranking",
        "recent_form": "Forme récente",
        "surface":     "Surface",
        "h2h":         "H2H",
        "fatigue":     "Fraîcheur",
        "context":     "Contexte",
    }
    lines = []
    items = list(factors.items())
    for i, (k, v) in enumerate(items):
        prefix = "└" if i == len(items) - 1 else "├"
        bar_len = int(v * 10)
        bar = "▓" * bar_len + "░" * (10 - bar_len)
        label = escape(labels.get(k, k))
        lines.append(f"{prefix} {label} : `{bar}` `{v * 100:.0f}%`")
    return lines
