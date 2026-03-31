#!/usr/bin/env python3
"""
Daily PUBG title report generator.

Fetches yesterday's match stats for all registered players,
awards titles, and returns a formatted WeChat message.
"""
import logging
from datetime import datetime, timedelta
from pubg_api import PubgClient, CST
from player_registry import get_all_players

log = logging.getLogger(__name__)

# ── Title definitions ────────────────────────────────────────────
#   (emoji, title, dimension_desc, score_fn, detail_fn)
#
#   score_fn(stats)  → comparable value used to find the winner
#   detail_fn(stats) → string shown after "PlayerID ·"

TITLES = [
    (
        "🔫", "击杀王", "最多总击杀",
        lambda s: s["total_kills"],
        lambda s: f"{s['total_kills']} 杀",
    ),
    (
        "✈️", "跳伞大师", "最多游玩场数",
        lambda s: s["games"],
        lambda s: f"{s['games']} 场",
    ),
    (
        "🛠", "打工皇帝", "最多助攻",
        lambda s: s["total_assists"],
        lambda s: f"{s['total_assists']} 助攻",
    ),
    (
        "💀", "K头怪", "击杀/伤害比最高",
        lambda s: s["total_kills"] / max(s["total_damage"], 1),
        lambda s: (
            f"{s['total_kills']} 杀 / {round(s['total_damage'])} 伤"
            f"（每百伤 {round(s['total_kills'] / max(s['total_damage'], 1) * 100, 2)} 杀）"
        ),
    ),
    (
        "⚡", "KD冠军", "最高 KD",
        lambda s: s["kd_ratio"],
        lambda s: f"KD {s['kd_ratio']}",
    ),
    (
        "💥", "输出大师", "最高场均伤害",
        lambda s: s["avg_damage"],
        lambda s: f"场均 {s['avg_damage']} 伤",
    ),
    (
        "💊", "华佗在世", "救援最多",
        lambda s: s["total_revives"],
        lambda s: f"救了 {s['total_revives']} 次",
    ),
    (
        "📷", "战地记者", "最少击杀最多吃鸡",
        lambda s: s["wins"] / max(s["total_kills"], 1),
        lambda s: f"{s['wins']} 胜 / {s['total_kills']} 杀",
    ),
    (
        "🥤", "吃喝王", "喝罐最多",
        lambda s: s.get("total_boosts", 0),
        lambda s: f"喝了 {s.get('total_boosts', 0)} 罐",
    ),
]


# ── Fetch ────────────────────────────────────────────────────────

def fetch_yesterday_stats() -> dict:
    """
    Return {player_name: stats_dict_or_None} for all registered players.
    stats_dict is None when the player had no games yesterday.
    """
    players = get_all_players()
    if not players:
        return {}

    client = PubgClient()
    yesterday = (datetime.now(CST) - timedelta(days=1)).date()
    result = {}
    for player in players:
        try:
            result[player] = client.get_stats_for_date(player, yesterday)
        except Exception as e:
            log.warning(f"fetch stats for {player}: {e}")
            result[player] = None
    return result


# ── Format ───────────────────────────────────────────────────────

def build_report(stats_map: dict) -> str:
    """Build the full daily title report string."""
    yesterday_str = (datetime.now(CST) - timedelta(days=1)).strftime("%m/%d")

    # Only players who actually played yesterday
    active = {
        p: s for p, s in stats_map.items()
        if s is not None and s.get("games", 0) > 0
    }

    header = f"🏆 昨日战绩排行榜 ({yesterday_str})"

    if not active:
        no_data = [p for p, s in stats_map.items() if s is None or s.get("games", 0) == 0]
        msg = "昨日无玩家上线，摸鱼一天！"
        if no_data:
            msg += f"\n({' · '.join(no_data)} 均未出战)"
        return f"{header}\n{msg}"

    lines = [header, ""]

    # ── Title awards ────────────────────────────────────────────
    first = True
    for emoji, title, dim, score_fn, detail_fn in TITLES:
        try:
            winner = max(active, key=lambda p: score_fn(active[p]))
            score = score_fn(active[winner])
            # Skip if the winning score is 0 (nobody actually did this)
            if score == 0:
                continue
            detail = detail_fn(active[winner])
            if not first:
                lines.append("")
            first = False
            lines.append(f"{emoji} {title}")
            lines.append(f"   {winner} · {detail}")
        except Exception:
            pass

    # Players who didn't play
    idle = [p for p, s in stats_map.items() if s is None or s.get("games", 0) == 0]
    if idle:
        lines.append("")
        lines.append(f"未出战：{' · '.join(idle)}")

    return "\n".join(lines)


def generate() -> str:
    """Convenience: fetch + build in one call."""
    return build_report(fetch_yesterday_stats())
