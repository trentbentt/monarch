"""
BaseListener — abstract polling listener.

Each listener runs as a daemon thread. Failures are logged and the loop
continues — a broken listener never takes down other listeners or the daemon.
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseListener(ABC):
    """
    Subclass this and implement `poll()`.
    Call `start()` to launch as a daemon thread.
    """

    name: str = "base"
    interval_sec: float = 30.0

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name=f"listener-{self.name}",
            daemon=True,
        )
        self._thread.start()
        logger.info("[%s] started (interval=%.0fs)", self.name, self.interval_sec)

    def stop(self) -> None:
        self._stop_event.set()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @abstractmethod
    def poll(self) -> None:
        """Perform one observation cycle. Must not raise — catch internally."""
        ...

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.poll()
            except Exception as exc:
                # Isolation: log the failure, keep running
                logger.error("[%s] poll() raised %s: %s",
                             self.name, type(exc).__name__, exc, exc_info=True)
            self._stop_event.wait(timeout=self.interval_sec)
