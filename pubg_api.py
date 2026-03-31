#!/usr/bin/env python3
"""PUBG API client — reusable module for all PUBG-related bot features."""
import os
import requests
import time
from datetime import datetime, date, timezone, timedelta

PUBG_API_KEY = os.environ["PUBG_API_KEY"]
PUBG_BASE_URL = "https://api.pubg.com"
CST = timezone(timedelta(hours=8))
DEFAULT_SHARD = "steam"

MODE_CN = {
    "solo":      "单排",
    "solo-fpp":  "单排FPP",
    "duo":       "双排",
    "duo-fpp":   "双排FPP",
    "squad":     "四排",
    "squad-fpp": "四排FPP",
}
MODE_ORDER = ["squad", "squad-fpp", "duo", "duo-fpp", "solo", "solo-fpp"]


def _cst_today() -> date:
    return datetime.now(CST).date()


def _pct(n, total) -> str:
    return f"{n / total * 100:.1f}%" if total else "0%"


def _km(m: float) -> str:
    return f"{m / 1000:.1f}km"


def _hm(seconds: float) -> str:
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    return f"{h}h{m:02d}m"


def _min_str(seconds: float) -> str:
    return f"{seconds / 60:.1f}min"


# ══════════════════════════════════════════════════
# API Client
# ══════════════════════════════════════════════════

class PubgClient:
    def __init__(self, api_key: str = PUBG_API_KEY):
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/vnd.api+json",
        })

    def _get(self, path: str, **kwargs):
        r = self._session.get(f"{PUBG_BASE_URL}{path}", timeout=15, **kwargs)
        r.raise_for_status()
        return r.json()

    def get_player(self, player_name: str, shard: str = DEFAULT_SHARD) -> dict:
        try:
            data = self._get(
                f"/shards/{shard}/players",
                params={"filter[playerNames]": player_name},
            )
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                raise ValueError(f"找不到玩家 [{player_name}]，请确认 ID 是否正确（区分大小写）")
            raise
        players = data.get("data", [])
        if not players:
            raise ValueError(f"找不到玩家：{player_name}")
        return players[0]

    def get_current_season(self, shard: str = DEFAULT_SHARD) -> str:
        seasons = self._get(f"/shards/{shard}/seasons")["data"]
        for s in seasons:
            if s["attributes"].get("isCurrentSeason"):
                return s["id"]
        return seasons[-1]["id"]

    def get_season_stats(self, player_name: str, season_id: str = None, shard: str = DEFAULT_SHARD) -> dict:
        player = self.get_player(player_name, shard)
        if season_id is None:
            season_id = self.get_current_season(shard)
        r = self._get(f"/shards/{shard}/players/{player['id']}/seasons/{season_id}")
        return {
            "player_name": player_name,
            "season_id":   season_id,
            "modes":       r["data"]["attributes"]["gameModeStats"],
        }

    def get_ranked_stats(self, player_name: str, season_id: str = None, shard: str = DEFAULT_SHARD) -> dict:
        player = self.get_player(player_name, shard)
        if season_id is None:
            season_id = self.get_current_season(shard)
        r = self._get(f"/shards/{shard}/players/{player['id']}/seasons/{season_id}/ranked")
        return {
            "player_name": player_name,
            "season_id":   season_id,
            "modes":       r["data"]["attributes"]["rankedGameModeStats"],
        }

    def get_lifetime_stats(self, player_name: str, shard: str = DEFAULT_SHARD) -> dict:
        player = self.get_player(player_name, shard)
        r = self._get(f"/shards/{shard}/players/{player['id']}/seasons/lifetime")
        return {
            "player_name": player_name,
            "modes":       r["data"]["attributes"]["gameModeStats"],
        }

    def get_stats_for_date(self, player_name: str, target_date: date = None, shard: str = DEFAULT_SHARD) -> dict | None:
        if target_date is None:
            target_date = _cst_today()
        player = self.get_player(player_name, shard)
        account_id = player["id"]
        match_refs = player.get("relationships", {}).get("matches", {}).get("data", [])

        stats_list = []
        for idx, ref in enumerate(match_refs):
            if idx > 0:
                time.sleep(0.15)
            try:
                match = self._get(f"/shards/{shard}/matches/{ref['id']}")
            except Exception:
                continue
            created_at_str = match["data"]["attributes"].get("createdAt", "")
            try:
                created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                match_date = created_at.astimezone(CST).date()
            except Exception:
                continue
            if match_date < target_date:
                break
            if match_date != target_date:
                continue
            p = self._find_participant(match, account_id)
            if p:
                stats_list.append(p)

        if not stats_list:
            return None
        return self._aggregate(stats_list, player_name, target_date)

    def get_today_stats(self, player_name: str, shard: str = DEFAULT_SHARD):
        return self.get_stats_for_date(player_name, _cst_today(), shard)

    def get_yesterday_stats(self, player_name: str, shard: str = DEFAULT_SHARD):
        return self.get_stats_for_date(player_name, _cst_today() - timedelta(days=1), shard)

    @staticmethod
    def _find_participant(match_data: dict, account_id: str) -> dict | None:
        for item in match_data.get("included", []):
            if item.get("type") != "participant":
                continue
            s = item.get("attributes", {}).get("stats", {})
            if s.get("playerId") == account_id:
                return s
        return None

    @staticmethod
    def _aggregate(stats_list: list, player_name: str, match_date: date) -> dict:
        n = len(stats_list)
        total_kills  = sum(s.get("kills", 0) for s in stats_list)
        total_damage = sum(s.get("damageDealt", 0.0) for s in stats_list)
        total_assists  = sum(s.get("assists", 0) for s in stats_list)
        total_revives  = sum(s.get("revives", 0) for s in stats_list)
        total_dbnos    = sum(s.get("DBNOs", 0) for s in stats_list)
        total_boosts   = sum(s.get("boosts", 0) for s in stats_list)
        wins  = sum(1 for s in stats_list if s.get("winPlace") == 1)
        top10 = sum(1 for s in stats_list if s.get("winPlace", 99) <= 10)
        max_kills  = max(s.get("kills", 0) for s in stats_list)
        max_damage = max(s.get("damageDealt", 0.0) for s in stats_list)
        deaths = n - wins
        kd_ratio = round(total_kills / deaths, 2) if deaths > 0 else float(total_kills)
        return {
            "player_name":   player_name,
            "date":          str(match_date),
            "games":         n,
            "total_kills":   total_kills,
            "total_damage":  round(total_damage, 1),
            "total_assists": total_assists,
            "total_revives": total_revives,
            "total_dbnos":   total_dbnos,
            "wins":          wins,
            "top10":         top10,
            "max_kills":     max_kills,
            "max_damage":    round(max_damage, 1),
            "avg_kills":     round(total_kills / n, 2),
            "avg_damage":    round(total_damage / n, 1),
            "kd_ratio":      kd_ratio,
            "total_boosts":  total_boosts,
        }


