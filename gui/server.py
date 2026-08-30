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
from gce.engine import GCE

from gui.log_parser import LogParser

# ---------------------------------------------------------------------------
# Flask App
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder="static", static_url_path="")

@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

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
    "perf_order_times": [],
    "perf_control_timings": [],
}
_lock = threading.RLock()
_initialized = False


def _init_components():
    """Initialize GCE components."""
    global _initialized
    with _lock:
        if _initialized:
            return  # already initialized

        log_dir = os.path.join(PROJECT_ROOT, "logs")

        _state["logger"] = GCELogger(log_dir=log_dir, console=False, file=True)
        _state["logger"].info("GCE Control Center GUI started")

        # DataMgr
        try:
            _state["datamgr"] = DataMgr(
                static_dir=os.path.join(PROJECT_ROOT, "Instrument Static"),
                dat_path=os.path.join(PROJECT_ROOT, "cache", "InstrumentStatic.dat"),
            )
            _state["datamgr"].load_session_config(
                os.path.join(PROJECT_ROOT, "config", "Datamgr.ini")
            )
        except Exception as e:
            print(f"[GUI] DataMgr init warning: {e}")
            _state["datamgr"] = DataMgr(auto_load=False)

        # Instruments (initialized from DataMgr singleton in memory)
        try:
            _state["instruments"] = InstrumentCache.from_datamgr(_state["datamgr"])
            if _state["instruments"].count() == 0 and os.path.exists(os.path.join(PROJECT_ROOT, "HK-ListOfSecurities.csv")):
                _state["instruments"].load_from_csv(os.path.join(PROJECT_ROOT, "HK-ListOfSecurities.csv"))
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
                dat_path=os.path.join(PROJECT_ROOT, "cache", "PriceCache.dat"),
                symbols=symbols,
                fetch_on_start=False,
                auto_start_bg=True,
            )
        except Exception as e:
            print(f"[GUI] PXFeeder init warning: {e}")
            _state["pxfeeder"] = PXFeeder(fetch_on_start=False, auto_start_bg=False)

        # PriceCache
        try:
            _state["prices"] = PriceCache(
                dat_path=os.path.join(PROJECT_ROOT, "cache", "PriceCache.dat"),
                fetch_yfinance=False,
                auto_save=False,
            )
        except Exception:
            _state["prices"] = PriceCache(dat_path=os.path.join(PROJECT_ROOT, "cache", "PriceCache.dat"))

        # OrderCache
        try:
            _state["orders"] = OrderCache(
                dat_path=os.path.join(PROJECT_ROOT, "cache", "OrderCache.dat"),
                instrument_cache=_state["instruments"],
            )
        except Exception:
            _state["orders"] = OrderCache(dat_path=os.path.join(PROJECT_ROOT, "cache", "OrderCache.dat"))

        # PositionCache
        try:
            _state["positions"] = PositionCache(
                dat_path=os.path.join(PROJECT_ROOT, "cache", "PositionsCache.dat"),
            )
        except Exception:
            _state["positions"] = PositionCache(dat_path=os.path.join(PROJECT_ROOT, "cache", "PositionsCache.dat"))

        # Logger
        _state["logger"] = GCELogger(log_dir=log_dir)

        # Log parser
        _state["log_parser"] = LogParser(os.path.join(log_dir, "GCE.log"))

        _initialized = True


# Start background initialization immediately on module load so services are pre-warmed
threading.Thread(target=_init_components, name="GCEPreWarmThread", daemon=True).start()


def _get(key):
    if not _initialized:
        _init_components()
    return _state.get(key)


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
            if px:
                is_running = hasattr(px, "_bg_thread") and px._bg_thread and px._bg_thread.is_alive()
                info["status"] = "running" if is_running else "ready"
                info["detail"] = f"{len(px._prices)} prices, {len(px._fx_rates)} FX rates cached"
            else:
                info["status"] = "stopped"
                info["detail"] = "Not initialized"
        elif name == "logger":
            lg = _get("logger")
            if lg:
                is_running = hasattr(lg, "worker_thread") and lg.worker_thread and lg.worker_thread.is_alive()
                info["status"] = "running" if is_running else "stopped"
                info["detail"] = "Async log worker active" if is_running else "Log worker idle"
            else:
                info["status"] = "stopped"
                info["detail"] = "Not initialized"
        elif name == "datamgr":
            dm = _get("datamgr")
            if dm:
                cnt = dm.count()
                info["status"] = "running" if cnt > 0 else "ready"
                info["detail"] = f"{cnt} instruments loaded"
            else:
                info["status"] = "stopped"
                info["detail"] = "Not initialized"
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


import configparser


def _reinit_all_services():
    """Restart GCE engine singletons as a whole."""
    global _initialized
    with _lock:
        px = _state.get("pxfeeder")
        if px and hasattr(px, "stop"):
            try:
                px.stop()
            except Exception:
                pass
        lg = _state.get("logger")
        if lg and hasattr(lg, "shutdown"):
            try:
                lg.shutdown()
            except Exception:
                pass

        _initialized = False
        _state["start_time"] = time.time()
        _init_components()


@app.route("/api/service/<name>/start", methods=["POST"])
def api_service_start(name):
    try:
        if name in ("engine", "gce", "all"):
            _reinit_all_services()
            return jsonify({"ok": True, "message": "GCE Engine service restarted successfully"})
        elif name == "pxfeeder":
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
        if name in ("engine", "gce", "all"):
            px = _get("pxfeeder")
            if px and hasattr(px, "stop"):
                px.stop()
            return jsonify({"ok": True, "message": "GCE Engine stopped"})
        elif name == "pxfeeder":
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
    if name in ("engine", "gce", "all"):
        _reinit_all_services()
        return jsonify({"ok": True, "message": "GCE Engine service restarted successfully"})
    api_service_stop(name)
    time.sleep(0.3)
    return api_service_start(name)


