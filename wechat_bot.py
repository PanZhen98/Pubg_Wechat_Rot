#!/usr/bin/env python3
import os
import requests
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pubg_api import PubgClient, format_stats_report, format_season_report, format_ranked_report, format_lifetime_report, CST
from player_registry import add_player, get_all_players
import daily_report as _daily_report_mod
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("/tmp/bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger()

AGENT_API  = "http://localhost:6174"
TOKEN_FILE = "/root/.config/agent-wechat/token"
AI_API     = "https://imds.ai/v1"
AI_KEY     = os.environ["AI_KEY"]
AI_MODEL   = "gpt-4o-mini"
POLL_SEC   = 1
SYSTEM_MSG = (
    "你是一个 PUBG 游戏群的专属 AI 机器人，名叫\"战地助手\"。\n"
    "你服务于一个 PUBG 游戏群，可以聊 PUBG 相关的一切，也可以回答群友的日常问题。\n"
    "\n"
    "【战绩查询指令】\n"
    "- 查询今日战报：直接发送 玩家ID（如：6umm）\n"
    "- 查询昨日战报：发送 玩家ID 昨日（如：6umm 昨日）\n"
    "- 查询本赛季/排位/生涯：发送 玩家ID 赛季/排位/生涯\n"
    "- 登记ID参与每日称号评选：发送 登记 玩家ID\n"
    "\n"
    "【回答原则】\n"
    "- 战绩数据由系统自动查询，不要自己编造数字。\n"
    "- 回答简洁自然，使用中文，保持 PUBG 游戏风格，可以适当幽默。\n"
    "- 严禁使用任何 Markdown 语法，包括 ##、**、`、---等，所有回复均为纯文本。"
)
GROUP_TRIGGERS = ["ai:", "AI:"]


def get_token():
    return open(TOKEN_FILE).read().strip()


def agent_get(path, token):
    r = requests.get(
        f"{AGENT_API}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10
    )
    r.raise_for_status()
    return r.json()


def agent_send(chat_id, text, token):
    body = json.dumps({"chatId": chat_id, "text": text}, ensure_ascii=False).encode("utf-8")
    r = requests.post(
        f"{AGENT_API}/api/messages/send",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        },
        data=body,
        timeout=15
    )
    r.raise_for_status()
    log.info(f"[SENT] {chat_id}: {text[:80]}")


def ai_reply(text, max_tokens=500):
    messages = [
        {"role": "system", "content": SYSTEM_MSG},
        {"role": "user", "content": text}
    ]
    r = requests.post(
        f"{AI_API}/chat/completions",
        headers={
            "Authorization": f"Bearer {AI_KEY}",
            "Content-Type": "application/json"
        },
        json={"model": AI_MODEL, "messages": messages, "max_tokens": max_tokens},
        timeout=30
    )
    r.raise_for_status()
    return json.loads(r.content)["choices"][0]["message"]["content"].strip()


def extract_group_query(content, chat_id=""):
    if content.startswith("@"):
        m = re.match(r"^@(\S+)\s+(.*)", content, re.DOTALL)
        if m:
            at_names = BOT_AT_NAMES_MAP.get(chat_id, BOT_AT_NAMES_DEFAULT)
            if m.group(1) in at_names:
                return m.group(2).strip()
    return None


PUBG_SHARD    = "steam"
BOT_WXID      = "wxid_kpj31bk8ma9x12"
# Per-group @mention names for the bot.
# If a chat_id is not listed here, BOT_AT_NAMES_DEFAULT is used.
BOT_AT_NAMES_DEFAULT = {"战地助手"}
BOT_AT_NAMES_MAP = {
    "45203634329@chatroom": {"ai吃鸡助手"},  # Pubg粤语-大湾区
}


def _parse_target_date(requirement):
    from datetime import datetime, timedelta
    now = datetime.now(CST)
    if any(k in requirement for k in ["昨", "昨日", "昨天"]):
        return (now - timedelta(days=1)).date()
    return now.date()


def _pubg_call(fn, *args, label="PUBG"):
    try:
        return fn(*args)
    except ValueError as e:
        return str(e)
    except Exception as e:
        log.error(f"{label} error: {e}")
        return f"查询{label}数据失败，请稍后重试"


def handle_pubg_stats(player_name, requirement=""):
    req = requirement
    client = PubgClient()

    if any(k in req for k in ["排位", "段位", "rank", "ranked"]):
        return _pubg_call(
            lambda: format_ranked_report(client.get_ranked_stats(player_name, shard=PUBG_SHARD)),
            label="排位"
        )
    if any(k in req for k in ["生涯", "lifetime", "总战绩"]):
        return _pubg_call(
            lambda: format_lifetime_report(client.get_lifetime_stats(player_name, shard=PUBG_SHARD)),
            label="生涯"
        )
    if any(k in req for k in ["赛季", "season", "本赛季"]):
        return _pubg_call(
            lambda: format_season_report(client.get_season_stats(player_name, shard=PUBG_SHARD)),
            label="赛季"
        )
    # default: date-based report
    target_date = _parse_target_date(req)
    return _pubg_call(
        lambda: format_stats_report(client.get_stats_for_date(player_name, target_date, PUBG_SHARD), player_name),
        label="战绩"
    )


