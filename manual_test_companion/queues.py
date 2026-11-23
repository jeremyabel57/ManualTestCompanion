from __future__ import annotations

from collections import deque
from typing import Deque as DequeType, Generic, Iterator, TypeVar


T = TypeVar("T")


class Deque(Generic[T]):
    """Double-ended queue used by the legacy script and instrument queues."""

    def __init__(self) -> None:
        self._items: DequeType[T] = deque()

    def push(self, item: T) -> None:
        self._items.append(item)

    def push_front(self, item: T) -> None:
        self._items.appendleft(item)

    def pop(self) -> T:
        return self._items.popleft()

    def pop_back(self) -> T:
        return self._items.pop()

    def peek(self) -> T:
        return self._items[0]

    def peek_back(self) -> T:
        return self._items[-1]

    def size(self) -> int:
        return len(self._items)

    def is_empty(self) -> bool:
        return not self._items

    def to_list(self) -> list[T]:
        return list(self._items)

    def copy(self, reverse: bool = False) -> Deque[T]:
        result: Deque[T] = Deque()
        result._items.extend(reversed(self._items) if reverse else self._items)
        return result

    def drain_into(self, target: Deque[T], *, front: bool = False) -> None:
        while self._items:
            item = self.pop()
            if front:
                target.push_front(item)
            else:
                target.push(item)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[T]:
        return iter(self._items)


class ProgramQueue(Generic[T]):
    """Instruction block with the parked, active, and completed PC states."""

    def __init__(
        self,
        command: str = "",
        condition: str = "",
        condition_result: bool = False,
    ) -> None:
        self._items: dict[int, T] = {}
        self._head = 1
        self._tail = 0
        self._pc = 0
        self.command = command
        self.condition = condition
        self.condition_result = condition_result
        self.skip = False

    def push(self, item: T) -> None:
        self._tail += 1
        self._items[self._tail] = item

    def pop(self) -> T:
        if self.is_empty():
            raise IndexError("pop from empty program queue")
        item = self._items.pop(self._head)
        self._head += 1
        return item

    def is_empty(self) -> bool:
        return self._head > self._tail

    @property
    def pc(self) -> int:
        if self._pc < self._head:
            return self._head - 1
        if self._pc > self._tail:
            return self._tail + 1
        if self._pc not in self._items:
            raise RuntimeError(f"program queue has no instruction at PC {self._pc}")
        return self._pc

    @property
    def is_parked(self) -> bool:
        return self._pc < self._head

    @property
    def is_start(self) -> bool:
        return self._pc == self._head

    @property
    def is_done(self) -> bool:
        return self._pc > self._tail

    def release(self) -> None:
        self._pc = self._head

    def restart(self) -> None:
        self._pc = self._head

    def set_done(self) -> None:
        self._pc = self._tail + 1

    def advance(self) -> bool:
        if self._pc <= self._tail:
            self._pc += 1
        if self._pc < self._head:
            self._pc = self._head
        return self._pc <= self._tail

    def next_item(self) -> T:
        if self.is_parked:
            raise RuntimeError("program queue is parked")
        if self.is_done:
            raise StopIteration
        if self._pc not in self._items:
            raise RuntimeError(f"program queue has no instruction at PC {self._pc}")
        item = self._items[self._pc]
        self._pc += 1
        return item

    def __len__(self) -> int:
        return max(0, self._tail - self._head + 1)
