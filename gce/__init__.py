"""
Global Compliance Engine (GCE) - Risk Management System
Pre-trade order control and compliance validation
"""

__version__ = "0.1.0"
__author__ = "Trading Systems"

from gce.engine import GCE, GCEEngine
from gce.pxfeeder import PXFeeder
from gce.datamgr import DataMgr, InstrumentStatic
from gce.distributed import ValidatorNode, DistributedValidationRouter, LoadBalancingStrategy
from gce.analytics import RiskAnalytics, RiskReporter, RiskReport

__all__ = [
    "GCE", "GCEEngine", "PXFeeder", "DataMgr", "InstrumentStatic",
    "ValidatorNode", "DistributedValidationRouter", "LoadBalancingStrategy",
    "RiskAnalytics", "RiskReporter", "RiskReport"
]