# ---------------------------------------------------------------------------
# Section: System Configuration API
# ---------------------------------------------------------------------------
@app.route("/api/config")
def api_get_config():
    """Retrieve all configuration parameters from config/*.ini files."""
    try:
        config_dir = Path(PROJECT_ROOT) / "config"
        results = []
        for ini_path in sorted(config_dir.glob("*.ini")):
            parser = configparser.ConfigParser()
            parser.optionxform = str
            raw_text = ini_path.read_text(encoding="utf-8")
            
            lines = raw_text.splitlines()
            first_code_line = next((l.strip() for l in lines if l.strip() and not l.strip().startswith(";") and not l.strip().startswith("#")), "")
            parsed_text = raw_text if first_code_line.startswith("[") else "[General]\n" + raw_text

            parser.read_string(parsed_text)
            
            sections = []
            for sec in parser.sections():
                items = [{"key": k, "value": v} for k, v in parser.items(sec)]
                sections.append({"section": sec, "items": items})
            
            results.append({
                "filename": ini_path.name,
                "path": str(ini_path),
                "sections": sections
            })
        return jsonify(results)
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/config/update", methods=["POST"])
def api_update_config():
    """Update a configuration parameter in config/*.ini and apply it immediately."""
    try:
        data = request.json or {}
        filename = data.get("filename", "")
        section = data.get("section", "General")
        key = data.get("key", "")
        val = str(data.get("value", "")).strip()

        if not filename or not key:
            return jsonify({"ok": False, "message": "Filename and key are required"}), 400

        config_file = Path(PROJECT_ROOT) / "config" / filename
        if not config_file.exists():
            return jsonify({"ok": False, "message": f"Config file not found: {filename}"}), 404

        raw_text = config_file.read_text(encoding="utf-8")
        lines = raw_text.splitlines()

        updated = False
        current_section = "General"
        
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                current_section = stripped[1:-1].strip()
                new_lines.append(line)
                continue
            
            if current_section == section and stripped and not stripped.startswith(";") and not stripped.startswith("#"):
                if "=" in line:
                    k, _ = line.split("=", 1)
                    if k.strip() == key:
                        new_lines.append(f"{key}={val}" if "=" not in line or " " not in line.split("=")[0] else f"{key} = {val}")
                        updated = True
                        continue
            new_lines.append(line)

        if not updated:
            target_sec_header = f"[{section}]"
            sec_idx = None
            for idx, l in enumerate(new_lines):
                if l.strip() == target_sec_header:
                    sec_idx = idx
                    break
            
            if sec_idx is not None:
                new_lines.insert(sec_idx + 1, f"{key} = {val}")
            else:
                if section != "General":
                    new_lines.append(f"\n[{section}]")
                new_lines.append(f"{key} = {val}")

        config_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        # --- IMMEDIATE BACKEND APPLICATION ---
        applied_msg = "Updated configuration file."
        if filename == "limitchecker.ini":
            px = _get("pxfeeder")
            if px:
                if key == "refresh_interval":
                    try:
                        px.refresh_interval = int(val)
                        applied_msg = f"PXFeeder refresh interval set to {val}s immediately."
                    except ValueError:
                        pass
                elif key == "max_symbols":
                    try:
                        px.max_symbols = int(val)
                        applied_msg = f"PXFeeder max_symbols set to {val} immediately."
                    except ValueError:
                        pass
        elif filename == "Datamgr.ini":
            dm = _get("datamgr")
            if dm:
                dm.load_session_config(str(config_file))
                applied_msg = "DataMgr exchange session timings reloaded immediately."

        return jsonify({
            "ok": True,
            "filename": filename,
            "section": section,
            "key": key,
            "value": val,
            "message": f"Successfully updated [{section}] {key} = '{val}' in {filename}. {applied_msg}"
        })
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


# ---------------------------------------------------------------------------
# Section 2 — GCE Limits (RMS Control Limits CRUD & Import/Export)
# ---------------------------------------------------------------------------
@app.route("/api/limits")
def api_limits_list():
    dm = _get("datamgr")
    if not dm:
        return jsonify([])
    rows = dm.get_all_limits_from_db()
    return jsonify(rows)


@app.route("/api/limits/options")
def api_limits_options():
    dm = _get("datamgr")
    if not dm:
        return jsonify({})
    return jsonify(dm.get_limit_options())


@app.route("/api/limits", methods=["POST"])
def api_limits_create():
    dm = _get("datamgr")
    if not dm:
        return jsonify({"ok": False, "message": "DataMgr not available"}), 500
    try:
        data = request.json or {}
        db_id = dm.add_limit_rule(data)
        return jsonify({"ok": True, "db_id": db_id, "message": "Limit rule created successfully"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.route("/api/limits/<int:db_id>", methods=["PUT"])
def api_limits_update(db_id):
    dm = _get("datamgr")
    if not dm:
        return jsonify({"ok": False, "message": "DataMgr not available"}), 500
    try:
        data = request.json or {}
        success = dm.update_limit_rule(db_id, data)
        if success:
            return jsonify({"ok": True, "message": f"Limit rule {db_id} updated"})
        return jsonify({"ok": False, "message": f"Rule {db_id} not found"}), 404
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.route("/api/limits/<int:db_id>", methods=["DELETE"])
def api_limits_delete(db_id):
    dm = _get("datamgr")
    if not dm:
        return jsonify({"ok": False, "message": "DataMgr not available"}), 500
    try:
        success = dm.delete_limit_rule(db_id)
        if success:
            return jsonify({"ok": True, "message": f"Limit rule {db_id} deleted"})
        return jsonify({"ok": False, "message": f"Rule {db_id} not found"}), 404
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.route("/api/limits/export")
def api_limits_export():
    dm = _get("datamgr")
    if not dm:
        return "DataMgr not available", 500
    from gce.datamgr import ALL_DB_COLUMNS
    rows = dm.get_all_limits_from_db()
    
    import io, csv
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=ALL_DB_COLUMNS)
    writer.writeheader()
    for r in rows:
        row_dict = {col: r.get(col, '') for col in ALL_DB_COLUMNS}
        writer.writerow(row_dict)

    from flask import Response
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=rms_control_limits.csv"}
    )