def handle_pubg_evaluation(player_name: str) -> str:
    """Fetch today's + lifetime stats and ask AI to evaluate with tiered tone."""
    client = PubgClient()
    try:
        stats = client.get_stats_for_date(player_name, shard=PUBG_SHARD)
    except ValueError as e:
        return str(e)
    except Exception as e:
        log.error(f"evaluation fetch error: {e}")
        return "查不到数据，没法评价"
    if not stats:
        return f"{player_name} 今天根本没上线，评价个寂寞"

    # Lifetime boost check
    lifetime_boost_avg = 0.0
    try:
        lt = client.get_lifetime_stats(player_name, shard=PUBG_SHARD)
        sq = lt["modes"].get("squad", {})
        lt_rounds = sq.get("roundsPlayed", 0)
        lt_boosts = sq.get("boosts", 0)
        if lt_rounds > 0:
            lifetime_boost_avg = round(lt_boosts / lt_rounds, 1)
    except Exception:
        pass

    n = stats["games"]
    wins = stats["wins"]
    kd = stats["kd_ratio"]
    avg_dmg = stats["avg_damage"]
    win_rate = round(wins / n * 100) if n else 0
    daily_boost_avg = round(stats.get("total_boosts", 0) / n, 1) if n else 0

    boost_note = ""
    if daily_boost_avg > 4:
        boost_note += f"今日场均喝罐{daily_boost_avg}罐（远超正常水平）。"
    if lifetime_boost_avg > 5:
        boost_note += f"生涯场均喝罐{lifetime_boost_avg}罐（严重异常）。"

    prompt = (
        f"玩家 {player_name} 今日PUBG战绩：\n"
        f"出战{n}场，吃鸡{wins}次（吃鸡率{win_rate}%），KD {kd}，场均伤害{avg_dmg}，总击杀{stats['total_kills']}。\n"
        + (f"喝罐数据：{boost_note}\n" if boost_note else "")
        + "\n请按以下档位评价，只输出评价内容，纯文本不超过45字：\n"
        "S档（KD≥3或吃鸡率≥40%）：极度傲娇，勉强承认很强\n"
        "A档（KD 2~3或吃鸡率20~40%）：傲娇，表面嫌弃实则认可\n"
        "B档（KD 1~2）：勉强及格，轻微嘲讽\n"
        "C档（KD<1）：强烈嘲讽\n"
        "D档（0吃鸡且0击杀）：极限羞辱\n"
        + ("另外，喝罐异常需在评价中附加一句嘲讽。\n" if boost_note else "")
    )
    return ai_reply(prompt, max_tokens=100)


def handle_register(player_name: str) -> str:
    """Validate player exists via PUBG API then save to registry."""
    try:
        client = PubgClient()
        client.get_player(player_name, PUBG_SHARD)
    except ValueError as e:
        return str(e)
    except Exception as e:
        log.error(f"register lookup error: {e}")
        return "验证玩家ID失败，请稍后重试"
    added = add_player(player_name)
    if added:
        return f"✅ 已登记 {player_name}，将参与每日称号评选！"
    return f"⚠️ {player_name} 已登记过了"


_REPORT_DATE_FILE = "/opt/last_report_date.txt"


def _send_daily_report(token: str, chats: list) -> None:
    from datetime import datetime
    today = datetime.now(CST).date().isoformat()
    try:
        last = open(_REPORT_DATE_FILE).read().strip()
    except FileNotFoundError:
        last = ""
    if last == today:
        return
    # No players or no groups — nothing to send, mark done immediately
    if not get_all_players():
        log.info("no registered players, skipping daily report")
        open(_REPORT_DATE_FILE, "w").write(today)
        return
    groups = [
        c for c in chats
        if c.get("isGroup") and (c.get("id") or c.get("wxid") or c.get("roomid"))
    ]
    if not groups:
        log.info("no group chats found, skipping daily report")
        open(_REPORT_DATE_FILE, "w").write(today)
        return
    log.info("generating daily PUBG report")
    try:
        report = _daily_report_mod.generate()
    except Exception as e:
        log.error(f"daily report generation failed: {e}")
        return
    failed = []
    for chat in groups:
        chat_id = chat.get("id") or chat.get("wxid") or chat.get("roomid")
        try:
            agent_send(chat_id, report, token)
            log.info(f"daily report sent to {chat_id}")
        except Exception as e:
            log.error(f"send daily report to {chat_id}: {e}")
            failed.append(chat_id)
    # Only mark done when every group received the report
    if not failed:
        open(_REPORT_DATE_FILE, "w").write(today)
        log.info(f"daily report fully sent to {len(groups)} group(s), marked done")
    else:
        log.warning(f"daily report failed for {failed}, will retry next cycle")


