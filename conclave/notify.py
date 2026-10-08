from __future__ import annotations

import json
import logging
import urllib.request

log = logging.getLogger(__name__)


def slack(webhook: str | None, text: str) -> bool:
    if not webhook:
        return False
    try:
        req = urllib.request.Request(webhook, data=json.dumps({"text": text[:39000]}).encode(),
                                     headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception as e:  # noqa: BLE001
        log.warning("slack post failed: %s", e)
        return False