# ══════════════════════════════════════════════════
# Formatting  —  mobile-friendly, no markdown
# ══════════════════════════════════════════════════

def _date_label(date_str: str) -> str:
    today = _cst_today()
    try:
        d = date.fromisoformat(date_str)
        if d == today:
            return "今日"
        if d == today - timedelta(days=1):
            return "昨日"
    except Exception:
        pass
    return date_str


def _season_short(season_id: str) -> str:
    return season_id.replace("division.bro.official.", "")


def format_stats_report(stats: dict | None, player_name: str = "") -> str:
    """Today / yesterday match report."""
    if stats is None:
        return f"📊 {player_name or '该玩家'} 该日期暂无 PUBG 记录"
    label = _date_label(stats["date"])
    try:
        d = date.fromisoformat(stats["date"])
        date_str = f"{d.month}/{d.day}"
    except Exception:
        date_str = stats["date"]
    n = stats["games"]
    wins  = stats["wins"]
    top10 = stats["top10"]
    win_rate  = f"{wins  / n * 100:.0f}%" if n else "0%"
    top_rate  = f"{top10 / n * 100:.0f}%" if n else "0%"
    lines = [
        f"🎮 {stats['player_name']} {label}战报 ({date_str})",
        "",
        f"出战 {n}场 · 吃鸡 {wins}({win_rate}) · 前10 {top10}({top_rate})",
        f"KD {stats['kd_ratio']} · 场均击杀 {stats['avg_kills']}",
        "",
        f"击杀 {stats['total_kills']} · 最高单场 {stats['max_kills']} · 击倒 {stats['total_dbnos']}",
        f"助攻 {stats['total_assists']} · 救援 {stats['total_revives']}",
        "",
        f"伤害 {stats['total_damage']} · 场均 {stats['avg_damage']} · 最高 {stats['max_damage']}",
    ]
    boosts = stats.get("total_boosts", 0)
    if boosts:
        lines.append(f"喝罐 {boosts}个")
    return "\n".join(lines)


