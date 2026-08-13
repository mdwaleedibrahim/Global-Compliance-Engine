"""Risk Analytics and Reporting Engine for GCE."""

import json
import csv
import math
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from gce.cache.order_cache import OrderCache, Order, OrderStatus
from gce.cache.position_cache import PositionCache, Position
from gce.cache.price_cache import PriceCache


@dataclass
class RiskReport:
    """Dataclass representing portfolio risk metrics and analytics snapshot."""
    timestamp: str
    total_orders: int
    approved_orders: int
    rejected_orders: int
    approval_rate_pct: float
    total_positions: int
    gross_exposure_usd: float
    net_exposure_usd: float
    long_exposure_usd: float
    short_exposure_usd: float
    var_95_usd: float
    var_99_usd: float
    top_concentrations: List[Dict[str, Any]]
    rejection_breakdown: Dict[str, int]
    trader_breakdown: Dict[str, Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary."""
        return asdict(self)


class RiskAnalytics:
    """Engine for computing portfolio risk metrics, concentration risk, VaR, and rejection analytics."""

    @staticmethod
    def calculate_risk_report(order_cache: OrderCache, position_cache: PositionCache,
                              price_cache: Optional[PriceCache] = None, logger_rejections: Optional[List[str]] = None) -> RiskReport:
        """
        Compute full risk analytics snapshot.
        
        Args:
            order_cache: OrderCache instance
            position_cache: PositionCache instance
            price_cache: Optional PriceCache instance
            logger_rejections: Optional list of rejection strings from logger
            
        Returns:
            RiskReport dataclass instance
        """
        all_orders = list(order_cache.orders.values())
        total_orders = len(all_orders)
        approved_orders = len([o for o in all_orders if o.status == OrderStatus.LIVE or o.status == OrderStatus.FILL or o.status == OrderStatus.PARTIAL_FILL])
        rejected_orders = len([o for o in all_orders if o.status == OrderStatus.REJECTED])
        approval_rate_pct = round((approved_orders / total_orders * 100.0), 2) if total_orders > 0 else 100.0

        # Position metrics
        all_positions = list(position_cache.positions.values())
        total_positions = len(all_positions)

        long_usd = 0.0
        short_usd = 0.0
        position_exposures: List[Dict[str, Any]] = []
        trader_map: Dict[str, Dict[str, Any]] = {}

        for pos in all_positions:
            net_val_usd = pos.net_value_usd() if hasattr(pos, 'net_value_usd') else (pos.buy_open_value - pos.sell_open_value)
            if net_val_usd >= 0:
                long_usd += net_val_usd
            else:
                short_usd += abs(net_val_usd)

            abs_val = abs(net_val_usd)
            position_exposures.append({
                "symbol": pos.symbol,
                "trader": getattr(pos, 'trader', 'UNKNOWN'),
                "net_quantity": pos.net_quantity(),
                "net_value_usd": net_val_usd,
                "abs_exposure_usd": abs_val
            })

            # Trader breakdown
            t_name = getattr(pos, 'trader', 'UNKNOWN') or 'UNKNOWN'
            if t_name not in trader_map:
                trader_map[t_name] = {
                    "trader": t_name,
                    "orders_count": 0,
                    "rejected_count": 0,
                    "gross_exposure_usd": 0.0,
                    "net_exposure_usd": 0.0
                }
            trader_map[t_name]["gross_exposure_usd"] += abs_val
            trader_map[t_name]["net_exposure_usd"] += net_val_usd

        # Include orders in trader breakdown
        for o in all_orders:
            t_name = o.trader or 'UNKNOWN'
            if t_name not in trader_map:
                trader_map[t_name] = {
                    "trader": t_name,
                    "orders_count": 0,
                    "rejected_count": 0,
                    "gross_exposure_usd": 0.0,
                    "net_exposure_usd": 0.0
                }
            trader_map[t_name]["orders_count"] += 1
            if o.status == OrderStatus.REJECTED:
                trader_map[t_name]["rejected_count"] += 1

        gross_usd = long_usd + short_usd
        net_usd = long_usd - short_usd

        # Calculate concentration risk (% of gross exposure)
        for pe in position_exposures:
            pe["pct_of_gross"] = round((pe["abs_exposure_usd"] / gross_usd * 100.0), 2) if gross_usd > 0 else 0.0

        # Sort top concentrations
        top_concentrations = sorted(position_exposures, key=lambda x: x["abs_exposure_usd"], reverse=True)[:5]

        # Calculate Parametric Value at Risk (VaR) assuming daily volatility of 2.0%
        daily_volatility = 0.02
        var_95 = round(gross_usd * daily_volatility * 1.645, 2)  # 95% confidence level Z-score 1.645
        var_99 = round(gross_usd * daily_volatility * 2.326, 2)  # 99% confidence level Z-score 2.326

        # Rejection analytics
        rejection_breakdown: Dict[str, int] = {}
        for o in all_orders:
            if o.status == OrderStatus.REJECTED and o.rejection_reason:
                for reason in o.rejection_reason.split(";"):
                    ctrl_name = reason.split(":")[0].strip() if ":" in reason else "GeneralRejection"
                    rejection_breakdown[ctrl_name] = rejection_breakdown.get(ctrl_name, 0) + 1

        if logger_rejections:
            for rej in logger_rejections:
                ctrl_name = rej.split(":")[0].strip() if ":" in rej else "LoggedRejection"
                rejection_breakdown[ctrl_name] = rejection_breakdown.get(ctrl_name, 0) + 1

        return RiskReport(
            timestamp=datetime.now().isoformat(),
            total_orders=total_orders,
            approved_orders=approved_orders,
            rejected_orders=rejected_orders,
            approval_rate_pct=approval_rate_pct,
            total_positions=total_positions,
            gross_exposure_usd=round(gross_usd, 2),
            net_exposure_usd=round(net_usd, 2),
            long_exposure_usd=round(long_usd, 2),
            short_exposure_usd=round(short_usd, 2),
            var_95_usd=var_95,
            var_99_usd=var_99,
            top_concentrations=top_concentrations,
            rejection_breakdown=rejection_breakdown,
            trader_breakdown=trader_map
        )


class RiskReporter:
    """Renders terminal risk dashboards and exports structured reports (JSON/CSV)."""

    @staticmethod
    def print_risk_dashboard(report: RiskReport):
        """Print ASCII Risk Dashboard to console."""
        print(f"\n{'='*75}")
        print(f"GCE RISK ANALYTICS & PORTFOLIO DASHBOARD")
        print(f"{'='*75}")
        print(f"Timestamp: {report.timestamp}")
        print(f"-"*75)
        print(f"PORTFOLIO EXPOSURE (USD):")
        print(f"  Gross Exposure:  ${report.gross_exposure_usd:,.2f}")
        print(f"  Net Exposure:    ${report.net_exposure_usd:,.2f}")
        print(f"  Long Exposure:   ${report.long_exposure_usd:,.2f}")
        print(f"  Short Exposure:  ${report.short_exposure_usd:,.2f}")
        print(f"-"*75)
        print(f"VALUE AT RISK (ESTIMATED 1-DAY):")
        print(f"  95% Confidence VaR:  ${report.var_95_usd:,.2f}")
        print(f"  99% Confidence VaR:  ${report.var_99_usd:,.2f}")
        print(f"-"*75)
        print(f"ORDER FLOW ANALYTICS:")
        print(f"  Total Orders: {report.total_orders} | Approved: {report.approved_orders} | Rejected: {report.rejected_orders}")
        print(f"  Approval Rate: {report.approval_rate_pct:.2f}%")
        
        if report.rejection_breakdown:
            print(f"\nREJECTION BREAKDOWN BY CONTROL:")
            for ctrl, count in report.rejection_breakdown.items():
                print(f"  - {ctrl}: {count} rejection(s)")

        if report.top_concentrations:
            print(f"\nTOP POSITION CONCENTRATIONS:")
            for item in report.top_concentrations:
                print(f"  - {item['symbol']} ({item['trader']}): ${item['abs_exposure_usd']:,.2f} ({item['pct_of_gross']}%)")
        print(f"{'='*75}\n")

    @staticmethod
    def export_json(report: RiskReport, path: str = "reports/risk_report.json"):
        """Export risk report to JSON file."""
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, indent=2)

    @staticmethod
    def export_csv(report: RiskReport, path: str = "reports/risk_summary.csv"):
        """Export risk summary metrics to CSV file."""
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Metric", "Value"])
            writer.writerow(["Timestamp", report.timestamp])
            writer.writerow(["Total Orders", report.total_orders])
            writer.writerow(["Approved Orders", report.approved_orders])
            writer.writerow(["Rejected Orders", report.rejected_orders])
            writer.writerow(["Approval Rate (%)", report.approval_rate_pct])
            writer.writerow(["Gross Exposure (USD)", report.gross_exposure_usd])
            writer.writerow(["Net Exposure (USD)", report.net_exposure_usd])
            writer.writerow(["Long Exposure (USD)", report.long_exposure_usd])
            writer.writerow(["Short Exposure (USD)", report.short_exposure_usd])
            writer.writerow(["95% VaR (USD)", report.var_95_usd])
            writer.writerow(["99% VaR (USD)", report.var_99_usd])
