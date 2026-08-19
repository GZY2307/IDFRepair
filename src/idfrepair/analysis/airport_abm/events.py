"""Stable priority queue primitives for the discrete-event simulator."""

from __future__ import annotations

from dataclasses import dataclass, field
import heapq
from typing import Any, Iterator


@dataclass(order=True, frozen=True, slots=True)
class Event:
    time: float
    sequence: int
    kind: str = field(compare=False)
    agent_id: str = field(compare=False)
    payload: dict[str, Any] = field(compare=False)


class EventQueue:
    def __init__(self) -> None:
        self._heap: list[Event] = []
        self._sequence = 0

    def push(
        self,
        time: float,
        kind: str,
        agent_id: str,
        payload: dict[str, Any],
    ) -> None:
        if time < 0:
            raise ValueError("event time must not be negative")
        event = Event(float(time), self._sequence, kind, agent_id, payload)
        self._sequence += 1
        heapq.heappush(self._heap, event)

    def pop(self) -> Event:
        return heapq.heappop(self._heap)

    def __bool__(self) -> bool:
        return bool(self._heap)

    def __iter__(self) -> Iterator[Event]:
        while self._heap:
            yield self.pop()