def _check_leave_event(msg: dict):
    """Return leaver's name if this is a group-leave system message, else None."""
    text = msg.get("content", "")
    if "退出了群聊" not in text:
        return None
    m = re.match(r'^["“](.+?)["”]\s*退出了群聊', text.strip())
    if m:
        return m.group(1)
    return "某人"


_HELP_KEYWORDS = {
    "功能", "帮助", "help", "怎么用", "如何用", "用法",
    "指令", "命令", "使用说明", "介绍", "干什么", "能做什么",
    "有什么", "啥功能", "会什么",
}

_HELP_MSG = (
    "我能做的：\n"
    "查今日战报：发玩家ID（如：6umm）\n"
    "查昨日战报：6umm 昨日\n"
    "查本赛季/排位/生涯：6umm 赛季 / 6umm 排位 / 6umm 生涯\n"
    "登记ID参与每日称号：登记 6umm\n"
    "\n"
    "每天8点到9点之间自动发送昨日战绩称号榜"
)


def dispatch(query: str) -> str:
    """Route a user query to the correct handler.

    Handles: player registration, PUBG stats queries, help questions.
    Returns None for unrecognised input (caller skips sending).
    """
    q = query.strip()
    # Registration: 消息含"登记" + 任意位置的 PUBG ID
    if "登记" in q:
        m_reg = re.search(r"(?<![A-Za-z0-9_\-.])([A-Za-z0-9][A-Za-z0-9_\-.]{2,23})(?![A-Za-z0-9_\-.])", q)
        if m_reg:
            return handle_register(m_reg.group(1))
    # Help / usage questions
    if any(kw in q for kw in _HELP_KEYWORDS):
        return _HELP_MSG
    # Evaluation: 消息含"评价" + 玩家ID
    if "评价" in q:
        m_eval = re.search(r"(?<![A-Za-z0-9_\-.])([A-Za-z0-9][A-Za-z0-9_\-.]{2,23})(?![A-Za-z0-9_\-.])", q)
        if m_eval:
            return handle_pubg_evaluation(m_eval.group(1))
    # PUBG ID anywhere in message (pure-ASCII, 3-24 chars)
    m = re.search(r"(?<![A-Za-z0-9_\-.])([A-Za-z0-9][A-Za-z0-9_\-.]{2,23})(?![A-Za-z0-9_\-.])", q)
    if m:
        player_name = m.group(1)
        requirement = (q[:m.start()] + q[m.end():]).strip()
        return handle_pubg_stats(player_name, requirement)
    # Unrecognised — casual chat
    return ai_reply(query, max_tokens=60)



_executor = ThreadPoolExecutor(max_workers=10)


def _handle_message(cid, query, sender, token):
    log.info(f"[MSG] {cid} {sender}: {query[:60]}")
    try:
        reply = dispatch(query)
        if not reply:
            log.info(f"[SKIP] no handler for: {query[:60]}")
            return
        agent_send(cid, reply, token)
    except Exception as e:
        log.error(f"dispatch error: {e}")


def main():
    token = get_token()
    last_seen = {}

    log.info("Bot started, initializing...")
    chats = agent_get("/api/chats", token)
    for chat in chats:
        cid = chat["id"]
        try:
            msgs = agent_get("/api/messages/" + requests.utils.quote(cid, safe=""), token)
            last_seen[cid] = msgs[0]["localId"] if msgs else 0
        except Exception:
            last_seen[cid] = 0
    log.info(f"Ready, monitoring {len(last_seen)} chats")

    while True:
        try:
            chats = agent_get("/api/chats", token)

            # Daily report at 08:00 CST (only fires during the 8 o'clock hour)
            from datetime import datetime as _dt
            if _dt.now(CST).hour == 8:
                _send_daily_report(token, chats)

            for chat in chats:
                cid = chat["id"]
                is_group = chat.get("isGroup", False)
                if not is_group:
                    continue
                try:
                    msgs = agent_get("/api/messages/" + requests.utils.quote(cid, safe=""), token)
                except Exception:
                    continue
                if not msgs:
                    continue

                last_id = last_seen.get(cid, 0)
                new_msgs = [m for m in msgs if m["localId"] > last_id and not m.get("isSelf")]
                new_msgs.sort(key=lambda m: m["localId"])

                for msg in new_msgs:
                    content = msg.get("content", "").strip()
                    sender = msg.get("senderName", "?")

                    # Detect group-leave system messages
                    if is_group:
                        leaver = _check_leave_event(msg)
                        if leaver:
                            log.info(f"[LEAVE] {cid}: {leaver}")
                            agent_send(cid, f"👋 {leaver} 退出了群聊，后会有期！", token)
                            continue

                    if is_group:
                        query = extract_group_query(content, cid)
                        if not query:
                            continue
                    else:
                        query = content

                    if not query:
                        continue

                    _executor.submit(_handle_message, cid, query, sender, token)

                if new_msgs:
                    last_seen[cid] = new_msgs[-1]["localId"]

        except Exception as e:
            log.error(f"Poll error: {e}")

        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
