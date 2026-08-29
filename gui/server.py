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
                csv_path=os.path.join(PROJECT_ROOT, "cache", "PriceCache.csv"),
                fetch_yfinance=False,
                auto_save=False,
            )
        except Exception:
            _state["prices"] = PriceCache()

        # OrderCache
        try:
            _state["orders"] = OrderCache(
                csv_path=os.path.join(PROJECT_ROOT, "OrderCache.csv"),
                dat_path=os.path.join(PROJECT_ROOT, "cache", "OrderCache.dat"),
                instrument_cache=_state["instruments"],
            )
        except Exception:
            _state["orders"] = OrderCache(dat_path=os.path.join(PROJECT_ROOT, "cache", "OrderCache.dat"))

        # PositionCache
        try:
            _state["positions"] = PositionCache(
                csv_path=os.path.join(PROJECT_ROOT, "cache", "PositionsCache.csv"),
                dat_path=os.path.join(PROJECT_ROOT, "cache", "PositionsCache.dat"),
            )
        except Exception:
            _state["positions"] = PositionCache()

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
    if "gce" not in _state or _state["gce"] is None:
        try:
            from gce.engine import GCE
            gce_inst = GCE(
                instrument_csv=os.path.join(PROJECT_ROOT, "HK-ListOfSecurities.csv"),
                price_csv=os.path.join(PROJECT_ROOT, "PriceCache.csv"),
                order_csv=os.path.join(PROJECT_ROOT, "OrderCache.csv"),
                position_csv=os.path.join(PROJECT_ROOT, "cache", "PositionsCache.csv"),
                log_dir=os.path.join(PROJECT_ROOT, "logs")
            )
            from gce.controls.quantity_control import MaxOrderQuantity
            from gce.controls.price_control import MaxOrderPrice
            from gce.controls.max_order_consideration import MaxOrderConsideration
            from gce.controls.bbo_price_tolerance import BBOPriceTolerance
            from gce.controls.close_price_tolerance import ClosePriceTolerance
            from gce.controls.last_price_tolerance import LastPriceTolerance
            from gce.controls.max_daily_turnover import MaxDailyTurnover

            gce_inst.register_control("MaxOrderQuantity", MaxOrderQuantity())
            gce_inst.register_control("MaxOrderPrice", MaxOrderPrice())
            gce_inst.register_control("MaxOrderConsideration", MaxOrderConsideration())
            gce_inst.register_control("BBOPriceTolerance", BBOPriceTolerance())
            gce_inst.register_control("ClosePriceTolerance", ClosePriceTolerance())
            gce_inst.register_control("LastPriceTolerance", LastPriceTolerance())
            gce_inst.register_control("MaxDailyTurnover", MaxDailyTurnover())

            _state["gce"] = gce_inst
        except Exception as e:
            print(f"[GUI] GCE engine init warning: {e}")
            _state["gce"] = None

    gce = _state.get("gce")
    if gce:
        gce.prices = _get("prices")
        gce.pxfeeder = _get("pxfeeder")
        gce.datamgr = _get("datamgr")
        gce.instruments = _get("instruments")
        gce.orders = _get("orders")
        gce.positions = _get("positions")
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
        if gce_engine and hasattr(gce_engine, "validate_order"):
            gce_passed, gce_rejections = gce_engine.validate_order(order)
            if not gce_passed:
                rejections.extend(gce_rejections)

        passed = (len(rejections) == 0)
        if passed:
            order.status = OrderStatus.LIVE
        else:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = "; ".join(rejections)

        if orders_cache:
            orders_cache.add_order(order)

        # Persist orders cache
        if orders_cache:
            try:
                orders_cache.save_to_csv(os.path.join(PROJECT_ROOT, "OrderCache.csv"))
            except Exception as e:
                print(f"Warning: Failed to save OrderCache.csv: {e}")
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
    return jsonify(fx)


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
# Section 11 — Log Viewer & Order Log Search
# ---------------------------------------------------------------------------
@app.route("/api/logs")
def api_logs():
    order_id = request.args.get("order_id", "").strip()
    search = request.args.get("search", "").strip()
    level = request.args.get("level", "").strip().upper()
    try:
        limit = int(request.args.get("limit", 200))
    except Exception:
        limit = 200

    log_path = Path(PROJECT_ROOT) / "logs" / "GCE.log"
    if not log_path.exists():
        return jsonify({"ok": True, "count": 0, "lines": [], "message": "Log file not found"})

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
            "count": len(matching_lines),
            "lines": matching_lines
        })
    except Exception as e:
        return jsonify({"ok": False, "message": str(e), "lines": []}), 500


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("  GCE Control Center")
    print(f"  http://localhost:5050")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5050, debug=False)
