"""
Formatage des messages Telegram (Markdown v2)
Messages compacts — un seul message par commande.
"""

from datetime import datetime, timezone, timedelta
from analyzer import ValueBet
from data_fetcher import Match


def _is_tomorrow(commence_time: str) -> bool:
    try:
        dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).date()
        return dt.date() == tomorrow
    except Exception:
        return False


def _time_str(commence_time: str) -> str:
    try:
        dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except Exception:
        return "?"


# ── SCAN ML — Un seul message compact ─────────────────────────────────────────

def fmt_scan_compact(vbs: list[ValueBet], matches_count: int,
                     withdrawals: dict = None) -> str:
    """
    Message compact unique pour /scan.
    withdrawals = {player_name: withdrawal_dict}
    """
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")

    if not vbs:
        return (
            f"🔍 *Scan ML terminé* \\({escape(ts)}\\)\n"
            f"Matchs analysés : `{matches_count}`\n\n"
            f"Aucun value bet détecté\\."
        )

    lines = [
        f"🔍 *SCAN ML* — {escape(ts)}",
        f"Matchs analysés : `{matches_count}` — VB trouvés : `{len(vbs)}`",
        f"",
    ]

    for i, vb in enumerate(vbs, 1):
        tmrw = " ⏰" if _is_tomorrow(vb.match.commence_time) else ""
        time = _time_str(vb.match.commence_time)
        conf_emoji = "🔥" if vb.edge >= 0.15 else ("✅" if vb.edge >= 0.08 else "⚠️")

        lines.append(f"{'─' * 30}")
        lines.append(
            f"{conf_emoji} *{escape(vb.player)}* vs {escape(vb.opponent)}{tmrw}"
        )
        lines.append(f"🏆 {escape(vb.match.tournament)} — {escape(time)}")
        lines.append(
            f"💰 Cote `{vb.best_odds:.2f}` — Edge `{vb.edge_pct}` — "
            f"Kelly `{vb.kelly_stake:.0f}€`"
        )
        lines.append(
            f"📊 P\\.est `{vb.p_estimated*100:.0f}%` vs P\\.marché `{vb.p_implied*100:.0f}%`"
        )

    # Section alertes santé (condensée)
    if withdrawals:
        wd_lines = []
        for vb in vbs:
            for name in [vb.player, vb.opponent]:
                wd = withdrawals.get(name)
                if wd and wd.get("total", 0) > 0:
                    last = wd.get("last_withdrawal")
                    if last:
                        days = last["days_ago"]
                        wtype = "abandon" if last["type"] == "retired" else "forfait"
                        emoji = "🔴" if days <= 7 else ("🟠" if days <= 14 else "🟡")
                        wd_lines.append(
                            f"{emoji} {escape(name)} — {escape(wtype)} il y a `{days}`j"
                        )

        if wd_lines:
            lines.append(f"")
            lines.append(f"🏥 *Alertes santé*")
            lines.extend(wd_lines)

    lines.append(f"")
    lines.append(f"⚠️ _Joue responsable\\._")

    return "\n".join(lines)


# ── TOTALS O/U — Un seul message compact ──────────────────────────────────────

def fmt_totals_compact(totals_bets: list, matches_count: int) -> str:
    """Message compact unique pour /totals."""
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")

    if not totals_bets:
        return (
            f"📏 *Scan O/U terminé* \\({escape(ts)}\\)\n"
            f"Matchs analysés : `{matches_count}`\n\n"
            f"Aucun value bet over/under détecté\\."
        )

    lines = [
        f"📏 *SCAN OVER/UNDER* — {escape(ts)}",
        f"Matchs analysés : `{matches_count}` — VB trouvés : `{len(totals_bets)}`",
        f"",
    ]

    for i, tb in enumerate(totals_bets, 1):
        tmrw = " ⏰" if _is_tomorrow(tb.match.commence_time) else ""
        time = _time_str(tb.match.commence_time)
        side_emoji = "⬆️" if tb.side == "over" else "⬇️"
        side_label = f"Over {tb.line}" if tb.side == "over" else f"Under {tb.line}"
        conf_emoji = "🔥" if tb.edge >= 0.12 else ("✅" if tb.edge >= 0.06 else "⚠️")

        lines.append(f"{'─' * 30}")
        lines.append(
            f"{side_emoji} {conf_emoji} *{escape(side_label)}*{tmrw}"
        )
        lines.append(
            f"🆚 {escape(tb.match.player1)} vs {escape(tb.match.player2)}"
        )
        lines.append(f"🏆 {escape(tb.match.tournament)} — {escape(time)}")
        lines.append(
            f"💰 Cote `{tb.best_odds:.2f}` \\({escape(tb.bookmaker)}\\) — "
            f"Edge `{tb.edge_pct}`"
        )
        lines.append(f"📊 Jeux estimés : `{tb.estimated_games:.1f}`")

    lines.append(f"")
    lines.append(f"⚠️ _Joue responsable\\._")

    return "\n".join(lines)


# ── Match list ────────────────────────────────────────────────────────────────

def fmt_match_list(matches: list[Match]) -> str:
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


# ── Status ────────────────────────────────────────────────────────────────────

def fmt_status(config: dict) -> str:
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
    special = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in str(text))
