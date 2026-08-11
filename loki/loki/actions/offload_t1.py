"""
Action: offload_t1_reasoning — Substrate Pressure Cascade T1 self-offload (§10.3).

Under sustained VRAM pressure inside the overnight weekday window, Loki
offloads a portion of T1's layers GPU → CPU/DDR5 (reduced -ngl) to free VRAM for
a T2/T6 burst. Fires as a **non-blocking Tier-3** action: the gate surfaces a
120-second veto window ("offloading T1 to RAM in 120s unless you veto") and
default-proceeds at timeout (§9.5.1 / §10.3). Hard Constraint #1 is preserved —
the Loki daemon never stops; only the T1 llama-server window is relaunched at
a lower -ngl. Reverse: restore_t1_reasoning.

Shells to ~/bin/t1-offload, which owns the launch flags + `control`-session
topology — same delegation pattern as restart_dataplane_tier → ~/bin/t{3,4,5}-up.

Doctrine: master_summary §10.3 (Substrate Pressure Cascade), §9.5.1 (non-blocking
Tier 3), §9.5.3 (overnight window gating — applied by the rule, not here).
"""

from __future__ import annotations

import logging
import os
import subprocess

from ..schema import ActionTier, MONARCH_TIERS
from ..listeners.process import _t1_offload_state
from .base import Action, _http_ok

logger = logging.getLogger(__name__)

_SCRIPT = os.path.expanduser("~/bin/t1-offload")
# ~/bin/t1-offload waits up to its own HEALTH_TIMEOUT (180s) for the relaunched
# T1 to bind /health; give the subprocess a margin beyond that.
_OFFLOAD_TIMEOUT_SEC = 240

# Reverse script, named by `reversible = True` and run by rollback(). Same script
# restore_t1_reasoning shells to — one mechanism, two callers.
_REVERSE_SCRIPT = os.path.expanduser("~/bin/t1-restore")
_REVERSE_TIMEOUT_SEC = 240


class OffloadT1Reasoning(Action):
    action_id   = "offload_t1_reasoning"
    action_class = "service-lifecycle"
    description = "Offload a portion of T1 reasoning GPU→CPU/DDR5 (reduced -ngl) to free VRAM for a burst (§10.3)"
    default_tier = ActionTier.TIER_3     # surface-and-ask (non-blocking, see veto window)
    target_tier  = ActionTier.TIER_3     # never auto-promotes — a disruptive move always wants the veto
    reversible   = True                  # ~/bin/t1-restore
    costs_money  = False
    vram_mb      = 0                     # FREES VRAM (does not consume)

    # §9.5.1 / §10.3: non-blocking Tier 3 — the gate surfaces a PendingAsk with a
    # deadline this many seconds out, then default-proceeds unless the operator
    # vetoes. None on an action = classic blocking Tier 3 (wait for approval).
    nonblocking_veto_sec = 120

    def matches(self, params: dict) -> bool:
        return True

    def execute(self, params: dict) -> str:
        """Shell out to ~/bin/t1-offload (idempotent). "ok" = relaunched cleanly
        (vram.py confirms the freed VRAM on its next poll), else "failed"."""
        if not (os.path.isfile(_SCRIPT) and os.access(_SCRIPT, os.X_OK)):
            logger.error("[action:offload_t1] launch script missing/not-executable: %s", _SCRIPT)
            return "failed"
        try:
            logger.info("[action:offload_t1] → %s", _SCRIPT)
            proc = subprocess.run(
                [_SCRIPT], capture_output=True, text=True, timeout=_OFFLOAD_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            logger.error("[action:offload_t1] timed out after %ds", _OFFLOAD_TIMEOUT_SEC)
            return "failed"
        except Exception as exc:  # never raise — the gate records the outcome
            logger.error("[action:offload_t1] raised %s: %s", type(exc).__name__, exc)
            return "failed"

        if proc.returncode == 0:
            logger.info("[action:offload_t1] T1 offloaded ok")
            return "ok"

        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        logger.error("[action:offload_t1] failed (rc=%d): %s", proc.returncode, " | ".join(tail))
        return "failed"

    def verify(self, params: dict) -> str:
        """T1 must answer /health AND actually be offloaded.

        Liveness alone is NOT proof this action did its job: T1 is RELAUNCHED at
        a reduced -ngl, never stopped, so /health answers before and after — and
        answers just as happily if the script did nothing at all. Verifying only
        the port let a no-op score execute=ok + verify=ok, which the ledger
        records as "ok" and the autonomy ladder counts as a clean run toward
        promotion (agentbench #5, 2026-07-16).

        The marker written by ~/bin/t1-offload is the source of truth for
        residency — the same one process.py reads to populate
        tier.runtime.offloaded — so verify confirms the CLAIMED EFFECT (layers
        moved GPU→CPU, VRAM freed), not merely that the tier is alive.
        """
        port = MONARCH_TIERS["t1"].port
        if not _http_ok(f"http://127.0.0.1:{port}/health", timeout=10.0):
            logger.error("[action:offload_t1] verify: T1 not answering /health")
            return "failed"
        offloaded, ngl = _t1_offload_state()
        if not offloaded:
            logger.error("[action:offload_t1] verify: T1 answers but is NOT "
                         "offloaded — the relaunch did not take effect")
            return "failed"
        logger.info("[action:offload_t1] verify: T1 offloaded (ngl=%s)", ngl)
        return "ok"

    def rollback(self, params: dict) -> str:
        """Undo the offload by running the reverse script this action's
        `reversible = True` already names.

        The gate calls rollback() in exactly one situation (authority.py):
        execute() said "ok" but verify() said "failed". For this action that
        means T1 is offloaded-but-broken or off its port entirely — the
        reasoning brain, with NO rule that autonomously recovers it. Returning
        "unsupported" here (the previous behaviour) meant the gate asked for the
        undo it had been promised and got nothing (agentbench #5, 2026-07-16).
        """
        if not (os.path.isfile(_REVERSE_SCRIPT) and os.access(_REVERSE_SCRIPT, os.X_OK)):
            logger.error("[action:offload_t1] rollback: reverse script "
                         "missing/not-executable: %s", _REVERSE_SCRIPT)
            return "failed"
        try:
            logger.warning("[action:offload_t1] rollback → %s", _REVERSE_SCRIPT)
            proc = subprocess.run(
                [_REVERSE_SCRIPT], capture_output=True, text=True,
                timeout=_REVERSE_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            logger.error("[action:offload_t1] rollback timed out after %ds",
                         _REVERSE_TIMEOUT_SEC)
            return "failed"
        except Exception as exc:  # never raise — the gate records the outcome
            logger.error("[action:offload_t1] rollback raised %s: %s",
                         type(exc).__name__, exc)
            return "failed"
        if proc.returncode == 0:
            logger.info("[action:offload_t1] rollback ok — T1 restored")
            return "ok"
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        logger.error("[action:offload_t1] rollback FAILED (rc=%d): %s — T1 may "
                     "be degraded; operator attention needed",
                     proc.returncode, " | ".join(tail))
        return "failed"
