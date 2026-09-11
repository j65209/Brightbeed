"""Classify missing read-only order details instead of silently losing rows."""
import json
from urllib.error import HTTPError


def _rows(response, expected):
    rows = response.get("data") if isinstance(response, dict) else None
    if not isinstance(rows, list):
        raise ValueError("incomplete_order_details")
    identities = []
    for row in rows:
        order = row.get("productOrder") if isinstance(row, dict) else None
        identity = order.get("productOrderId") if isinstance(order, dict) else None
        if identity in (None, "", False):
            raise ValueError("mismatched_order_details")
        identities.append(str(identity))
    if len(identities) != len(set(identities)) or not set(identities) <= expected:
        raise ValueError("mismatched_order_details")
    return rows, set(identities)


def fetch_details(query, ids):
    """Only HTTP 400 / code 100001 from an individual lookup is exempted.

    Naver's official explanation: https://github.com/commerce-api-naver/commerce-api/discussions/3572
    Such rows are unavailable through this API; totals must carry coverage.
    Other omissions/errors fail publication. Never log order/customer identifiers.
    """
    if len({str(i) for i in ids}) != len(ids):
        raise ValueError("duplicate_order_request")
    out, missing = [], []
    for start in range(0, len(ids), 100):
        batch = ids[start:start + 100]
        rows, returned = _rows(query(batch), set(map(str, batch)))
        out.extend(rows)
        missing.extend(identity for identity in batch if str(identity) not in returned)
    if len(missing) > 10:
        raise ValueError("too_many_missing_orders")
    unavailable = 0
    for identity in missing:
        try:
            response = query([identity])
        except HTTPError as error:
            # Read at most a small error body, and retain only its documented code.
            try:
                body = json.loads(error.read(4096))
            except (ValueError, OSError):
                body = {}
            if error.code != 400 or not isinstance(body, dict) or str(body.get("code")) != "100001":
                raise ValueError("order_lookup_failed") from None
            unavailable += 1
            continue
        rows, returned = _rows(response, {str(identity)})
        if returned != {str(identity)}:
            raise ValueError("unconfirmed_missing_order")
        out.extend(rows)
    coverage = {"requestedOrders": len(ids), "returnedOrders": len(out),
                "unavailableOrders": unavailable, "complete": unavailable == 0}
    if unavailable:
        coverage["unavailableReason"] = "naver_api_100001"
    return out, coverage
