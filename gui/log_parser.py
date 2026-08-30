"""GCE Log Parser — Extracts RMS control stats and performance timing from GCE.log.

Parses log lines like:
  [PASS] MaxOrderPrice: Control passed | LMT=100.0, ORD=50.0 {price_control.py:19 2800 nano seconds}
  [rule=8] [PASS] QtyControl: Control passed | LMT=1000, ORD=500 {test_parallel_logging.py:69 2.75 μs}
  [rule=8] [FAIL] PriceControl: Price Exceeds Limit | LMT=100.0, ORD=200.0 {test_parallel_logging.py:75 3.78 μs}
  LMT_CHECK_OVER in 270.98 ms
  LMT_CHECK_OVER in 155.93 μs
  LMT_CHECK_OVER in 0.60ms
"""

import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from collections import defaultdict


def parse_duration_to_ms(val_str: str) -> float:
    """Parse any duration string (e.g. '242.43 ms', '155.93 μs', '2800 ns', '1.25 s', '0.60ms') to milliseconds."""
    if not val_str:
        return 0.0
    s = str(val_str).strip().replace('nano seconds', 'ns').replace('nanoseconds', 'ns').replace('micro seconds', 'μs').replace('microseconds', 'μs')
    m = re.search(r'([\d.]+)\s*([a-zA-Zμµ]+)', s)
    if not m:
        try:
            return float(s)
        except ValueError:
            return 0.0
    num = float(m.group(1))
    unit = m.group(2).lower()
    if unit in ('ns', 'nanos'):
        return num / 1_000_000.0
    elif unit in ('μs', 'µs', 'us', 'micros'):
        return num / 1000.0
    elif unit in ('ms', 'millis'):
        return num
    elif unit in ('s', 'sec', 'secs', 'second', 'seconds'):
        return num * 1000.0
    elif unit in ('m', 'min', 'mins', 'minute', 'minutes'):
        return num * 60_000.0
    return num


def parse_duration_to_ns(val_str: str) -> int:
    """Parse any duration string to integer nanoseconds."""
    return int(round(parse_duration_to_ms(val_str) * 1_000_000.0))


# Regex patterns for log parsing
CONTROL_RESULT_RE = re.compile(
    r'(?:\[rule=(?P<rule>\w+)\]\s+)?'
    r'\[(?P<status>PASS|FAIL)\]\s+'
    r'(?P<control>\S+?):\s+'
    r'(?P<message>[^|]+?)\s*\|\s*'
    r'LMT=(?P<limit>[^,]+),\s*ORD=(?P<order_val>[^ \t\r\n{}]+)'
    r'(?:\s*\{(?P<caller>[^}]+)\})?'
)

TIMING_SUFFIX_RE = re.compile(
    r'(?P<file>\S+?:\d+)?\s*(?P<duration>[\d.]+\s*(?:nano\s+seconds|nanoseconds|ns|μs|µs|us|ms|s))?'
)

LMT_CHECK_OVER_RE = re.compile(
    r'LMT_CHECK_OVER\s+in\s+(?P<duration>[\d.]+\s*(?:nano\s+seconds|nanoseconds|ns|μs|µs|us|ms|s)?)'
)

LMT_CHECK_START_RE = re.compile(r'LMT_CHECK_START')
LMT_CHECK_NEW_RE = re.compile(r'LMT_CHECK_NEW')
LMT_CHECK_AMEND_RE = re.compile(r'LMT_CHECK_AMEND')

TIMESTAMP_RE = re.compile(
    r'^(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[.,]\d+)'
)


