"""
Loki Daemon v0.2

Starts the StateStore writer thread, then all listeners.
Writes state.json every 10s.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from loki.listeners import (
    CronListener,
    HardwareListener,
    MemoryListener,
    ProcessListener,
    QuotaListener,
    TierHealthListener,
    VRAMListener,
)
from loki.engine import DecisionEngine
from loki.state import STATE_PATH, StateStore

LOG_PATH = Path(os.environ.get(
    "LOKI_LOG_PATH",
    Path.home() / ".local/state/loki/daemon.log"
))
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("loki.daemon")

PERSIST_INTERVAL_SEC = 10


def main() -> None:
    logger.info("══ Loki daemon v0.2 starting ══")
    logger.info("State file: %s", STATE_PATH)
    logger.info("Log file:   %s", LOG_PATH)

    store = StateStore.get()
    store.start()

    listeners = [
        VRAMListener(),
        TierHealthListener(),
        ProcessListener(),
        QuotaListener(),
        CronListener(),
        MemoryListener(),
        HardwareListener(),
    ]
    for listener in listeners:
        listener.start()
    logger.info("Listeners started: %s",
                ", ".join(f"{l.name}({l.interval_sec:.0f}s)" for l in listeners))

    # Decision engine — pure consumer of listener signals (§12.6). Separate
    # thread on its own tick; writes only the `decisions` domain.
    engine = DecisionEngine()
    engine.start()
    logger.info("Decision engine started (%.0fs tick)", engine.interval_sec)

    _shutdown = [False]

    def _handle_signal(sig: int, _frame: object) -> None:
        logger.info("Received signal %d — shutting down", sig)
        _shutdown[0] = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    last_persist = 0.0
    last_health_log = 0.0

    while not _shutdown[0]:
        now = time.monotonic()

        if now - last_persist >= PERSIST_INTERVAL_SEC:
            try:
                store.save_to_disk()
            except Exception as exc:
                logger.error("Failed to persist state: %s", exc, exc_info=True)
            last_persist = now

        if now - last_health_log >= 60.0:
            for listener in listeners:
                if not listener.is_alive():
                    logger.error("Listener %s thread DEAD — should not happen",
                                 listener.name)
            last_health_log = now

        time.sleep(1)

    logger.info("Stopping listeners…")
    for listener in listeners:
        listener.stop()

    logger.info("Stopping decision engine…")
    engine.stop()       # flushes the authority ledger

    time.sleep(1)
    try:
        store.save_to_disk()
        logger.info("Final state written")
    except Exception as exc:
        logger.error("Final state write failed: %s", exc)

    store.stop()
    logger.info("══ Loki daemon stopped ══")


if __name__ == "__main__":
    main()
