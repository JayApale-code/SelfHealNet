# ml_engine/__init__.py - Machine Learning Fault Prediction Engine

import os
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Any
import logging
from datetime import datetime, timedelta
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import precision_score, recall_score, f1_score, roc_auc_score, confusion_matrix
from sklearn.ensemble import RandomForestClassifier
import joblib
try:
    from ..config import config
except ImportError:
    from config import config

logger = logging.getLogger(__name__)


class FaultDatasetGenerator:
    """Generate synthetic network fault dataset"""
    
    def __init__(self, n_samples: int = 10000, random_state: int = 42):
        self.n_samples = n_samples
        self.random_state = random_state
        np.random.seed(random_state)
    
    def generate(self) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Generate synthetic network fault dataset.
        
        Features:
        - Historical latency (mean, std, p95)
        - Historical packet loss (mean, std)
        - Bandwidth utilization (current, trend)
        - Jitter (mean, spike rate)
        - Error rate trend
        - Network topology degree
        - Time of day (cyclic)
        - Recent anomalies count
        
        Target:
        - Fault (binary: 0=no fault, 1=fault)
        
        Returns:
            Tuple of (feature DataFrame, target Series)
        """
        np.random.seed(self.random_state)
        data = []
        labels = []
        
        for i in range(self.n_samples):
            # Normal behavior (70% of data)
            if np.random.random() < 0.7:
                # Latency features
                latency_mean = np.random.normal(30, 5)  # 30ms mean
                latency_std = np.random.normal(2, 0.5)
                latency_p95 = latency_mean + latency_std * 2
                
                # Packet loss features
                packet_loss_mean = np.random.uniform(0, 0.1)  # 0-0.1%
                packet_loss_std = packet_loss_mean / 5
                
                # Bandwidth features
                bandwidth_util = np.random.uniform(20, 70)  # 20-70% utilization
                bandwidth_trend = np.random.uniform(-2, 2)
                
                # Jitter
                jitter_mean = np.random.uniform(1, 5)
                jitter_spike_rate = np.random.uniform(0, 0.05)
                
                # Error rate
                error_rate_trend = np.random.uniform(-1, 1)
                
                # Topology
                node_degree = np.random.randint(1, 20)
                
                # Time of day (0-23 hours)
                time_of_day = np.random.uniform(0, 24)
                
                # Recent anomalies
                recent_anomalies = np.random.poisson(0.5)
                
                fault = 0
            
            # Fault behavior (30% of data)
            else:
                # Select fault type randomly
                fault_type = np.random.choice([
                    "link_failure",
                    "congestion",
                    "high_jitter",
                    "high_error_rate",
                    "anomaly"
                ])
                
                if fault_type == "link_failure":
                    latency_mean = np.random.normal(100, 20)
                    latency_std = np.random.normal(15, 5)
                    packet_loss_mean = np.random.uniform(2, 10)
                    packet_loss_std = packet_loss_mean / 3
                    bandwidth_util = np.random.uniform(10, 30)
                    error_rate_trend = np.random.uniform(5, 15)
                    jitter_spike_rate = np.random.uniform(0.2, 0.5)
                
                elif fault_type == "congestion":
                    bandwidth_util = np.random.uniform(85, 99)
                    bandwidth_trend = np.random.uniform(2, 10)
                    latency_mean = np.random.normal(50, 10)
                    packet_loss_mean = np.random.uniform(0.5, 2)
                    jitter_mean = np.random.uniform(8, 15)
                    recent_anomalies = np.random.poisson(3)
                
                elif fault_type == "high_jitter":
                    jitter_mean = np.random.uniform(20, 50)
                    jitter_spike_rate = np.random.uniform(0.3, 0.7)
                    latency_std = np.random.normal(10, 3)
                    packet_loss_mean = np.random.uniform(0.1, 1)
                
                elif fault_type == "high_error_rate":
                    error_rate_trend = np.random.uniform(5, 20)
                    packet_loss_mean = np.random.uniform(1, 5)
                    latency_mean = np.random.normal(45, 15)
                
                else:  # anomaly
                    # Random anomalous values
                    latency_mean = np.random.choice([10, 200])  # Bimodal
                    bandwidth_util = np.random.choice([15, 95])
                    jitter_mean = np.random.uniform(10, 30)
                    recent_anomalies = np.random.poisson(2)
                
                latency_p95 = latency_mean + (latency_std if 'latency_std' in locals() else np.random.normal(8, 2)) * 2
                latency_std = latency_std if 'latency_std' in locals() else np.random.normal(8, 2)
                packet_loss_std = packet_loss_std if 'packet_loss_std' in locals() else packet_loss_mean / 3
                bandwidth_trend = bandwidth_trend if 'bandwidth_trend' in locals() else np.random.uniform(-1, 3)
                jitter_mean = jitter_mean if 'jitter_mean' in locals() else np.random.uniform(5, 15)
                jitter_spike_rate = jitter_spike_rate if 'jitter_spike_rate' in locals() else np.random.uniform(0.05, 0.3)
                error_rate_trend = error_rate_trend if 'error_rate_trend' in locals() else np.random.uniform(-2, 5)
                node_degree = np.random.randint(1, 20)
                time_of_day = np.random.uniform(0, 24)
                recent_anomalies = recent_anomalies if 'recent_anomalies' in locals() else np.random.poisson(1)
                
                fault = 1
            
            # Compile feature vector
            feature_vector = [
                latency_mean,
                latency_std,
                latency_p95,
                packet_loss_mean,
                packet_loss_std,
                bandwidth_util,
                bandwidth_trend,
                jitter_mean,
                jitter_spike_rate,
                error_rate_trend,
                node_degree,
                time_of_day,
                recent_anomalies
            ]
            
            data.append(feature_vector)
            labels.append(fault)
        
        feature_names = [
            'latency_mean',
            'latency_std',
            'latency_p95',
            'packet_loss_mean',
            'packet_loss_std',
            'bandwidth_util',
            'bandwidth_trend',
            'jitter_mean',
            'jitter_spike_rate',
            'error_rate_trend',
            'node_degree',
            'time_of_day',
            'recent_anomalies'
        ]
        
        df = pd.DataFrame(data, columns=feature_names)
        y = pd.Series(labels, name='fault')
        
        logger.info(f"Generated dataset: {df.shape[0]} samples, {df.shape[1]} features")
        logger.info(f"Fault distribution: {y.value_counts().to_dict()}")
        
        return df, y


class FaultPredictionModel:
    """Random Forest-based fault prediction model."""
    
    def __init__(self, model_version: str = "1.0.0"):
        self.model_version = model_version
        self.model = None
        self.scaler = StandardScaler()
        self.preprocessor = None
        self.selector = None
        self.feature_names = None
        self.metrics = {}
    
    def train(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        test_size: float = 0.2,
        random_state: int = 42
    ) -> Dict[str, float]:
        """
        Train XGBoost model with proper train/test split.
        
        Args:
            X: Feature DataFrame
            y: Target Series
            test_size: Test set proportion
            random_state: Random seed
            
        Returns:
            Dictionary of evaluation metrics
        """
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y,
            test_size=test_size,
            random_state=random_state,
            stratify=y
        )
        
        logger.info(f"Train set: {X_train.shape[0]} samples")
        logger.info(f"Test set: {X_test.shape[0]} samples")
        
        # Scale features
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)
        
        # Store feature names
        self.feature_names = X.columns.tolist()
        
        # Train Random Forest model as the initial production model
        self.model = RandomForestClassifier(
            n_estimators=200,
            max_depth=12,
            min_samples_split=2,
            min_samples_leaf=1,
            random_state=random_state,
            class_weight='balanced'
        )
        
        self.model.fit(X_train_scaled, y_train)
        
        # Evaluate on test set
        y_pred = self.model.predict(X_test_scaled)
        y_pred_proba = self.model.predict_proba(X_test_scaled)[:, 1]
        
        # Calculate metrics
        self.metrics = {
            "precision": float(precision_score(y_test, y_pred)),
            "recall": float(recall_score(y_test, y_pred)),
            "f1": float(f1_score(y_test, y_pred)),
            "roc_auc": float(roc_auc_score(y_test, y_pred_proba)),
            "accuracy": float((y_pred == y_test).mean())
        }
        
        logger.info(f"Model metrics: {self.metrics}")
        
        return self.metrics
    
    def predict(self, X: pd.DataFrame) -> Dict[str, Any]:
        """
        Predict fault probability for new data.
        
        Args:
            X: Feature DataFrame
            
        Returns:
            Dictionary with predictions and probabilities
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        
        if self.preprocessor is not None:
            processed = self.preprocessor.transform(X)
            model_input = self.selector.transform(processed) if self.selector is not None else processed
        else:
            model_input = self.scaler.transform(X)
        predictions = self.model.predict(model_input)
        probabilities = self.model.predict_proba(model_input)
        
        return {
            "predictions": predictions.tolist(),
            "fault_probability": probabilities[:, 1].tolist(),
            "confidence": np.max(probabilities, axis=1).tolist()
        }
    
    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance from model"""
        if self.model is None:
            return {}
        
        importance_dict = dict(zip(
            self.feature_names,
            self.model.feature_importances_
        ))
        
        return dict(sorted(
            importance_dict.items(),
            key=lambda x: x[1],
            reverse=True
        ))
    
    def save(self, path: str):
        """Save model to disk"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        model_package = {
            "model": self.model,
            "scaler": self.scaler,
            "feature_names": self.feature_names,
            "metrics": self.metrics,
            "version": self.model_version,
            "saved_at": datetime.utcnow().isoformat()
        }
        
        joblib.dump(model_package, path)
        logger.info(f"Model saved to {path}")
    
    @classmethod
    def load(cls, path: str) -> 'FaultPredictionModel':
        """Load model from disk"""
        model_package = joblib.load(path)
        
        instance = cls(model_version=model_package.get("version", "1.0.0"))
        instance.model = model_package["model"]
        if "preprocessor" in model_package:
            instance.preprocessor = model_package["preprocessor"]
            instance.selector = model_package.get("selector")
            instance.feature_names = model_package.get("feature_columns", [])
        else:
            instance.scaler = model_package["scaler"]
            instance.feature_names = model_package["feature_names"]
        instance.metrics = model_package["metrics"]
        
        logger.info(f"Model loaded from {path}")
        return instance


# Global model instance
_model = None


def get_fault_prediction_model() -> FaultPredictionModel:
    """Get or create global model instance"""
    global _model
    if _model is None:
        if os.path.exists(config.MODEL_PATH):
            _model = FaultPredictionModel.load(config.MODEL_PATH)
        else:
            logger.warning(f"Model not found at {config.MODEL_PATH}")
            _model = FaultPredictionModel()
    return _model


def train_fault_prediction_model(save: bool = True) -> Dict[str, Any]:
    """
    Train a new fault prediction model.
    
    Args:
        save: Whether to save model to disk
        
    Returns:
        Training results and metrics
    """
    global _model
    
    # Generate dataset
    generator = FaultDatasetGenerator(n_samples=10000)
    X, y = generator.generate()
    
    # Train model
    model = FaultPredictionModel()
    metrics = model.train(X, y)
    
    # Save model
    if save:
        model.save(config.LEGACY_MODEL_PATH)
    
    # Update global instance
    _model = model
    
    return {
        "status": "success",
        "version": model.model_version,
        "metrics": metrics,
        "feature_importance": model.get_feature_importance(),
        "saved_path": config.LEGACY_MODEL_PATH if save else None
    }
