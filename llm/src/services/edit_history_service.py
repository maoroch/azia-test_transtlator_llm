from typing import List, Dict, Any, Optional
from loguru import logger
import copy

class EditHistoryService:
    """
    Сервис для управления историей изменений (undo/redo) состояния блоков.
    """
    def __init__(self, max_states: int = 50):
        self.history: List[List[Dict[str, Any]]] = []
        self.future: List[List[Dict[str, Any]]] = []
        self.max_states = max_states
        self.last_action_desc = None

    def add_state(self, blocks: List[Dict[str, Any]], action_desc: str = "", metadata: Optional[Dict] = None):
        """Сохранить текущее состояние блоков."""
        state_copy = copy.deepcopy(blocks)
        self.history.append(state_copy)
        if len(self.history) > self.max_states:
            self.history.pop(0)
        self.future.clear()
        self.last_action_desc = action_desc
        logger.debug(f"State saved (action: {action_desc}). Total {len(self.history)} states.")

    def undo(self) -> Optional[List[Dict[str, Any]]]:
        """Отменить последнее действие."""
        if len(self.history) <= 1:
            logger.warning("Nothing to undo")
            return None
        current = self.history.pop()
        self.future.append(current)
        prev_state = self.history[-1]
        logger.info(f"Undo performed. Now at state {len(self.history)}")
        return copy.deepcopy(prev_state)

    def redo(self) -> Optional[List[Dict[str, Any]]]:
        """Повторить отменённое действие."""
        if not self.future:
            logger.warning("Nothing to redo")
            return None
        next_state = self.future.pop()
        self.history.append(next_state)
        logger.info(f"Redo performed. Now at state {len(self.history)}")
        return copy.deepcopy(next_state)

    def get_history_info(self) -> Dict[str, Any]:
        return {
            "total_states": len(self.history),
            "can_undo": len(self.history) > 1,
            "can_redo": len(self.future) > 0,
            "last_action": self.last_action_desc
        }

    def clear(self):
        self.history.clear()
        self.future.clear()
        logger.info("History cleared")