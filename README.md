# GCE - Global Compliance Engine

A high-performance pre-trade order risk management system for Hong Kong & global securities trading. Provides real-time order validation using configurable limit controls with parallel execution, nanosecond-precision logging, automated multi-currency FX data feeding, static instrument management, and SQLite RMS control limits (`DataMgr`).

## Features

- **Pre-Trade Control Engine**: Validates orders against multiple configurable limit controls (quantity, price, max consideration, notional value) before execution.
- **DataMgr & SQLite RMS Control Limits**: Manages instrument static data from `"Instrument Static"` CSV files and maintains a local SQLite database (`rms_limits.db`) for RMS control limits.
  - Loads DB limits into an in-memory cache on startup.
  - Supports on-demand limit reloading (`reload_limits_from_db()`).
  - Supports bulk replacement of existing DB limits via CSV file (`replace_limits_from_csv()`).
  - Enforces text length limits (max 64 characters) and numerical caps (`999,999,999,999`).
  - Provides hierarchical wildcard matching for order limits.
- **PXFeeder Market & FX Data Feeder**: Integrated `PXFeeder` module fetching live prices and FX rates for major **US, EU, and APAC currencies** (`USD`, `EUR`, `GBP`, `JPY`, `HKD`, `AUD`, `SGD`, `CNH`, `CAD`, `CHF`) via `yfinance`.
- **Automated Hourly Background Refresh**: Periodic background worker thread refreshing market data every hour (3600s) without interrupting pre-trade order validation.
- **Zero-Latency In-Memory Caching**: All prices, positions, orders, instruments, FX rates, and RMS limits are cached in memory for sub-millisecond control checks.
- **Binary `.DAT` Snapshot Persistence**: Automatic dumping and fast recovery of market data snapshots to binary `.dat` storage files (`PriceCache.dat`, `InstrumentStatic.dat`).
- **Cache Reader Utilities**: High-level inspection tools (`OrderCacheReader`, `PXFeederReader`, `PositionCacheReader`, `CacheReaderManager`) for querying engine state and generating summaries.
- **Control Framework & Parallel Execution**: Multithreaded execution pipeline running risk controls concurrently with sub-millisecond latency.
- **Structured Logging**: Nanosecond-precision timestamps with rejection tracking.
- **Performance**: Average validation time < 0.1ms, **20,000+ orders/sec** throughput.

## Architecture

```
GCE (Global Compliance Engine)
├── gce/
│   ├── cache/
│   │   ├── base_cache.py (Abstract cache layer with file persistence)
│   │   ├── order_cache.py (Order CRUD and state management)
│   │   ├── position_cache.py (Position tracking and reconciliation)
│   │   ├── price_cache.py (Price cache with .dat binary persistence)
│   │   └── instrument_cache.py (Security universe)
│   ├── controls/
│   │   ├── base_control.py (Control framework with performance tracking)
│   │   ├── quantity_control.py (MaxOrderQuantity validation)
│   │   ├── price_control.py (MaxOrderPrice validation)
│   │   └── max_order_consideration.py (FX-converted consideration limit control)
│   ├── datamgr.py (Instrument static manager & SQLite RMS control limits manager)
│   ├── pxfeeder.py (yfinance prices & US/EU/APAC FX feeder with hourly background refresh)
│   ├── engine.py (GCE orchestrator with control registry & execution pipeline)
│   ├── logger.py (Structured logging with nanosecond timestamps)
│   ├── order_state_machine.py (Order state transition validation)
│   ├── position_updater.py (Fill application and reconciliation)
│   └── reconciler.py (Position variance detection)
├── Instrument Static/ (Directory containing instrument static data CSV files)
│   └── HK-ListOfSecurities.csv
├── rms_limits.db (SQLite database storing RMS control limit rules)
├── utils/
│   ├── cache_reader.py (Utilities for reading OrderCache, PXFeeder, and PositionCache)
│   ├── order_generator.py (Mock order generation for testing)
│   └── price_updater.py (Price cache management utility)
├── tests/
│   ├── test_datamgr.py (Unit tests for DataMgr static instrument manager)
│   ├── test_datamgr_sqlite.py (Unit tests for DataMgr SQLite DB & RMS limits)
│   ├── test_pxfeeder.py (Unit tests for PXFeeder & FX conversions)
│   ├── test_cache_readers.py (Unit tests for cache readers)
│   ├── test_max_order_consideration.py (Max order consideration unit tests)
│   └── integration_tests.py (Comprehensive integration test suite)
├── config/
│   └── controls.json (Control configuration)
├── logs/
│   └── GCE.log (Rotating log file with 10MB max, 5 backups)
└── example_usage.py (Comprehensive usage examples)
```

