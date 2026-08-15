"""GCE Control Center — Flask API Server.

Internal localhost tool. No authentication required.
Serves the single-page dashboard and REST API endpoints for all GCE subsystems.
"""

import os
import sys
import time
import threading
from pathlib import Path
from datetime import datetime

# Add project root to path so we can import gce modules
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import Flask, jsonify, request, send_from_directory

# GCE imports
from gce.cache.order_cache import OrderCache, Order, OrderStatus
from gce.cache.price_cache import PriceCache
from gce.cache.instrument_cache import InstrumentCache
from gce.cache.position_cache import PositionCache
from gce.logger import GCELogger
from gce.pxfeeder import PXFeeder
from gce.datamgr import DataMgr
from gce.reconciler import PositionReconciler

from gui.log_parser import LogParser

# ---------------------------------------------------------------------------
# Flask App
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder="static", static_url_path="")

# ---------------------------------------------------------------------------
# GCE State — Lazy-initialized singletons
# ---------------------------------------------------------------------------
_state = {
    "start_time": time.time(),
    "logger": None,
    "pxfeeder": None,
    "datamgr": None,
    "instruments": None,
    "prices": None,
    "orders": None,
    "positions": None,
    "log_parser": None,
}
_lock = threading.Lock()


def _init_components():
    """Initialize GCE components lazily on first API call."""
    with _lock:
        if _state["logger"] is not None:
            return  # already initialized

        log_dir = os.path.join(PROJECT_ROOT, "logs")

        _state["logger"] = GCELogger(log_dir=log_dir, console=False, file=True)
        _state["logger"].info("GCE Control Center GUI started")

        # DataMgr
        try:
            _state["datamgr"] = DataMgr(
                static_dir=os.path.join(PROJECT_ROOT, "Instrument Static"),
                dat_path=os.path.join(PROJECT_ROOT, "InstrumentStatic.dat"),
            )
            _state["datamgr"].load_session_config(
                os.path.join(PROJECT_ROOT, "config", "Datamgr.ini")
            )
        except Exception as e:
            print(f"[GUI] DataMgr init warning: {e}")
            _state["datamgr"] = DataMgr(auto_load=False)

        # Instruments
        try:
            _state["instruments"] = InstrumentCache(
                os.path.join(PROJECT_ROOT, "HK-ListOfSecurities.csv")
            )
        except Exception:
            _state["instruments"] = InstrumentCache()

        # PXFeeder
        try:
            symbols = (
                list(_state["instruments"].instruments.keys())[:10]
                if _state["instruments"].count() > 0
                else None
            )
            _state["pxfeeder"] = PXFeeder(
                dat_path=os.path.join(PROJECT_ROOT, "PriceCache.dat"),
                symbols=symbols,
                fetch_on_start=True,
            )
        except Exception as e:
            print(f"[GUI] PXFeeder init warning: {e}")
            _state["pxfeeder"] = PXFeeder(fetch_on_start=False, auto_start_bg=False)

        # PriceCache
        try:
            _state["prices"] = PriceCache(
                dat_path=os.path.join(PROJECT_ROOT, "PriceCache.dat"),
                csv_path=os.path.join(PROJECT_ROOT, "PriceCache.csv"),
                fetch_yfinance=False,
                auto_save=False,
            )
        except Exception:
            _state["prices"] = PriceCache()

        # OrderCache
        try:
            _state["orders"] = OrderCache(
                csv_path=os.path.join(PROJECT_ROOT, "OrderCache.csv"),
                instrument_cache=_state["instruments"],
            )
        except Exception:
            _state["orders"] = OrderCache()

        # PositionCache
        try:
            _state["positions"] = PositionCache(
                os.path.join(PROJECT_ROOT, "PositionsCache.csv")
            )
        except Exception:
            _state["positions"] = PositionCache()

        # Log parser
        _state["log_parser"] = LogParser(os.path.join(log_dir, "GCE.log"))


def _get(key):
    if _state["logger"] is None:
        _init_components()
    return _state[key]


# ---------------------------------------------------------------------------
# Routes — Static
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ---------------------------------------------------------------------------
# Section 1 — Service Status
# ---------------------------------------------------------------------------
def _service_info(name):
    """Return status dict for a named service."""
    info = {"name": name, "status": "stopped", "detail": ""}
    try:
        if name == "pxfeeder":
            px = _get("pxfeeder")
            if px and hasattr(px, "_bg_thread") and px._bg_thread and px._bg_thread.is_alive():
                info["status"] = "running"
                info["detail"] = f"{len(px._prices)} prices cached"
            else:
                info["status"] = "stopped"
                info["detail"] = "Background thread not running"
        elif name == "logger":
            lg = _get("logger")
            if lg and hasattr(lg, "worker_thread") and lg.worker_thread.is_alive():
                info["status"] = "running"
                info["detail"] = "Async log worker active"
            else:
                info["status"] = "stopped"
        elif name == "datamgr":
            dm = _get("datamgr")
            if dm:
                cnt = dm.count()
                info["status"] = "running" if cnt > 0 else "stopped"
                info["detail"] = f"{cnt} instruments loaded"
        elif name == "engine":
            info["status"] = "running"
            uptime = int(time.time() - _state["start_time"])
            mins, secs = divmod(uptime, 60)
            hrs, mins = divmod(mins, 60)
            info["detail"] = f"Uptime {hrs:02d}:{mins:02d}:{secs:02d}"
    except Exception as e:
        info["status"] = "error"
        info["detail"] = str(e)
    return info


