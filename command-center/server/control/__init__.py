"""Phase 3: gated control surface.

The only part of the dashboard that mutates monarch. Every action is:
  - a member of a CLOSED enum (no arbitrary commands / URLs / shell),
  - behind the operator control token,
  - requires explicit per-request confirmation,
  - appended to an audit log,
  - dry-run capable (global or per-request) for safe verification.
"""
