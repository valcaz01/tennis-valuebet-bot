"""
Formatage des messages Telegram (Markdown v2)
"""

from datetime import datetime, timezone, timedelta
from analyzer import ValueBet
from data_fetcher import Match


def _is_tomorrow(commence_time: str) -> bool:
    """Vérifie si un match est demain."""
    try:
        dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).date()
        return dt.date() == tomorrow
    except Exception:
        return False


def fmt_valuebet_alert(vb: ValueBet, player_withdrawals: dict = None,
                       opponent_withdrawals: dict = None) -> str:
    """Message d'alerte pour un value bet détecté."""
    dt = datetime.fromisoformat(vb.match.commence_time.replace("Z", "+00:00"))
    match_time = dt.strftime("%d/%m %H:%M UTC")
    tomorrow_badge = " ⏰ _DEMAIN_" if _is_tomorrow(vb.match.commence_time) else ""

    bar = _edge_bar(vb.edge)

    lines = [
        f"🎾 *VALUE BET DÉTECTÉ*{tomorrow_badge}",
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
    ] + _fmt_factors(vb.factors)

    # Section retraits
    withdrawal_lines = _fmt_withdrawals(vb.player, player_withdrawals,
                                         vb.opponent, opponent_withdrawals)
    if withdrawal_lines:
        lines.append(f"")
        lines.extend(withdrawal_lines)

    lines.extend([
        f"",
        f"⚠️ _Pari à tes risques\\. Joue responsable\\._",
    ])

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
        tomorrow = " ⏰" if _is_tomorrow(vb.match.commence_time) else ""
        lines.append(
            f"{i}\\. {escape(vb.player)} vs {escape(vb.opponent)}{tomorrow} "
            f"— cote `{vb.best_odds:.2f}` — edge `{vb.edge_pct}`"
        )

    return "\n".join(lines)


def fmt_match_list(matches: list[Match]) -> str:
    """Liste des matchs récupérés."""
    if not matches:
        return "Aucun match trouvé\\."

    lines = [f"📋 *{len(matches)} matchs à venir*\n"]
    for m in matches[:20]:
        dt = datetime.fromisoformat(m.commence_time.replace("Z", "+00:00"))
        time_str = dt.strftime("%d/%m %H:%M")
        bms = len(m.odds)
        tomorrow = " ⏰" if _is_tomorrow(m.commence_time) else ""
        lines.append(
            f"• {escape(m.player1)} vs {escape(m.player2)}{tomorrow}\n"
            f"  {escape(time_str)} \\| {bms} bookmakers"
        )

    if len(matches) > 20:
        lines.append(f"\n_\\.\\.\\. et {len(matches) - 20} autres matchs_")

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
    """Affiche le détail des facteurs."""
    labels = {
        "elo":          "Elo surface",
        "performance":  "Performance",
        "form":         "Forme récente",
        "market":       "Marché",
        "h2h":          "H2H",
        "context":      "Contexte",
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


def _fmt_withdrawals(player: str, player_wd: dict,
                     opponent: str, opponent_wd: dict) -> list[str]:
    """Formate la section retraits/walkovers."""
    lines = []
    has_info = False

    for name, wd in [(player, player_wd), (opponent, opponent_wd)]:
        if not wd or wd.get("total", 0) == 0:
            continue

        has_info = True
        total = wd["total"]
        ret = wd["retirements"]
        wo = wd["walkovers"]
        last = wd.get("last_withdrawal")

        if last:
            days = last["days_ago"]
            wtype = "abandon" if last["type"] == "retired" else "forfait"

            if days <= 7:
                emoji = "🔴"
                urgency = "ATTENTION"
            elif days <= 14:
                emoji = "🟠"
                urgency = "Récent"
            else:
                emoji = "🟡"
                urgency = "Noté"

            lines.append(
                f"{emoji} *{escape(urgency)}* — {escape(name)} : "
                f"dernier {escape(wtype)} il y a `{days}` jours"
            )
            if total > 1:
                detail = []
                if ret > 0:
                    detail.append(f"{ret} abandon\\(s\\)")
                if wo > 0:
                    detail.append(f"{wo} forfait\\(s\\)")
                lines.append(f"   _{escape(str(total))} incidents sur 90j : {', '.join(detail)}_")

    if has_info:
        lines.insert(0, f"🏥 *Alertes santé*")

    return lines


def fmt_totals_alert(tb) -> str:
    """Message d'alerte pour un pari over/under détecté."""
    from totals_analyzer import is_tomorrow as _is_tmrw
    dt = datetime.fromisoformat(tb.match.commence_time.replace("Z", "+00:00"))
    match_time = dt.strftime("%d/%m %H:%M UTC")
    tomorrow_badge = " ⏰ _DEMAIN_" if _is_tmrw(tb.match.commence_time) else ""

    side_emoji = "⬆️" if tb.side == "over" else "⬇️"
    side_label = f"Over {tb.line}" if tb.side == "over" else f"Under {tb.line}"

    lines = [
        f"{side_emoji} *{escape(side_label)} JEUX*{tomorrow_badge}",
        f"",
        f"🏆 {escape(tb.match.tournament)}",
        f"📅 {escape(match_time)}",
        f"🆚 {escape(tb.match.player1)} vs {escape(tb.match.player2)}",
        f"",
        f"📊 *Analyse*",
        f"├ Jeux estimés : `{tb.estimated_games:.1f}`",
        f"├ Ligne : `{tb.line}`",
        f"├ Cote : `{tb.best_odds:.2f}` \\({escape(tb.bookmaker)}\\)",
        f"└ Edge : `{tb.edge_pct}`",
        f"",
        f"💡 *Confiance :* {tb.confidence}",
        f"",
        f"⚠️ _Pari à tes risques\\. Joue responsable\\._",
    ]

    return "\n".join(lines)


def fmt_totals_summary(totals_bets: list, matches_count: int) -> str:
    """Résumé des paris over/under détectés."""
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
    if not totals_bets:
        return (
            f"📏 *Scan Over/Under terminé* \\({escape(ts)}\\)\n"
            f"Matchs analysés : {matches_count}\n"
            f"Aucun value bet over/under détecté\\."
        )

    from totals_analyzer import is_tomorrow as _is_tmrw
    lines = [
        f"📏 *Scan Over/Under terminé* \\({escape(ts)}\\)",
        f"Matchs analysés : `{matches_count}`",
        f"Value bets trouvés : `{len(totals_bets)}`",
        f"",
    ]
    for i, tb in enumerate(totals_bets, 1):
        side_emoji = "⬆️" if tb.side == "over" else "⬇️"
        side_label = f"O{tb.line}" if tb.side == "over" else f"U{tb.line}"
        tomorrow = " ⏰" if _is_tmrw(tb.match.commence_time) else ""
        lines.append(
            f"{i}\\. {side_emoji} {escape(side_label)} {escape(tb.match.player1)} vs {escape(tb.match.player2)}{tomorrow} "
            f"— cote `{tb.best_odds:.2f}` — edge `{tb.edge_pct}`"
        )

    return "\n".join(lines)