@app.route("/api/status")
def api_status():
    services = ["engine", "pxfeeder", "logger", "datamgr"]
    return jsonify([_service_info(s) for s in services])


@app.route("/api/service/<name>/start", methods=["POST"])
def api_service_start(name):
    try:
        if name == "pxfeeder":
            px = _get("pxfeeder")
            if px:
                px.start()
            return jsonify({"ok": True, "message": f"{name} started"})
        elif name == "logger":
            lg = _get("logger")
            if lg and not lg.worker_thread.is_alive():
                lg.worker_thread = threading.Thread(target=lg._log_worker, name="GCELoggerWorker", daemon=True)
                lg._stop_event.clear()
                lg.worker_thread.start()
            return jsonify({"ok": True, "message": f"{name} started"})
        elif name == "datamgr":
            dm = _get("datamgr")
            if dm:
                dm.reload_limits_from_db()
            return jsonify({"ok": True, "message": f"{name} reloaded"})
        return jsonify({"ok": False, "message": f"Unknown service: {name}"}), 400
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/service/<name>/stop", methods=["POST"])
def api_service_stop(name):
    try:
        if name == "pxfeeder":
            px = _get("pxfeeder")
            if px:
                px.stop()
            return jsonify({"ok": True, "message": f"{name} stopped"})
        elif name == "logger":
            lg = _get("logger")
            if lg:
                lg.shutdown()
            return jsonify({"ok": True, "message": f"{name} stopped"})
        return jsonify({"ok": False, "message": f"Cannot stop {name}"}), 400
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/service/<name>/restart", methods=["POST"])
def api_service_restart(name):
    api_service_stop(name)
    time.sleep(0.3)
    return api_service_start(name)


# ---------------------------------------------------------------------------
# Section 3 — OMS Browser (Orders)
# ---------------------------------------------------------------------------
@app.route("/api/orders")
def api_orders():
    oc = _get("orders")
    orders_list = []
    for o in oc.orders.values():
        status_val = o.status.value if hasattr(o.status, "value") else str(o.status)
        orders_list.append({
            "order_id": o.order_id,
            "ric": o.ric,
            "symbol": o.symbol,
            "side": o.side,
            "quantity": o.quantity,
            "price": o.price,
            "status": status_val,
            "trader": o.trader,
            "account": o.account,
            "desk": getattr(o, "desk", ""),
            "client": getattr(o, "client", ""),
            "currency": getattr(o, "currency", "HKD"),
            "exchange": getattr(o, "exchange", ""),
            "timestamp": o.timestamp,
            "filled": o.filled,
            "open_qty": o.open_qty,
            "rejection_reason": getattr(o, "rejection_reason", ""),
        })
    return jsonify(orders_list)


# ---------------------------------------------------------------------------
# Section 4 — Prices & FX
# ---------------------------------------------------------------------------
@app.route("/api/prices")
def api_prices():
    pc = _get("prices")
    prices_list = []
    for ric, pd in pc.prices.items():
        prices_list.append({
            "ric": ric,
            "open": getattr(pd, "open_price", 0),
            "bid": pd.bid,
            "ask": pd.ask,
            "last": pd.last,
            "close": pd.close,
            "mid": pd.mid,
            "timestamp": getattr(pd, "timestamp", ""),
        })
    return jsonify(prices_list)


@app.route("/api/fx")
def api_fx():
    px = _get("pxfeeder")
    fx = px.get_all_fx_rates() if px else {}
    return jsonify(fx)


