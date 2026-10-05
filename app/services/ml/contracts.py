"""FIRRIS model choices, shared by request validation and execution."""
from typing import Literal

ClassifierType = Literal["random_forest", "xgboost", "svm", "cart", "gradient_boosting", "neural_network"]
CLASSIFIERS = ("random_forest", "xgboost", "svm", "cart", "gradient_boosting", "neural_network")
