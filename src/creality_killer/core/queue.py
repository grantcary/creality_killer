"""Local print queue. Nothing here starts a print - starting is always an explicit user action."""
from __future__ import annotations


class PrintQueue:
    def __init__(self) -> None:
        self._items: list[str] = []

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    @property
    def items(self) -> list[str]:
        return list(self._items)

    @property
    def head(self) -> str | None:
        return self._items[0] if self._items else None

    def add(self, path: str) -> None:
        """Duplicates are allowed - printing the same part twice is normal."""
        self._items.append(path)

    def remove_at(self, index: int) -> None:
        del self._items[index]

    def move(self, src: int, dst: int) -> None:
        self._items.insert(dst, self._items.pop(src))

    def job_started(self, path: str) -> bool:
        """Printer began `path`; drop it from the queue if it was the head."""
        if self.head == path:
            self._items.pop(0)
            return True
        return False