def _format_normal_mode(mode_cn: str, s: dict) -> str:
    """One game-mode block for season / lifetime report."""
    n      = s.get("roundsPlayed", 0)
    wins   = s.get("wins", 0)
    top10  = s.get("top10s", 0)
    kills  = s.get("kills", 0)
    deaths = max(n - wins, 1)
    assists = s.get("assists", 0)
    kd     = round(kills / deaths, 2)
    kda    = round((kills + assists) / deaths, 2)
    damage = s.get("damageDealt", 0.0)
    hs     = s.get("headshotKills", 0)
    total_sec = s.get("timeSurvived", 0)
    avg_sec   = total_sec / n if n else 0

    lines = [
        f"▸ {mode_cn} · {n}场",
        f"胜 {wins}({_pct(wins,n)}) · 前10 {top10}({_pct(top10,n)})",
        f"击 {kills} · 助 {assists} · 倒 {s.get('dBNOs',0)} · 救 {s.get('revives',0)}",
        f"KD {kd} · KDA {kda} · 爆头 {hs}({_pct(hs,kills)})",
        f"总伤 {round(damage,1)} · 场均 {round(damage/n,1) if n else 0}",
        f"最远 {round(s.get('longestKill',0))}m · 单场最多 {s.get('roundMostKills',0)} · 连杀 {s.get('maxKillStreaks',0)}",
        f"游玩 {_hm(total_sec)} · 均存 {_min_str(avg_sec)}",
        f"步行 {_km(s.get('walkDistance',0))} · 载具 {_km(s.get('rideDistance',0))}",
        f"喝罐 {s.get('boosts',0)} · 治疗 {s.get('heals',0)} · 拾枪 {s.get('weaponsAcquired',0)}",
    ]
    extras = []
    if s.get("roadKills"):    extras.append(f"路杀 {s['roadKills']}")
    if s.get("vehicleDestroys"): extras.append(f"摧毁 {s['vehicleDestroys']}")
    if s.get("teamKills"):    extras.append(f"友伤 {s['teamKills']}")
    if s.get("suicides"):     extras.append(f"自杀 {s['suicides']}")
    if extras:
        lines.append(" · ".join(extras))
    return "\n".join(lines)


def format_season_report(data: dict) -> str:
    name   = data["player_name"]
    sid    = _season_short(data["season_id"])
    active = {k: v for k, v in data["modes"].items()
              if v.get("roundsPlayed", 0) > 0 and k in {"squad"}}
    if not active:
        return f"📊 {name} 本赛季暂无 PUBG 记录"
    parts = [f"📊 {name} 本赛季战绩({sid})"]
    for k in MODE_ORDER:
        if k in active:
            parts.append("")
            parts.append(_format_normal_mode(MODE_CN.get(k, k), active[k]))
    return "\n".join(parts)


def format_lifetime_report(data: dict) -> str:
    name   = data["player_name"]
    active = {k: v for k, v in data["modes"].items()
              if v.get("roundsPlayed", 0) > 0 and k in {"squad"}}
    if not active:
        return f"🎖 {name} 暂无生涯 PUBG 记录"
    parts = [f"🎖 {name} 生涯统计"]
    for k in MODE_ORDER:
        if k in active:
            parts.append("")
            parts.append(_format_normal_mode(MODE_CN.get(k, k), active[k]))
    return "\n".join(parts)


def format_ranked_report(data: dict) -> str:
    name   = data["player_name"]
    sid    = _season_short(data["season_id"])
    active = {k: v for k, v in data["modes"].items()
              if v.get("roundsPlayed", 0) > 0 and k in {"squad"}}
    if not active:
        return f"🏅 {name} 本赛季暂无排位记录"
    parts = [f"🏅 {name} 本赛季排位({sid})"]
    for k in MODE_ORDER:
        if k not in active:
            continue
        s  = active[k]
        cn = MODE_CN.get(k, k)
        n  = s.get("roundsPlayed", 0)
        cur  = s.get("currentTier", {})
        best = s.get("bestTier", {})
        wins    = s.get("wins", 0)
        kills   = s.get("kills", 0)
        deaths  = s.get("deaths", 0) or max(n - wins, 1)
        assists = s.get("assists", 0)
        kd      = round(kills / deaths, 2) if deaths else kills
        kda     = round((kills + assists) / deaths, 2) if deaths else kills + assists
        top10_cnt = round(n * s.get("top10Ratio", 0))
        avg_rank  = round(s.get("avgRank", 0), 1)
        damage    = s.get("damageDealt", 0.0)
        parts.append("")
        parts.append(
            f"▸ {cn} · {n}场\n"
            f"当前 {cur.get('tier','')} {cur.get('subTier','')} · {s.get('currentRankPoint',0)} RP\n"
            f"最高 {best.get('tier','')} {best.get('subTier','')} · {s.get('bestRankPoint',0)} RP\n"
            f"胜 {wins}({_pct(wins,n)}) · 前10 {top10_cnt}({_pct(top10_cnt,n)}) · 均排名 {avg_rank}\n"
            f"击 {kills} · 助 {assists} · 倒 {s.get('dBNOs',0)}\n"
            f"KD {kd} · KDA {kda} · 均杀 {round(s.get('avgKill', kills/n if n else 0),2)}\n"
            f"总伤 {round(damage,1)}"
        )
    return "\n".join(parts)


# backward-compat alias
format_today_report = format_stats_report
