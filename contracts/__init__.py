"""monarch shared contracts.

Single source of truth for the data shapes that cross repo boundaries inside
the monarch stack. Before consolidation these seams were held together by
convention — each side hand-coded its own copy of the field names — and they
drifted silently (see ledger.py for the bug that motivated this package).

Importing from here makes the seams enforceable; tests/test_conformance.py
fails loudly if any producer or consumer drifts from the contract.
"""