---

## Core Components & Usage

### 1. DataMgr (Instrument Static & SQLite RMS Limits)

`DataMgr` reads instrument static data from `"Instrument Static"` CSV files and manages RMS Control Limits in a local SQLite database (`rms_limits.db`):

```python
from gce.datamgr import DataMgr

# Initialize DataMgr reading static folder and SQLite limits DB
datamgr = DataMgr(
    static_dir="Instrument Static",
    dat_path="InstrumentStatic.dat",
    db_path="rms_limits.db"
)

# 1. Replace limits in SQLite DB from a CSV file
count = datamgr.replace_limits_from_csv("rms_limits.csv")
print(f"Imported {count} limit rules into SQLite DB!")

# 2. Reload limits from DB into memory on demand
datamgr.reload_limits_from_db()

# 3. Match order attributes against cached RMS limits
matched_limits = datamgr.get_matching_limits(order)
print("Max Order Size:", matched_limits['MaxOrderSize'])
print("Max Order Value:", matched_limits['MaxOrderValue'])

# 4. Instrument static lookup & order detail enrichment
inst = datamgr.get_instrument("0700.HK")
enriched_details = datamgr.lookup_order_details(order)
```

### 2. PXFeeder & FX Rate Feeder

`PXFeeder` downloads market data and FX conversion rates at startup and automatically refreshes them every hour in a background daemon thread:

```python
from gce.pxfeeder import PXFeeder

# Initialize PXFeeder with binary .dat persistence and hourly refresh
feeder = PXFeeder(
    dat_path="PriceCache.dat",
    symbols=["0700.HK", "9988.HK", "AAPL", "MSFT"],
    fetch_on_start=True,
    refresh_interval=3600,  # 1 hour
    auto_start_bg=True
)

# Zero-latency in-memory FX conversion (US, EU, APAC currencies)
hkd_usd = feeder.get_fx_rate("HKD", "USD")  # e.g., 0.128

# Stop background refresh on shutdown
feeder.stop()
```

### 3. GCE Engine & Control Validation

The `GCE` engine orchestrates controls, market data, static instruments, and SQLite RMS limits (`DataMgr`):

```python
from gce import GCE
from gce.controls.max_order_consideration import MaxOrderConsideration
from gce.controls.quantity_control import MaxOrderQuantity
from gce.cache.order_cache import Order

# Initialize GCE (automatically loads DataMgr, PXFeeder, PriceCache.dat, instruments, orders)
gce = GCE(
    instrument_csv="HK-ListOfSecurities.csv",
    price_csv="PriceCache.csv",
    order_csv="OrderCache.csv",
    position_csv="PositionsCache.csv"
)

# Register controls
gce.register_control("MaxOrderQuantity", MaxOrderQuantity(limit=1000))

# Validate order concurrently
passed, rejections = gce.validate_order(order, is_new=True, parallel=True)

# Shutdown engine & background threads
gce.shutdown()
```

---

## How to Start the App and Send Test Orders

### Option 1: Run Demonstration Script
```powershell
$env:PYTHONPATH="."
python example_usage.py
```

### Option 2: Programmatic Usage (Python API)
```python
from gce import GCE
from gce.cache.order_cache import Order

gce = GCE()

# Create test order
order = Order(order_id="ORD001", symbol="0700.HK", quantity=100, price=380.0, side="B", currency="HKD")

# Validate order
passed, rejections = gce.validate_order(order)
print("APPROVED" if passed else f"REJECTED: {rejections}")
```

---

## Data Persistence & Storage Formats

- **rms_limits.db**: SQLite database storing pre-trade RMS control limits and rule attributes.
- **InstrumentStatic.dat**: Binary snapshot of static instrument definitions loaded from `"Instrument Static"` CSV files.
- **PriceCache.dat**: Binary snapshot storage (via `pickle`) for fast startup recovery of prices and FX rates.
- **OrderCache.csv**: Order lifecycle records and statuses (`Live`, `Fill`, `Rejected`, `Cancelled`).
- **PositionsCache.csv**: Real-time position volumes, exposures, and USD values.

---

## Running Tests

Run all unit and integration test suites:

```bash
# Run complete unit test suite
python -m unittest tests/test_datamgr.py tests/test_datamgr_sqlite.py tests/test_pxfeeder.py tests/test_cache_readers.py tests/test_max_order_consideration.py tests/test_yfinance_price_cache.py

# Run comprehensive integration test suite
python tests/integration_tests.py
```

---

## License

Internal Use Only - Trading Systems Team