"""
Global Compliance Engine (GCE) - Risk Management System
Pre-trade order control and compliance validation
"""

__version__ = "0.1.0"
__author__ = "Trading Systems"

from gce.main.engine import GCE, GCEEngine
from gce.main.pxfeeder import PXFeeder
from gce.main.datamgr import DataMgr, InstrumentStatic
from gce.main.distributed import ValidatorNode, DistributedValidationRouter, LoadBalancingStrategy
from gce.main.analytics import RiskAnalytics, RiskReporter, RiskReport

__all__ = [
    "GCE", "GCEEngine", "PXFeeder", "DataMgr", "InstrumentStatic",
    "ValidatorNode", "DistributedValidationRouter", "LoadBalancingStrategy",
    "RiskAnalytics", "RiskReporter", "RiskReport"
]
