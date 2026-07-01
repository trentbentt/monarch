"""
Loki Supervisor — a read-and-propose conversational layer ABOVE the deterministic
daemon. It reads live state + ledger + doctrine, answers the operator in natural
language, and can submit proposals into the daemon's authority gate. It holds no
authority of its own: every action it proposes is classified, cooldown-deduped,
and operator-gated identically to a deterministic rule's proposal.

Safety boundary (enforced in code, not just prose):
  • context.py reads state.json / authority.json / doctrine READ-ONLY.
  • proposals.py is the only write path and writes *requests*, validated against
    the ACTIONS registry so a hallucinated action can never be enqueued.
  • the engine drains the queue behind a DEFAULT-OFF flag, so wiring the layer in
    changes nothing until the operator explicitly enables it.

Doctrine: master_summary §9.5 (authority) / §12.6 (engine flow); the supervisor is
an additional proposal source, never an additional authority.
"""

from .proposals import SupervisorProposalQueue, SUPERVISOR_SOURCE, QUEUE_PATH
from .context import build_context, registered_actions
from .client import SupervisorClient
from .agent import SupervisorAgent

__all__ = [
    "SupervisorProposalQueue",
    "SUPERVISOR_SOURCE",
    "QUEUE_PATH",
    "build_context",
    "registered_actions",
    "SupervisorClient",
    "SupervisorAgent",
]
