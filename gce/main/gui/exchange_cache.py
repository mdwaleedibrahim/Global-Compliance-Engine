"""Read the Exchange Connectivity binary order journal for the OMS view."""

import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


RECORD = struct.Struct("@II32s24sqqdc?xxxxxx")


def _text(value: bytes) -> str:
    return value.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def read_exchange_orders(path: Path) -> List[Dict[str, Any]]:
    """Return gateway journal records in the same shape as the GCE OMS API."""
    if not path.exists():
        return []
    orders: List[Dict[str, Any]] = []
    modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    with path.open("rb") as journal:
        while True:
            payload = journal.read(RECORD.size)
            if not payload or len(payload) != RECORD.size:
                break
            client_id, _, order_id, symbol, quantity, leaves, price, status, odd_lot = RECORD.unpack(payload)
            status_code = status.decode(errors="replace")
            orders.append({
                "order_id": _text(order_id) or str(client_id), "ric": _text(symbol), "symbol": _text(symbol),
                "side": "", "quantity": quantity, "price": price,
                "status": {"0": "Live", "1": "Partial Fill", "2": "Fill", "4": "Cancelled"}.get(status_code, "Live"),
                "trader": "EXCHANGE", "account": "", "client": str(client_id), "currency": "HKD",
                "exchange": "XHKG", "timestamp": modified, "filled": max(quantity - leaves, 0),
                "open_qty": leaves, "source": "exchange-connectivity", "odd_lot": odd_lot,
            })
    return orders