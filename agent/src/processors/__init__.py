"""
Processors Package.

Provides event processing capabilities:
- AnomalyDetector: AI-powered anomaly detection
- SeverityClassifier: P1-P6 incident classification
"""

from .anomaly import AnomalyDetector
from .classifier import SeverityClassifier

__all__ = [
    "AnomalyDetector",
    "SeverityClassifier",
]