# ---------------------------------------------------------------------------
# Section 5 — Instruments
# ---------------------------------------------------------------------------
@app.route("/api/instruments")
def api_instruments():
    ic = _get("instruments")
    dm = _get("datamgr")
    instruments_list = []

    # Prefer DataMgr static data (richer), fall back to InstrumentCache
    if dm and dm.count() > 0:
        search = request.args.get("search", "").upper()
        limit = int(request.args.get("limit", 0))
        count = 0
        for ric, inst in dm.instruments.items():
            inst_name = str(getattr(inst, "name", "") or "")
            if search and search not in ric.upper() and search not in inst_name.upper():
                continue
            instruments_list.append({
                "ric": ric,
                "stock_code": getattr(inst, "stock_code", ""),
                "name": getattr(inst, "name", ""),
                "category": getattr(inst, "category", ""),
                "security_type": getattr(inst, "security_type", getattr(inst, "sub_category", "")),
                "board_lot": getattr(inst, "board_lot", 0),
                "currency": getattr(inst, "trading_currency", "HKD"),
                "isin": getattr(inst, "isin", ""),
                "shortsell": getattr(inst, "shortsell_eligible", False),
                "cas": getattr(inst, "cas_eligible", False),
                "vcm": getattr(inst, "vcm_eligible", False),
            })
            count += 1
            if limit > 0 and count >= limit:
                break
    else:
        search = request.args.get("search", "").upper()
        limit = int(request.args.get("limit", 0))
        count = 0
        for ric, inst in ic.instruments.items():
            if search and search not in ric.upper() and search not in inst.name.upper():
                continue
            instruments_list.append({
                "ric": ric,
                "stock_code": inst.stock_code,
                "name": inst.name,
                "category": inst.category,
                "security_type": getattr(inst, "security_type", ""),
                "board_lot": inst.board_lot,
                "currency": inst.currency,
                "isin": inst.isin,
                "shortsell": inst.shortsell_eligible,
                "cas": inst.cas_eligible,
                "vcm": inst.vcm_eligible,
            })
            count += 1
            if limit > 0 and count >= limit:
                break
    return jsonify(instruments_list)


# ---------------------------------------------------------------------------
# Section 6 — Exchange Sessions
# ---------------------------------------------------------------------------
@app.route("/api/sessions")
def api_sessions():
    dm = _get("datamgr")
    result = {}
    if dm and hasattr(dm, "session_config"):
        for exchange, sessions in dm.session_config.items():
            exchange_data = {"sessions": [], "state": "closed", "status_text": "Closed"}
            for sp in sessions:
                exchange_data["sessions"].append({
                    "session": sp.session_num,
                    "start": sp.start_time.strftime("%H:%M"),
                    "end": sp.end_time.strftime("%H:%M"),
                })
            # Determine current state
            try:
                status = dm.get_session_status(exchange)
                if isinstance(status, str):
                    if status.startswith("Xsession"):
                        exchange_data["state"] = "trading"
                        exchange_data["status_text"] = f"Trading ({status})"
                    elif status.upper() == "BREAK":
                        exchange_data["state"] = "break"
                        exchange_data["status_text"] = "Intermission / Break"
                    else:
                        exchange_data["state"] = "closed"
                        exchange_data["status_text"] = status
            except Exception:
                pass
            result[exchange] = exchange_data
    return jsonify(result)


@app.route("/api/sessions/update", methods=["POST"])
def api_sessions_update():
    """Reload session config from ini file."""
    dm = _get("datamgr")
    if dm:
        try:
            dm.load_session_config(os.path.join(PROJECT_ROOT, "config", "Datamgr.ini"))
            return jsonify({"ok": True, "message": "Sessions reloaded"})
        except Exception as e:
            return jsonify({"ok": False, "message": str(e)}), 500
    return jsonify({"ok": False, "message": "DataMgr not available"}), 500


# ---------------------------------------------------------------------------
# Section 7 — Reconciliation
# ---------------------------------------------------------------------------
@app.route("/api/reconciliation")
def api_reconciliation():
    oc = _get("orders")
    pc = _get("positions")
    try:
        reconciler = PositionReconciler(oc, pc)
        reports = reconciler.reconcile_all()
        results = []
        for r in reports:
            results.append({
                "symbol": r.symbol,
                "trader": r.trader,
                "account": r.account,
                "total_orders": r.total_orders,
                "live_orders": r.live_orders,
                "filled_orders": r.filled_orders,
                "total_order_qty": r.total_order_qty,
                "total_filled_qty": r.total_filled_qty,
                "position_exists": r.position_exists,
                "net_quantity": r.net_quantity,
                "net_value": r.net_value,
                "qty_variance": r.qty_variance,
                "value_variance": r.value_variance,
                "status": r.status,
                "issues": r.issues,
            })
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e), "results": []}), 200


# ---------------------------------------------------------------------------
# Section 9 — RMS Controls Summary
# ---------------------------------------------------------------------------
@app.route("/api/rms/summary")
def api_rms_summary():
    parser = _get("log_parser")
    return jsonify(parser.get_rms_summary())


@app.route("/api/rms/orders/<control>/<status>")
def api_rms_orders(control, status):
    parser = _get("log_parser")
    return jsonify(parser.get_orders_for_control(control, status))


# ---------------------------------------------------------------------------
# Section 10 — Performance
# ---------------------------------------------------------------------------
@app.route("/api/performance")
def api_performance():
    parser = _get("log_parser")
    return jsonify(parser.get_performance_data())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("  GCE Control Center")
    print(f"  http://localhost:5050")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5050, debug=False)