class LogParser:
    """Parses GCE.log to extract RMS control stats and performance data."""

    def __init__(self, log_path: str = "logs/GCE.log"):
        self.log_path = Path(log_path)

    def _read_lines(self) -> List[str]:
        """Read log file lines, returning empty list if file doesn't exist."""
        if not self.log_path.exists():
            return []
        try:
            with open(self.log_path, 'r', encoding='utf-8', errors='replace') as f:
                return f.readlines()
        except Exception:
            return []

    def get_rms_summary(self) -> Dict[str, Any]:
        """
        Parse log and aggregate per-control PASS/FAIL counts.

        Returns:
            {
                "controls": {
                    "MaxOrderPrice": {"pass": 80, "fail": 20, "total": 100, "pass_rate": 80.0},
                    ...
                },
                "total_checks": 500,
                "total_orders": 100,
                "orders": [...]  # list of individual check results
            }
        """
        lines = self._read_lines()
        controls: Dict[str, Dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0})
        orders: List[Dict[str, Any]] = []
        total_orders = 0

        for line in lines:
            if LMT_CHECK_START_RE.search(line):
                total_orders += 1

            m = CONTROL_RESULT_RE.search(line)
            if not m:
                continue

            status = m.group('status')
            control = m.group('control')
            message = m.group('message')
            limit_val = m.group('limit')
            order_val = m.group('order_val')
            caller_info = m.group('caller') or ""

            # Extract timestamp
            ts_m = TIMESTAMP_RE.match(line)
            timestamp = ts_m.group('ts') if ts_m else ""

            # Extract timing and file from caller info
            elapsed_ns = 0
            source_file = ""
            if caller_info:
                tm = TIMING_SUFFIX_RE.search(caller_info)
                if tm:
                    source_file = tm.group('file') or ""
                    dur_str = tm.group('duration') or ""
                    if dur_str:
                        elapsed_ns = parse_duration_to_ns(dur_str)

            if status == "PASS":
                controls[control]["pass"] += 1
            else:
                controls[control]["fail"] += 1

            orders.append({
                "timestamp": timestamp,
                "control": control,
                "status": status,
                "message": message.strip(),
                "limit": limit_val,
                "order_value": order_val,
                "source": source_file,
                "elapsed_ns": elapsed_ns,
            })

        # Build summary
        summary = {}
        total_checks = 0
        for ctrl_name, counts in controls.items():
            total = counts["pass"] + counts["fail"]
            total_checks += total
            summary[ctrl_name] = {
                "pass": counts["pass"],
                "fail": counts["fail"],
                "total": total,
                "pass_rate": round((counts["pass"] / total * 100), 2) if total > 0 else 0.0,
            }

        return {
            "controls": summary,
            "total_checks": total_checks,
            "total_orders": total_orders,
            "orders": orders,
        }

    def get_orders_for_control(self, control_name: str, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get individual order check results for a specific control.

        Args:
            control_name: e.g. "MaxOrderPrice"
            status_filter: "PASS" or "FAIL" or None for all

        Returns:
            List of order check dicts
        """
        summary = self.get_rms_summary()
        results = [o for o in summary["orders"] if o["control"] == control_name]
        if status_filter:
            results = [o for o in results if o["status"] == status_filter.upper()]
        return results

    def get_performance_data(self) -> Dict[str, Any]:
        """
        Parse log for performance timing data.

        Returns:
            {
                "order_times_ms": [0.60, 0.45, ...],  # total time per order validation
                "control_timings": [
                    {"order_index": 0, "control": "MaxOrderPrice", "elapsed_ns": 2800, "status": "PASS"},
                    ...
                ],
                "stats": {
                    "avg_ms": 0.52,
                    "min_ms": 0.30,
                    "max_ms": 1.20,
                    "p95_ms": 0.95,
                    "total_orders": 100
                }
            }
        """
        lines = self._read_lines()
        order_times_ms: List[float] = []
        control_timings: List[Dict[str, Any]] = []
        current_order_idx = -1

        for line in lines:
            if LMT_CHECK_START_RE.search(line):
                current_order_idx += 1

            # Per-control timing
            m = CONTROL_RESULT_RE.search(line)
            if m:
                caller_info = m.group('caller') or ""
                elapsed_ns = 0
                if caller_info:
                    tm = TIMING_SUFFIX_RE.search(caller_info)
                    if tm:
                        dur_str = tm.group('duration') or ""
                        if dur_str:
                            elapsed_ns = parse_duration_to_ns(dur_str)

                control_timings.append({
                    "order_index": max(0, current_order_idx),
                    "control": m.group('control'),
                    "elapsed_ns": elapsed_ns,
                    "status": m.group('status'),
                })

            # Total order time
            over_m = LMT_CHECK_OVER_RE.search(line)
            if over_m:
                dur_str = over_m.group('duration') or ""
                dur_ms = parse_duration_to_ms(dur_str)
                order_times_ms.append(round(dur_ms, 4))

        # Calculate stats
        stats = {"avg_ms": 0, "min_ms": 0, "max_ms": 0, "p95_ms": 0, "total_orders": len(order_times_ms)}
        if order_times_ms:
            sorted_times = sorted(order_times_ms)
            stats["avg_ms"] = round(sum(sorted_times) / len(sorted_times), 4)
            stats["min_ms"] = sorted_times[0]
            stats["max_ms"] = sorted_times[-1]
            p95_idx = int(len(sorted_times) * 0.95)
            stats["p95_ms"] = sorted_times[min(p95_idx, len(sorted_times) - 1)]

        return {
            "order_times_ms": order_times_ms,
            "control_timings": control_timings,
            "stats": stats,
        }
