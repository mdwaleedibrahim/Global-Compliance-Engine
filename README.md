# GCE - Global Compliance Engine

A high-performance pre-trade order risk management system for Hong Kong & global securities trading. Provides real-time order validation using configurable limit controls with parallel execution, nanosecond-precision logging, automated multi-currency FX data feeding, static instrument management, exchange session timing tracking, SQLite RMS control limits (`DataMgr`), and a web-based **GCE Control Center GUI**.

---

## Key Features

- **GCE Control Center Web GUI (`gui/`)**: Real-time web-based control center dashboard built with a lightweight Flask REST backend and dark-mode glassmorphism single-page frontend.
  - **Services Management**: Check status and **Start / Stop / Restart** sub-services (`Engine`, `PXFeeder`, `Logger Worker`, `DataMgr`).
  - **OMS Browser**: Interactive order browser with search, status filtering, and dynamic bottom pagination (50 per page, threshold > 20 records).
  - **Prices & FX**: Market prices cache view (with pagination > 20 records) and multi-currency FX rates grid.
  - **Instruments**: Searchable instrument catalog (17,635 RICs, RIC masterkey index) with **SecurityType** (mapped from CSV `Sub-Category`), `Total Instruments` indicator, and pagination (50 per page).
  - **Exchange Sessions**: Visual session status (`XHKG`, `XSES`) with live state badges (🟢 Trading, 🟡 Break, 🔴 Closed) and configuration reloading.
  - **Reconciliation**: Audit order fills against position caches with variance alerts.
  - **RMS Controls Summary**: Parsed `GCE.log` statistics per control with Chart.js Pass/Fail bar charts and **click-to-expand order drill-down**.
  - **Performance Metrics**: Real-time validation time line chart (ms) and per-control nanosecond execution stacked bar chart (`{file:line Xns}`).
- **Pre-Trade Control Engine**: Validates orders against multiple configurable limit controls (`MaxOrderQuantity`, `MaxOrderPrice`, `MaxOrderConsideration`, `ClosePriceTolerance`, `LastPriceTolerance`, `BBOPriceTolerance`) before execution.
- **DataMgr & SQLite RMS Control Limits**: Manages instrument static data from `"Instrument Static"` CSV files and maintains a local SQLite database (`rms_limits.db`) for RMS control limits.
  - Loads DB limits into an in-memory cache on startup.
  - Supports on-demand limit reloading (`reload_limits_from_db()`).
  - Supports bulk replacement of existing DB limits via CSV file (`replace_limits_from_csv()`).
  - Enforces text length limits (max 64 characters) and numerical caps (`999,999,999,999`).
  - Provides hierarchical wildcard matching for order limits (`Product`, `Trader`, `Account`, `symbol`, etc.).
  - **RIC Masterkey Indexing**: Stores instruments using RIC as the primary masterkey (`00001.HK`, `0700.HK`) with fallback stock code lookup.
- **Control Disable Status (`0 = Disabled`)**: Setting any limit control to `0` or `'0'` disables that check.
- **Sliding Window Rate Limit Specification (`x,y`)**: Supports `"x,y"` format for `DuplicateOrders` and `BurstOrders` (e.g., `"10,60"` = maximum 10 orders within 60s).
- **Exchange Session Timing Management (`config/Datamgr.ini`)**: Parses session start and end times for exchanges (e.g. `XHKG`, `XSES`), tracking active trading vs. break times.
- **Price Tolerance Controls & `limitchecker.ini` Configuration**: Controls for `ClosePriceTolerance`, `LastPriceTolerance`, and `BBOPriceTolerance` configured via [`config/limitchecker.ini`](config/limitchecker.ini).
- **PXFeeder Market & FX Data Feeder**: Integrated `PXFeeder` module fetching live prices and FX rates for major **US, EU, and APAC currencies** (`USD`, `EUR`, `GBP`, `JPY`, `HKD`, `AUD`, `SGD`, `CNH`, `CAD`, `CHF`) via `yfinance`.
- **Zero-Latency In-Memory Caching & Binary `.DAT` Snapshot Persistence**: All market data, positions, orders, instruments, FX rates, and RMS limits are cached in memory with binary snapshot recovery (`PriceCache.dat`, `InstrumentStatic.dat`).
- **Nanosecond-Precision Logging & Timing**: Control execution logs append caller location and nanosecond timing details at line ends (e.g., `{price_control.py:19 2800 nano seconds}`).
- **Performance**: Average validation time < 0.1ms, **20,000+ orders/sec** throughput.

