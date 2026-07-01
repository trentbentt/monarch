"""Deliver Web Push messages via pywebpush; prune dead subscriptions.

Network delivery runs in a thread (pywebpush is sync). Dead endpoints (404/410)
are removed from the store automatically.
"""
from __future__ import annotations

import json
from typing import Tuple

import config
from push import subscriptions, vapid


def _claims() -> dict:
    return {"sub": config.PUSH_CONTACT}


def send_one(subscription: dict, payload: dict) -> Tuple[bool, int]:
    """Send to a single subscription. Returns (ok, status_code). On 404/410 the
    subscription is removed. Import is local so tests can run without pywebpush."""
    from pywebpush import webpush, WebPushException

    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=vapid.private_pem(),
            vapid_claims=_claims(),
            timeout=10,
        )
        return True, 201
    except WebPushException as e:
        status = getattr(getattr(e, "response", None), "status_code", 0) or 0
        if status in (404, 410):
            subscriptions.remove(subscription.get("endpoint", ""))
        return False, status
    except Exception:
        # Malformed subscription (bad keys), encryption/network error, etc.
        # A single bad subscription must never fault the whole send.
        return False, 0


def send_all(payload: dict) -> dict:
    sent, failed, pruned = 0, 0, 0
    for sub in subscriptions.all():
        ok, status = send_one(sub, payload)
        if ok:
            sent += 1
        else:
            failed += 1
            if status in (404, 410):
                pruned += 1
    return {"sent": sent, "failed": failed, "pruned": pruned}
