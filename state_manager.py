"""
Lightweight in-memory FSM state manager.
Replaces aiogram's FSMContext for the MAX bot.
Thread-safe enough for a single-threaded asyncio process.
"""
from typing import Any, Dict, Optional


class StateManager:
    def __init__(self):
        self._states: Dict[int, str] = {}
        self._data: Dict[int, Dict[str, Any]] = {}

    # ── State ──────────────────────────────────────────────────────────────────

    def get(self, user_id: int) -> Optional[str]:
        return self._states.get(user_id)

    def set(self, user_id: int, state: str):
        self._states[user_id] = state
        if user_id not in self._data:
            self._data[user_id] = {}

    def clear(self, user_id: int):
        self._states.pop(user_id, None)
        self._data.pop(user_id, None)

    # ── Data ───────────────────────────────────────────────────────────────────

    def get_data(self, user_id: int) -> Dict[str, Any]:
        return dict(self._data.get(user_id, {}))

    def update_data(self, user_id: int, **kwargs):
        if user_id not in self._data:
            self._data[user_id] = {}
        self._data[user_id].update(kwargs)

    def set_data(self, user_id: int, data: Dict[str, Any]):
        self._data[user_id] = data


# Singleton — imported everywhere
state_mgr = StateManager()