---

## GCE Control Center GUI

Launch the web GUI server:

```bash
python gui/server.py
```

Access the dashboard in your web browser:
👉 **[http://localhost:5050](http://localhost:5050)**

### Pagination & Threshold Rules
- Applicable to **OMS Browser**, **Prices**, and **Instruments**.
- When records exceed **20 items**, a pagination section appears at the bottom.
- Displays **50 records per page** with `⏮ Prev`, `Page P of N`, and `Next ⏭` controls.
- Displays `Total Records: X` (or `Total Instruments: 17,635` for Instruments).

---

## SQLite Database Schema (`rms_control_limits`)

The local SQLite table `rms_control_limits` is defined in the following exact column order:

| Column Name | SQLite Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `DBId` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Autogenerated | Primary key |
| `Product`, `SecurityType`, `Application`, `Flow`, `Trader`, `Desk`, `Account`, `Client`, `symbol`, `exchange`, `underlying`, `AlgoStrategy`, `Currency`, `Side`, `OrderType`, `Tif`, `ExtendedKey1`..`5` | `VARCHAR(64)` | `'*'` | Text key columns for rule matching |
| `MaxOrderSize`, `MaxOrderPrice`, `MaxOrderValue`, `MaxOrderADV`, `ClosePriceTolerance`, `LastPriceTolerance`, `BBOPriceTolerance`, `MarketDepthCheck`, `MaxDailyVolume`, `MaxDailyValue`, `MaxDailyNetValue`, `MaxDailyTurnover`, `MaxDailyExposure`, `MaxDailyOpenValue`, `MaxDailyActiveOrders` | `NUMERIC` | `0` | Core numerical limits (`0` = disabled) |
| `DuplicateOrders`, `BurstOrders` | `VARCHAR(64)` | `'0'` | Rate limit controls (`'x,y'` format or `'0'`) |
| `ExtendedValue1`..`5`, `Flags` | `NUMERIC` | `0` | Extended numerical fields |
| `Restricted`, `SSRestricted` | `VARCHAR(64)` | `'N'` | Security restriction flags |
| `Enabled` | `VARCHAR(64)` | `'Y'` | Rule enablement status |

---

## Architecture & Project Structure

```
GCE (Global Compliance Engine)
├── gce/
│   ├── cache/
│   │   ├── base_cache.py (Abstract cache layer with file persistence)
│   │   ├── order_cache.py (Order CRUD and state management)
│   │   ├── position_cache.py (Position tracking and reconciliation)
│   │   ├── price_cache.py (Price cache with .dat binary persistence)
│   │   └── instrument_cache.py (Security universe with RIC masterkey)
│   ├── controls/
│   │   ├── base_control.py (Control framework with performance tracking)
│   │   ├── config_helper.py (LimitCheckerConfig loader for limitchecker.ini)
│   │   ├── quantity_control.py (MaxOrderQuantity control -> MaxOrderSize)
│   │   ├── price_control.py (MaxOrderPrice control -> MaxOrderPrice)
│   │   ├── max_order_consideration.py (MaxOrderConsideration control -> MaxOrderValue)
│   │   ├── close_price_tolerance.py (ClosePriceTolerance control -> ClosePriceTolerance)
│   │   ├── last_price_tolerance.py (LastPriceTolerance control -> LastPriceTolerance)
│   │   └── bbo_price_tolerance.py (BBOPriceTolerance control -> BBOPriceTolerance)
│   ├── datamgr.py (Instrument static manager, RIC indexing, SQLite DB, session timings)
│   ├── pxfeeder.py (yfinance prices & US/EU/APAC FX feeder)
│   ├── engine.py (GCE orchestrator with control registry & execution pipeline)
│   ├── logger.py (Structured logging with nanosecond timestamps & caller metadata)
│   ├── order_state_machine.py (Order state transition validation)
│   ├── position_updater.py (Fill application and reconciliation)
│   └── reconciler.py (Position variance detection)
├── gui/
│   ├── server.py (Flask API server for Control Center GUI)
│   ├── log_parser.py (GCE.log parser for RMS summary & performance timing)
│   ├── requirements.txt (GUI dependencies: Flask >= 3.0)
│   └── static/
│       ├── index.html (Single-page dashboard HTML)
│       ├── styles.css (Dark-mode glassmorphism CSS design system)
│       └── app.js (Frontend REST polling, Chart.js graphs, pagination & drill-down)
├── Instrument Static/ (Directory containing static data CSV files)
│   └── HK-ListOfSecurities.csv
├── config/
│   ├── Datamgr.ini (Exchange session timings)
│   └── limitchecker.ini (Price tolerance configuration settings)
├── rms_limits.db (SQLite database storing RMS control limit rules)
├── utils/
│   ├── cache_reader.py (Utilities for reading OrderCache, PXFeeder, and PositionCache)
│   ├── order_generator.py (Mock order generation for testing)
│   └── price_updater.py (Price cache management utility)
├── tests/
│   ├── test_datamgr.py (Unit tests for DataMgr static instrument manager)
│   ├── test_datamgr_sqlite.py (Unit tests for SQLite DB & RMS limits)
│   ├── test_datamgr_sessions.py (Unit tests for exchange session timings)
│   ├── test_price_tolerances.py (Unit tests for Close/Last/BBO Price Tolerances)
│   ├── test_pxfeeder.py (Unit tests for PXFeeder & FX conversions)
│   ├── test_cache_readers.py (Unit tests for cache readers)
│   ├── test_max_order_consideration.py (Max order consideration unit tests)
│   └── integration_tests.py (Comprehensive integration test suite)
└── example_usage.py (Comprehensive usage examples)
```

---

## Usage Examples

### 1. DataMgr (SQLite RMS Limits & Session Timings)

```python
from gce.datamgr import DataMgr

# Initialize DataMgr reading static CSV folder, SQLite DB, and session config
datamgr = DataMgr(
    static_dir="Instrument Static",
    dat_path="InstrumentStatic.dat",
    db_path="rms_limits.db",
    ini_path="config/Datamgr.ini"
)

# Replace limits in SQLite DB from CSV
datamgr.replace_limits_from_csv("rms_limits.csv")

# Match order attributes against cached RMS limits
matched_limits = datamgr.get_matching_limits(order)

# Check exchange session status
status = datamgr.get_session_status("XHKG", "09:45")  # Returns "Xsession1"
is_trading = datamgr.is_trading_time("XHKG", "09:45") # Returns True
```

### 2. Validating Orders with Risk Controls

```python
from gce import GCE
from gce.controls.quantity_control import MaxOrderQuantity
from gce.controls.price_control import MaxOrderPrice
from gce.controls.max_order_consideration import MaxOrderConsideration
from gce.controls.close_price_tolerance import ClosePriceTolerance
from gce.controls.last_price_tolerance import LastPriceTolerance
from gce.controls.bbo_price_tolerance import BBOPriceTolerance
from gce.cache.order_cache import Order

gce = GCE()

# Register controls
gce.register_control("MaxOrderQuantity", MaxOrderQuantity())
gce.register_control("MaxOrderPrice", MaxOrderPrice())
gce.register_control("MaxOrderConsideration", MaxOrderConsideration())
gce.register_control("ClosePriceTolerance", ClosePriceTolerance())
gce.register_control("LastPriceTolerance", LastPriceTolerance())
gce.register_control("BBOPriceTolerance", BBOPriceTolerance())

# Create test order
order = Order(order_id="ORD001", symbol="0700.HK", quantity=100, price=380.0, side="B", currency="HKD")

# Validate order
passed, rejections = gce.validate_order(order)
print("APPROVED" if passed else f"REJECTED: {rejections}")
```

---

## Running Tests

Run the complete unit test suite:

```bash
python -m unittest tests/test_cache_readers.py tests/test_datamgr.py tests/test_datamgr_sqlite.py tests/test_datamgr_sessions.py tests/test_order_cache_schema.py tests/test_parallel_controls.py tests/test_risk_analytics.py tests/test_max_order_consideration.py tests/test_price_tolerances.py
```

---

## License

Internal Use Only - Trading Systems Team