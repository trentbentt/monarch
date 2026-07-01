"""Web Push (VAPID): key management, subscription store, sender, event bridge.

The browser never sees a bearer key; the only public material is the VAPID
application server key. Push respects the overnight-window quieting doctrine
(§9.5.3) — interrupt classes bypass it, everything else is suppressed in-window.
"""
