#!/usr/bin/env python3
"""Persistent registry of registered PUBG player IDs, per group."""
import json
import os

_REGISTRY_DIR = "/opt"
_GLOBAL_FILE  = "/opt/registered_players.json"


def _file(chat_id: str | None) -> str:
    if chat_id:
        safe = chat_id.replace("/", "_").replace("\\", "_")
        return os.path.join(_REGISTRY_DIR, f"players_{safe}.json")
    return _GLOBAL_FILE


def _load(chat_id: str | None = None) -> list:
    path = _file(chat_id)
    if not os.path.exists(path):
        return []
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return []


def _save(players: list, chat_id: str | None = None) -> None:
    json.dump(players, open(_file(chat_id), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def add_player(player_name: str, chat_id: str | None = None) -> bool:
    """Add player. Returns True if added, False if already registered."""
    players = _load(chat_id)
    if player_name in players:
        return False
    players.append(player_name)
    _save(players, chat_id)
    return True


def remove_player(player_name: str, chat_id: str | None = None) -> bool:
    """Remove player. Returns True if removed, False if not found."""
    players = _load(chat_id)
    if player_name not in players:
        return False
    players.remove(player_name)
    _save(players, chat_id)
    return True


def get_all_players(chat_id: str | None = None) -> list:
    return _load(chat_id)
