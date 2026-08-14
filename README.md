# GCE - Global Compliance Engine

A high-performance pre-trade order risk management system for Hong Kong & global securities trading. Provides real-time order validation using configurable limit controls with parallel execution, nanosecond-precision logging, automated multi-currency FX data feeding, static instrument management (`DataMgr`), and comprehensive position reconciliation.

## Features

- **Pre-Trade Control Engine**: Validates orders against multiple configurable limit controls (quantity, price, max consideration, notional value) before execution.
- **DataMgr Instrument Static Manager**: Reads static instrument CSV files from `"Instrument Static"` directory, caches in memory, persists to `.dat` file (`InstrumentStatic.dat`), and provides fast lookup utilities for order detail enrichment (lot size, trading currency, ISIN, shortsell eligibility, stamp duty).
- **PXFeeder Market & FX Data Feeder**: Integrated `PXFeeder` module fetching live prices and FX rates for major **US, EU, and APAC currencies** (`USD`, `EUR`, `GBP`, `JPY`, `HKD`, `AUD`, `SGD`, `CNH`, `CAD`, `CHF`) via `yfinance`.
- **Automated Hourly Background Refresh**: Periodic background worker thread refreshing market data every hour (3600s) without interrupting pre-trade order validation.
- **Zero-Latency In-Memory Caching**: All prices, positions, orders, instruments, and FX rates are cached in memory for sub-millisecond control checks.
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
│   ├── datamgr.py (Instrument static data manager from "Instrument Static" folder & .dat persistence)
│   ├── pxfeeder.py (yfinance prices & US/EU/APAC FX feeder with hourly background refresh)
│   ├── engine.py (GCE orchestrator with control registry & execution pipeline)
│   ├── logger.py (Structured logging with nanosecond timestamps)
│   ├── order_state_machine.py (Order state transition validation)
│   ├── position_updater.py (Fill application and reconciliation)
│   └── reconciler.py (Position variance detection)
├── Instrument Static/ (Directory containing instrument static data CSV files)
│   └── HK-ListOfSecurities.csv
├── utils/
│   ├── cache_reader.py (Utilities for reading OrderCache, PXFeeder, and PositionCache)
│   ├── order_generator.py (Mock order generation for testing)
│   └── price_updater.py (Price cache management utility)
├── tests/
│   ├── test_datamgr.py (Unit tests for DataMgr static instrument manager)
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

### 1. DataMgr (Instrument Static Manager)

`DataMgr` reads instrument static data from CSV files inside `"Instrument Static"`, caches them in memory, saves a binary snapshot to `InstrumentStatic.dat`, and enriches order details:

```python
from gce.datamgr import DataMgr

# Initialize DataMgr reading from "Instrument Static" folder
datamgr = DataMgr(static_dir="Instrument Static", dat_path="InstrumentStatic.dat")

# Fast in-memory instrument lookups
inst = datamgr.get_instrument("0700.HK")
print("Board Lot:", datamgr.get_board_lot("0700.HK"))            # e.g., 100
print("Trading Currency:", datamgr.get_trading_currency("0700.HK")) # e.g., HKD
print("Shortsell Eligible:", datamgr.is_shortsell_eligible("0700.HK"))

# Enrich order details with static instrument attributes
enriched_details = datamgr.lookup_order_details(order)
print("ISIN:", enriched_details['isin'])
print("Board Lot Valid:", enriched_details['board_lot_valid'])
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
eur_usd = feeder.get_fx_rate("EUR", "USD")  # e.g., 1.08

# Stop background refresh on shutdown
feeder.stop()
```

### 3. GCE Engine & Control Validation

The `GCE` engine orchestrates controls, market data, static instruments (`DataMgr`), and order validation:

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

# Access DataMgr from engine
datamgr = gce.datamgr
instrument_info = datamgr.get_instrument("0700.HK")

# Register controls
gce.register_control("MaxOrderQuantity", MaxOrderQuantity(limit=1000))
gce.register_control("MaxConsiderationUSD", MaxOrderConsideration(limit=50000.0, limit_currency="USD"))

# Validate order concurrently
passed, rejections = gce.validate_order(order, is_new=True, parallel=True)

# Shutdown engine & background threads
gce.shutdown()
```

### 4. Cache Reader Utilities

Inspect engine cache states from memory or `.dat`/`.csv` storage files using `utils/cache_reader.py`:

```python
from utils import CacheReaderManager, OrderCacheReader, PXFeederReader, PositionCacheReader

# Unified manager reading GCE caches
manager = CacheReaderManager(
    order_cache=gce.orders,
    pxfeeder=gce.pxfeeder,
    position_cache=gce.positions,
    price_dat="PriceCache.dat"
)

# Get high-level system summary
summary = manager.get_gce_state_summary()
```

---

## Data Persistence & Recovery

GCE supports multi-layer storage formats:

- **InstrumentStatic.dat**: Binary snapshot of static instrument definitions loaded from `"Instrument Static"` CSV files.
- **PriceCache.dat**: Binary snapshot storage (via `pickle`) for fast startup recovery of prices and FX rates.
- **PriceCache.csv**: Legacy CSV format export/import for compatibility.
- **OrderCache.csv**: Order lifecycle records and statuses (`Live`, `Fill`, `Rejected`, `Cancelled`).
- **PositionsCache.csv**: Real-time position volumes, exposures, and USD values.

---

## Performance Characteristics

Benchmark results on 1,000+ orders validation:

| Metric | Value |
|--------|-------|
| Average Order Validation Time | **0.04 ms – 0.06 ms** |
| Validation Throughput | **15,000 – 22,000+ orders/sec** |
| In-Memory Instrument / FX Lookup | `< 0.001 ms` |
| Background Refresh Overhead | `0 ms` (Runs in background thread) |
| Log Dispatch Overhead | `< 0.005 ms` |

---

## Running Tests

Run all unit and integration test suites:

```bash
# Run unit test suite including DataMgr and PXFeeder
python -m unittest tests/test_datamgr.py tests/test_pxfeeder.py tests/test_cache_readers.py tests/test_max_order_consideration.py tests/test_yfinance_price_cache.py

# Run comprehensive integration test suite
python tests/integration_tests.py

# Run usage demonstration script
python example_usage.py
```

---

## License

Internal Use Only - Trading Systems Team