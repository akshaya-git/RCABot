"""
Processors Package.

Provides event processing capabilities:
- AnomalyDetector: AI-powered anomaly detection
- SeverityClassifier: P1-P6 incident classification
"""

from processors.anomaly import AnomalyDetector
from processors.classifier import SeverityClassifier

__all__ = [
    "AnomalyDetector",
    "SeverityClassifier",
]