@app.route("/api/limits/import", methods=["POST"])
def api_limits_import():
    dm = _get("datamgr")
    if not dm:
        return jsonify({"ok": False, "message": "DataMgr not available"}), 500
    
    if "file" not in request.files:
        return jsonify({"ok": False, "message": "No CSV file uploaded"}), 400
    
    file = request.files["file"]
    mode = request.form.get("mode", "replace")  # 'replace' or 'append'

    import tempfile, os
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    try:
        if mode == "replace":
            count = dm.replace_limits_from_csv(tmp_path)
        else:
            import csv
            count = 0
            with open(tmp_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for r in reader:
                    dm.add_limit_rule(dict(r))
                    count += 1
        return jsonify({"ok": True, "message": f"Successfully imported {count} rules ({mode} mode)"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 400
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Section 3 — OMS Browser & Order Placement
# ---------------------------------------------------------------------------
def _get_gce_engine():
    gce = _get("gce")
    if not gce:
        try:
            from concurrent.futures import ThreadPoolExecutor
            gce_inst = GCE.__new__(GCE)
            log_inst = _get("logger")
            if not log_inst:
                log_inst = GCELogger(log_dir=os.path.join(PROJECT_ROOT, "logs"))
                _state["logger"] = log_inst
            gce_inst.logger = log_inst
            gce_inst.executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="GCEControlExec")
            gce_inst.datamgr = _get("datamgr")
            gce_inst.instruments = _get("instruments")
            gce_inst.pxfeeder = _get("pxfeeder")
            gce_inst.prices = _get("prices")
            gce_inst.orders = _get("orders")
            gce_inst.positions = _get("positions")
            gce_inst.controls = {}
            gce_inst.rejection_messages = []
            _state["gce"] = gce_inst
            gce = gce_inst
        except Exception as e:
            print(f"[GUI] GCE engine init warning: {e}")
            return None

    if gce:
        gce.prices = _get("prices")
        gce.pxfeeder = _get("pxfeeder")
        gce.instruments = _get("instruments")
        gce.orders = _get("orders")
        gce.positions = _get("positions")
        if not hasattr(gce, "controls") or gce.controls is None:
            gce.controls = {}
        if not hasattr(gce, "rejection_messages") or gce.rejection_messages is None:
            gce.rejection_messages = []

    return gce


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


@app.route("/api/positions")
def api_positions():
    pc = _get("positions")
    if not pc:
        return jsonify([])
    if hasattr(pc, "get_all_positions"):
        positions_list = pc.get_all_positions()
    else:
        positions_list = []
        for p in pc.positions.values():
            if hasattr(p, "to_dict"):
                positions_list.append(p.to_dict())
            else:
                positions_list.append({
                    "symbol": getattr(p, "symbol", ""),
                    "Trader": getattr(p, "trader", ""),
                    "Account": getattr(p, "account", ""),
                    "Client": getattr(p, "client", ""),
                    "Desk": getattr(p, "desk", ""),
                    "bvol": getattr(p, "buy_volume", 0),
                    "bval": getattr(p, "buy_value", 0.0),
                    "svol": getattr(p, "sell_volume", 0),
                    "sval": getattr(p, "sell_value", 0.0),
                    "Turnover": getattr(p, "buy_value", 0.0) + getattr(p, "sell_value", 0.0),
                    "NetValue": getattr(p, "buy_value", 0.0) - getattr(p, "sell_value", 0.0),
                })
    return jsonify(positions_list)


@app.route("/api/orders/place", methods=["POST"])
def api_orders_place():
    orders_cache = _get("orders")
    dm = _get("datamgr")
    data = request.get_json(force=True, silent=True) or request.form or {}

    try:
        ric = str(data.get("ric", "") or "").strip()
        if not ric:
            return jsonify({"ok": False, "message": "RIC/Symbol is required"}), 400

        side = str(data.get("side", "B") or "B").strip().upper()
        order_type = str(data.get("order_type", "LMT") or "LMT").strip().upper()

        qty = int(data.get("quantity", 0) or 0)
        px = float(data.get("price", 0.0) or 0.0)
        if qty <= 0:
            return jsonify({"ok": False, "message": "Quantity must be > 0"}), 400
        if order_type != "MKT" and px <= 0.0:
            return jsonify({"ok": False, "message": "Price must be > 0 for Limit orders"}), 400
        trader = str(data.get("trader", "*") or "*").strip()
        account = str(data.get("account", "*") or "*").strip()
        client = str(data.get("client", "*") or "*").strip()
        desk = str(data.get("desk", "*") or "*").strip()
        currency = str(data.get("currency", "HKD") or "HKD").strip()
        product = str(data.get("product", "Equity") or "Equity").strip()
        security_type = str(data.get("security_type", "") or "").strip()
        exchange = str(data.get("exchange", "XHKG") or "XHKG").strip()
        application = str(data.get("application", "*") or "*").strip()
        flow = str(data.get("flow", "*") or "*").strip()
        algo_strategy = str(data.get("algo_strategy", "*") or "*").strip()
        tif = str(data.get("tif", "DAY") or "DAY").strip()
        order_id = str(data.get("order_id", "") or "").strip()
        if not order_id:
            order_id = f"ORD-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{int(time.time()*1000)%1000:03d}"

        order = Order(
            order_id=order_id,
            ric=ric,
            symbol=ric,
            quantity=qty,
            price=px,
            side=side,
            order_type=order_type,
            trader=trader,
            account=account,
            client=client,
            desk=desk,
            currency=currency,
            product=product,
            security_type=security_type,
            exchange=exchange,
            application=application,
            flow=flow,
            algo_strategy=algo_strategy,
            tif=tif,
            timestamp=datetime.now().isoformat()
        )

        gce_engine = _get_gce_engine()
        rejections = []

        # 1. Evaluate against DataMgr SQLite RMS DB rules
        if dm:
            details = dm.lookup_order_details(order)
            rule = details.get("rms_limits", {})
            if isinstance(rule, dict) and rule:
                if rule.get("Enabled") != "N":
                    if rule.get("Restricted") == "Y":
                        rejections.append(f"Restricted rule (ID {rule.get('DBId')}): Order is restricted for Trader '{order.trader}' / Symbol '{order.symbol}'")
                    if order.side == "S" and rule.get("SSRestricted") == "Y" and not details.get("shortsell_eligible", False):
                        rejections.append(f"Shortsell Restricted rule (ID {rule.get('DBId')}): Instrument '{order.symbol}' is not shortsell eligible")
                    max_q = float(rule.get("MaxOrderQuantity", 0) or 0)
                    if max_q > 0 and order.quantity > max_q:
                        rejections.append(f"Order quantity {order.quantity} exceeds MaxOrderQuantity limit ({int(max_q)})")
                    max_p = float(rule.get("MaxOrderPrice", 0) or 0)
                    if max_p > 0 and order.price > max_p:
                        rejections.append(f"Order price {order.price} exceeds MaxOrderPrice limit ({max_p})")

        # 2. Evaluate against GCE Engine registered controls
        val_start = time.perf_counter()
        if gce_engine and hasattr(gce_engine, "validate_order"):
            gce_passed, gce_rejections = gce_engine.validate_order(order)
            if not gce_passed:
                rejections.extend(gce_rejections)
        val_elapsed_ms = round((time.perf_counter() - val_start) * 1000.0, 4)

        with _lock:
            if "perf_order_times" in _state:
                _state["perf_order_times"].append(val_elapsed_ms)
                if len(_state["perf_order_times"]) > 500:
                    _state["perf_order_times"].pop(0)

        passed = (len(rejections) == 0)
        if passed:
            order.status = OrderStatus.LIVE
        else:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = "; ".join(rejections)

        if orders_cache:
            orders_cache.add_order(order)

        # Persist orders cache to .dat
        if orders_cache:
            try:
                orders_cache.save_to_dat(os.path.join(PROJECT_ROOT, "cache", "OrderCache.dat"))
            except Exception as e:
                print(f"Warning: Failed to save OrderCache.dat: {e}")

        status_str = order.status.value if hasattr(order.status, "value") else str(order.status)
        return jsonify({
            "ok": True,
            "status": "APPROVED" if passed else "REJECTED",
            "message": f"Order {order.order_id} {'approved' if passed else 'rejected'}",
            "rejections": rejections,
            "order": {
                "order_id": order.order_id,
                "ric": order.ric,
                "quantity": order.quantity,
                "price": order.price,
                "side": order.side,
                "order_type": order.order_type,
                "status": status_str,
                "trader": order.trader,
                "account": order.account,
                "client": order.client,
                "desk": order.desk,
                "currency": order.currency,
                "product": order.product,
                "security_type": getattr(order, "security_type", getattr(order, "sub_category", "")),
                "exchange": getattr(order, "exchange", "XHKG"),
                "rejection_reason": getattr(order, "rejection_reason", ""),
                "timestamp": order.timestamp,
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "message": str(e)}), 400


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


@app.route("/api/prices/fetch", methods=["POST"])
def api_prices_fetch_live():
    data = request.json or {}
    ric = str(data.get("ric", "") or "").strip()
    if not ric:
        return jsonify({"ok": False, "message": "RIC is required"}), 400
    try:
        import yfinance as yf
        ticker = yf.Ticker(ric)
        info = ticker.info or {}
        price = (
            info.get("regularMarketPrice")
            or info.get("currentPrice")
            or info.get("previousClose")
            or info.get("ask")
            or info.get("bid")
        )
        if price is None:
            fast = getattr(ticker, "fast_info", None)
            if fast:
                price = fast.get("last_price") or fast.get("regular_market_previous_close")
        if price is None or float(price) <= 0:
            return jsonify({"ok": False, "message": f"Unable to fetch live price for {ric}"}), 404
        return jsonify({"ok": True, "ric": ric, "price": float(price)})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.route("/api/prices", methods=["POST"])
def api_prices_create():
    pc = _get("prices")
    if not pc:
        return jsonify({"ok": False, "message": "PriceCache not available"}), 500
    try:
        data = request.json or {}
        ric = str(data.get("ric", "") or "").strip()
        if not ric:
            return jsonify({"ok": False, "message": "RIC is required"}), 400
        
        bid = float(data.get("bid", 0) or 0)
        ask = float(data.get("ask", 0) or 0)
        last = float(data.get("last", 0) or 0)
        close = float(data.get("close", 0) or 0)
        open_price = float(data.get("open", 0) or 0)

        p = pc.update_price(ric=ric, bid=bid, ask=ask, last=last, close=close, open_price=open_price)
        pxf = _get("pxfeeder")
        if pxf and hasattr(pxf, "_prices"):
            pxf._prices[ric] = p
            pxf._prices[ric.upper()] = p
        return jsonify({
            "ok": True,
            "message": f"Price entry for {ric} updated",
            "price": {
                "ric": p.ric, "open": p.open_price, "bid": p.bid, "ask": p.ask,
                "last": p.last, "close": p.close, "mid": p.mid, "timestamp": p.timestamp
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.route("/api/prices/<path:ric>", methods=["PUT"])
def api_prices_update(ric):
    pc = _get("prices")
    if not pc:
        return jsonify({"ok": False, "message": "PriceCache not available"}), 500
    try:
        data = request.json or {}
        bid = float(data.get("bid", 0) or 0)
        ask = float(data.get("ask", 0) or 0)
        last = float(data.get("last", 0) or 0)
        close = float(data.get("close", 0) or 0)
        open_price = float(data.get("open", 0) or 0)

        p = pc.update_price(ric=ric, bid=bid, ask=ask, last=last, close=close, open_price=open_price)
        pxf = _get("pxfeeder")
        if pxf and hasattr(pxf, "_prices"):
            pxf._prices[ric] = p
            pxf._prices[ric.upper()] = p
        return jsonify({
            "ok": True,
            "message": f"Price entry for {ric} updated",
            "price": {
                "ric": p.ric, "open": p.open_price, "bid": p.bid, "ask": p.ask,
                "last": p.last, "close": p.close, "mid": p.mid, "timestamp": p.timestamp
            }
        })
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.route("/api/prices/<path:ric>", methods=["DELETE"])
def api_prices_delete(ric):
    pc = _get("prices")
    if not pc:
        return jsonify({"ok": False, "message": "PriceCache not available"}), 500
    try:
        success = pc.delete_price(ric)
        if success:
            return jsonify({"ok": True, "message": f"Price entry for {ric} deleted"})
        return jsonify({"ok": False, "message": f"Price entry for {ric} not found"}), 404
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.route("/api/fx")
def api_fx():
    px = _get("pxfeeder")
    fx = px.get_all_fx_rates() if px else {}
    search = (request.args.get("search", "") or "").strip().lower()
    entries = []
    for pair, rate in sorted(fx.items()):
        normalized_key = str(pair).upper().replace(" ", "")
        if search and search not in normalized_key.lower() and search not in str(rate).lower():
            continue
        if "/" not in normalized_key and len(normalized_key) == 6:
            left, right = normalized_key[:3], normalized_key[3:]
            normalized_key = f"{left}/{right}"
        entries.append({"pair": normalized_key, "rate": float(rate)})
    return jsonify(entries if entries else [])


@app.route("/api/fx", methods=["POST"])
def api_fx_create():
    px = _get("pxfeeder")
    if not px:
        return jsonify({"ok": False, "message": "PXFeeder not available"}), 500
    try:
        data = request.json or {}
        pair = str(data.get("pair", "") or "").strip().upper().replace(" ", "")
        if not pair:
            return jsonify({"ok": False, "message": "FX pair is required"}), 400
        if "/" not in pair and len(pair) == 6:
            pair = f"{pair[:3]}/{pair[3:]}"
        rate = float(data.get("rate", 0) or 0)
        px.set_fx_rate_in_memory(pair, rate)
        return jsonify({"ok": True, "message": f"FX rate for {pair} updated", "fx": {"pair": pair, "rate": rate}})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.route("/api/fx/<path:pair>", methods=["PUT"])
def api_fx_update(pair):
    px = _get("pxfeeder")
    if not px:
        return jsonify({"ok": False, "message": "PXFeeder not available"}), 500
    try:
        data = request.json or {}
        normalized_pair = str(pair).strip().upper().replace(" ", "")
        if "/" not in normalized_pair and len(normalized_pair) == 6:
            normalized_pair = f"{normalized_pair[:3]}/{normalized_pair[3:]}"
        rate = float(data.get("rate", 0) or 0)
        px.set_fx_rate_in_memory(normalized_pair, rate)
        return jsonify({"ok": True, "message": f"FX rate for {normalized_pair} updated", "fx": {"pair": normalized_pair, "rate": rate}})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.route("/api/fx/<path:pair>", methods=["DELETE"])
def api_fx_delete(pair):
    px = _get("pxfeeder")
    if not px:
        return jsonify({"ok": False, "message": "PXFeeder not available"}), 500
    try:
        normalized_pair = str(pair).strip().upper().replace(" ", "")
        if "/" not in normalized_pair and len(normalized_pair) == 6:
            normalized_pair = f"{normalized_pair[:3]}/{normalized_pair[3:]}"
        removed = px.remove_fx_rate_in_memory(normalized_pair)
        if removed:
            return jsonify({"ok": True, "message": f"FX rate for {normalized_pair} deleted"})
        return jsonify({"ok": False, "message": f"FX rate for {normalized_pair} not found"}), 404
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.route("/api/fx/fetch", methods=["POST"])
def api_fx_fetch_live():
    px = _get("pxfeeder")
    if not px:
        return jsonify({"ok": False, "message": "PXFeeder not available"}), 500
    try:
        data = request.json or {}
        pair = str(data.get("pair", "") or "").strip()
        if not pair:
            return jsonify({"ok": False, "message": "FX pair is required"}), 400
        rate = px.fetch_live_fx_rate(pair)
        if rate is None:
            return jsonify({"ok": False, "message": f"Unable to fetch live FX rate for {pair}"}), 404
        return jsonify({"ok": True, "pair": pair.upper().replace(" ", ""), "rate": float(rate)})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 400


# ---------------------------------------------------------------------------
# Section 5 — Instruments
# ---------------------------------------------------------------------------
@app.route("/api/instruments")
def api_instruments():
    ic = _get("instruments")
    dm = _get("datamgr")
    instruments_list = []

    # Check for force CSV reload parameter
    reload_arg = request.args.get("reload", "").lower() in ("true", "1")
    if reload_arg:
        if dm:
            dm.load(force_csv_reload=True)
        if ic:
            from pathlib import Path
            if Path("HK-ListOfSecurities.csv").exists():
                ic.load_from_csv("HK-ListOfSecurities.csv")

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
                "exchange": getattr(inst, "exchange", "XHKG"),
                "category": getattr(inst, "category", ""),
                "security_type": getattr(inst, "security_type", getattr(inst, "sub_category", "")),
                "board_lot": getattr(inst, "board_lot", 0),
                "currency": getattr(inst, "trading_currency", getattr(inst, "currency", "HKD")),
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
        if ic:
            for ric, inst in ic.instruments.items():
                if search and search not in ric.upper() and search not in inst.name.upper():
                    continue
                instruments_list.append({
                    "ric": ric,
                    "stock_code": inst.stock_code,
                    "name": inst.name,
                    "exchange": getattr(inst, "exchange", "XHKG"),
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


@app.route("/api/instruments", methods=["POST"])
def api_instruments_create():
    dm = _get("datamgr")
    ic = _get("instruments")
    data = request.json or {}
    ric = str(data.get("ric", "") or "").strip()
    if not ric:
        return jsonify({"ok": False, "message": "RIC is required"}), 400

    try:
        inst_dict = {}
        if dm and hasattr(dm, "add_or_update_instrument"):
            inst_obj = dm.add_or_update_instrument(data)
            inst_dict = inst_obj.to_dict()
        if ic and hasattr(ic, "add_or_update_instrument"):
            inst_obj2 = ic.add_or_update_instrument(data)
            if not inst_dict:
                inst_dict = inst_obj2.to_dict()

        return jsonify({
            "ok": True,
            "message": f"Instrument {ric} updated successfully",
            "instrument": inst_dict
        })
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.route("/api/instruments/<path:ric>", methods=["PUT"])
def api_instruments_update(ric):
    dm = _get("datamgr")
    ic = _get("instruments")
    data = request.json or {}
    data["ric"] = ric

    try:
        inst_dict = {}
        if dm and hasattr(dm, "add_or_update_instrument"):
            inst_obj = dm.add_or_update_instrument(data)
            inst_dict = inst_obj.to_dict()
        if ic and hasattr(ic, "add_or_update_instrument"):
            inst_obj2 = ic.add_or_update_instrument(data)
            if not inst_dict:
                inst_dict = inst_obj2.to_dict()

        return jsonify({
            "ok": True,
            "message": f"Instrument {ric} updated successfully",
            "instrument": inst_dict
        })
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 400


@app.route("/api/instruments/<path:ric>", methods=["DELETE"])
def api_instruments_delete(ric):
    dm = _get("datamgr")
    ic = _get("instruments")

    found_dm = dm.delete_instrument(ric) if (dm and hasattr(dm, "delete_instrument")) else False
    found_ic = ic.delete_instrument(ric) if (ic and hasattr(ic, "delete_instrument")) else False

    if found_dm or found_ic:
        return jsonify({"ok": True, "message": f"Instrument {ric} deleted successfully"})
    return jsonify({"ok": False, "message": f"Instrument {ric} not found"}), 404


@app.route("/api/instruments/delta", methods=["POST"])
def api_instruments_delta():
    """
    Intraday delta update endpoint for instruments.
    Accepts a single instrument dict or list of delta dicts.
    Applies changes directly in-memory and saves .dat snapshot without reloading full universe.
    """
    dm = _get("datamgr")
    ic = _get("instruments")
    gce_inst = _get("gce")
    data = request.json or {}

    deltas = data.get("deltas", data) if isinstance(data, dict) else data
    if isinstance(deltas, dict) and "deltas" not in data and "ric" not in deltas:
        return jsonify({"ok": False, "message": "Invalid delta format, expected list or object with 'ric'"}), 400

    try:
        dm_res = {"applied": 0, "deleted": 0, "total": 0}
        if dm and hasattr(dm, "apply_delta"):
            dm_res = dm.apply_delta(deltas)
        if ic and hasattr(ic, "apply_delta"):
            ic.apply_delta(deltas)
        if gce_inst and hasattr(gce_inst, "instruments") and hasattr(gce_inst.instruments, "apply_delta"):
            gce_inst.instruments.apply_delta(deltas)

        return jsonify({
            "ok": True,
            "message": f"Applied {dm_res.get('applied', 0)} intraday updates, {dm_res.get('deleted', 0)} deletions. Total active: {dm_res.get('total', 0)}",
            "delta_summary": dm_res
        })
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 400


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
    log_data = parser.get_performance_data() if parser else {
        "order_times_ms": [],
        "control_timings": [],
        "stats": {"avg_ms": 0, "min_ms": 0, "max_ms": 0, "p95_ms": 0, "total_orders": 0}
    }

    # Merge live in-memory telemetry if available
    live_times = _state.get("perf_order_times", [])
    if live_times:
        combined_times = list(log_data.get("order_times_ms", []))
        for t in live_times[-50:]:
            if len(combined_times) < len(live_times):
                combined_times.append(t)
        if combined_times:
            sorted_times = sorted(combined_times)
            log_data["order_times_ms"] = combined_times
            p95_idx = int(len(sorted_times) * 0.95)
            log_data["stats"] = {
                "avg_ms": round(sum(sorted_times) / len(sorted_times), 4),
                "min_ms": sorted_times[0],
                "max_ms": sorted_times[-1],
                "p95_ms": sorted_times[min(p95_idx, len(sorted_times) - 1)],
                "total_orders": len(combined_times)
            }

    return jsonify(log_data)


# ---------------------------------------------------------------------------
# Section 11 — Log Viewer & Order Log Search
# ---------------------------------------------------------------------------
@app.route("/api/logs")
def api_logs():
    order_id = request.args.get("order_id", "").strip()
    search = request.args.get("search", "").strip()
    level = request.args.get("level", "").strip().upper()
    log_type = request.args.get("file", "GCE").strip().lower()
    try:
        limit = int(request.args.get("limit", 200))
    except Exception:
        limit = 200

    filename = "pxfeeder.log" if log_type in ("pxfeeder", "px") else "GCE.log"
    log_path = Path(PROJECT_ROOT) / "logs" / filename
    if not log_path.exists():
        return jsonify({"ok": True, "count": 0, "lines": [], "message": f"Log file {filename} not found"})

    matching_lines = []
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            if order_id and order_id not in line_str:
                continue

            if level and level != "ALL" and f"[{level}]" not in line_str:
                continue

            if search and search.lower() not in line_str.lower():
                continue

            matching_lines.append(line_str)

        if limit > 0 and len(matching_lines) > limit:
            matching_lines = matching_lines[-limit:]

        return jsonify({
            "ok": True,
            "filename": filename,
            "count": len(matching_lines),
            "lines": matching_lines
        })
    except Exception as e:
        return jsonify({"ok": False, "message": str(e), "lines": []}), 500


# ---------------------------------------------------------------------------
# Section 12 — Admin Operations & Cache Management
# ---------------------------------------------------------------------------
def _format_file_size(size_bytes: int) -> str:
    """Format bytes into readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


@app.route("/api/admin/status")
def api_admin_status():
    """Retrieve overview metrics for all caches and log files."""
    try:
        oc = _get("orders")
        pc = _get("positions")
        prc = _get("prices")
        px = _get("pxfeeder")
        dm = _get("datamgr")
        ic = _get("instruments")

        orders_count = len(oc.orders) if oc and hasattr(oc, "orders") else 0
        positions_count = len(pc.positions) if pc and hasattr(pc, "positions") else 0
        prices_count = len(prc.prices) if prc and hasattr(prc, "prices") else 0
        fx_count = len(px.get_all_fx_rates()) if px and hasattr(px, "get_all_fx_rates") else 0
        
        instruments_count = 0
        if dm and hasattr(dm, "count"):
            instruments_count = dm.count()
        elif ic and hasattr(ic, "count"):
            instruments_count = ic.count()

        # Scan log directory
        log_dir = Path(PROJECT_ROOT) / "logs"
        log_files = []
        if log_dir.exists():
            for p in sorted(log_dir.glob("**/*")):
                if p.is_file():
                    rel_path = str(p.relative_to(log_dir))
                    size_bytes = p.stat().st_size
                    mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                    
                    if p.name in ("GCE.log", "pxfeeder.log"):
                        file_type = "Active Log"
                    elif p.suffix == ".zip" or "archive" in rel_path:
                        file_type = "Archived"
                    else:
                        file_type = "Rotated Log"

                    log_files.append({
                        "filename": rel_path,
                        "size_bytes": size_bytes,
                        "size_formatted": _format_file_size(size_bytes),
                        "mtime": mtime,
                        "type": file_type,
                    })

        return jsonify({
            "ok": True,
            "caches": {
                "orders": orders_count,
                "positions": positions_count,
                "prices": prices_count,
                "fx_rates": fx_count,
                "instruments": instruments_count,
            },
            "logs": log_files
        })
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/admin/purge/oms", methods=["POST"])
def api_admin_purge_oms():
    """Purge OMS order cache in memory and on disk (.dat only)."""
    try:
        oc = _get("orders")
        if oc and hasattr(oc, "orders"):
            with _lock:
                oc.orders.clear()

        # Remove any legacy OrderCache.csv
        for csv_name in ("OrderCache.csv", "cache/OrderCache.csv"):
            p = Path(PROJECT_ROOT) / csv_name
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

        # Reset .dat cache file
        for dat_name in ("cache/OrderCache.dat", "OrderCache.dat"):
            p = Path(PROJECT_ROOT) / dat_name
            if p.exists():
                try:
                    import pickle
                    with open(p, "wb") as f:
                        pickle.dump({}, f)
                except Exception:
                    pass

        return jsonify({"ok": True, "message": "OMS order cache cleared in memory and .dat disk snapshot."})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/admin/purge/positions", methods=["POST"])
def api_admin_purge_positions():
    """Purge positions cache in memory and on disk (.dat only)."""
    try:
        pc = _get("positions")
        if pc and hasattr(pc, "positions"):
            with _lock:
                pc.positions.clear()
                if hasattr(pc, "pattern_index"):
                    pc.pattern_index.clear()

        # Remove any legacy PositionsCache.csv
        for csv_name in ("cache/PositionsCache.csv", "PositionsCache.csv"):
            p = Path(PROJECT_ROOT) / csv_name
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

        # Reset .dat cache file
        for dat_name in ("cache/PositionsCache.dat", "PositionsCache.dat"):
            p = Path(PROJECT_ROOT) / dat_name
            if p.exists():
                try:
                    import pickle
                    with open(p, "wb") as f:
                        pickle.dump({}, f)
                except Exception:
                    pass

        return jsonify({"ok": True, "message": "Positions cache cleared in memory and .dat disk snapshot."})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/admin/purge/prices", methods=["POST"])
def api_admin_purge_prices():
    """Purge price & FX cache in memory and on disk (.dat only)."""
    try:
        prc = _get("prices")
        if prc and hasattr(prc, "prices"):
            with _lock:
                prc.prices.clear()

        px = _get("pxfeeder")
        if px:
            with px._lock:
                px._prices.clear()
                px._fx_rates.clear()
                px._init_default_fx_rates()
            if hasattr(px, "logger") and px.logger:
                px.logger.info("ADMIN_PURGE Price and FX cache cleared by administrator")

        # Remove any legacy PriceCache.csv
        for csv_name in ("cache/PriceCache.csv", "PriceCache.csv"):
            p = Path(PROJECT_ROOT) / csv_name
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

        # Reset .dat cache file
        for dat_name in ("cache/PriceCache.dat", "PriceCache.dat"):
            p = Path(PROJECT_ROOT) / dat_name
            if p.exists():
                try:
                    import pickle
                    with open(p, "wb") as f:
                        pickle.dump({"prices": {}, "fx_rates": {}, "last_updated": datetime.now().isoformat()}, f)
                except Exception:
                    pass

        return jsonify({"ok": True, "message": "Price and FX cache cleared in memory and .dat disk snapshot."})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/admin/purge/instruments", methods=["POST"])
def api_admin_purge_instruments():
    """Purge instruments in-memory cache and binary .dat recovery snapshot."""
    try:
        ic = _get("instruments")
        if ic:
            with _lock:
                ic.instruments.clear()
                if hasattr(ic, "ric_to_code"):
                    ic.ric_to_code.clear()

        dm = _get("datamgr")
        if dm:
            with dm._lock:
                dm.instruments.clear()
                if hasattr(dm, "code_to_ric"):
                    dm.code_to_ric.clear()

        # Remove .dat snapshot files so recovery starts fresh
        for dat_name in ("cache/InstrumentStatic.dat", "InstrumentStatic.dat"):
            p = Path(PROJECT_ROOT) / dat_name
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

        return jsonify({"ok": True, "message": "Instruments runtime cache and .dat snapshot purged successfully."})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/admin/purge/all", methods=["POST"])
def api_admin_purge_all():
    """Purge all caches (OMS, Positions, Prices, Instruments)."""
    try:
        api_admin_purge_oms()
        api_admin_purge_positions()
        api_admin_purge_prices()
        api_admin_purge_instruments()
        return jsonify({"ok": True, "message": "All GCE caches (OMS, Positions, Prices, Instruments) purged successfully."})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/admin/logs/rollover", methods=["POST"])
def api_admin_logs_rollover():
    """Rollover current GCE.log (and optionally pxfeeder.log) and create fresh file(s)."""
    try:
        data = request.json or {}
        target = data.get("target", "all").lower()
        rotated_files = []

        if target in ("all", "gce"):
            lg = _get("logger")
            if lg and hasattr(lg, "rollover"):
                res = lg.rollover()
                if res:
                    rotated_files.append(Path(res).name)
            else:
                log_file = Path(PROJECT_ROOT) / "logs" / "GCE.log"
                if log_file.exists():
                    now_str = datetime.now().strftime("%Y-%m-%d_%H%M%S")
                    rot = log_file.parent / f"GCE.log.{now_str}"
                    log_file.rename(rot)
                    log_file.touch()
                    rotated_files.append(rot.name)

        if target in ("all", "pxfeeder", "px"):
            px = _get("pxfeeder")
            if px and hasattr(px, "logger") and hasattr(px.logger, "rollover"):
                res = px.logger.rollover()
                if res:
                    rotated_files.append(Path(res).name)

        return jsonify({
            "ok": True,
            "message": f"Rollover completed. Created new active log file(s). Rotated: {', '.join(rotated_files) if rotated_files else 'None'}",
            "rotated_files": rotated_files
        })
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/admin/logs/archive", methods=["POST"])
def api_admin_logs_archive():
    """Archive all historical / rotated log files into a zip file, preserving active log files."""
    try:
        import zipfile
        log_dir = Path(PROJECT_ROOT) / "logs"
        if not log_dir.exists():
            return jsonify({"ok": True, "message": "No logs directory found to archive.", "count": 0})

        archive_dir = log_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filename = f"logs_archive_{now_str}.zip"
        zip_path = archive_dir / zip_filename

        # Identify rotated / non-current log files
        to_archive = []
        for item in log_dir.iterdir():
            if item.is_file() and item.name not in ("GCE.log", "pxfeeder.log") and not item.name.endswith(".zip"):
                to_archive.append(item)

        if not to_archive:
            return jsonify({"ok": True, "message": "No historical log files found to archive.", "count": 0})

        # Compress into zip
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in to_archive:
                zipf.write(file_path, arcname=file_path.name)

        # Delete archived files
        archived_names = []
        for file_path in to_archive:
            archived_names.append(file_path.name)
            try:
                file_path.unlink()
            except Exception:
                pass

        return jsonify({
            "ok": True,
            "message": f"Successfully archived {len(archived_names)} historical log files into {zip_filename}",
            "archive_filename": zip_filename,
            "archived_files": archived_names,
            "count": len(archived_names)
        })
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("  GCE Control Center")
    print(f"  http://localhost:5050")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5050, debug=False)
