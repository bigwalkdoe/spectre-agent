#!/usr/bin/env python3
"""
Machine Learning Anomaly Detection for Spectre Suite
Detects anomalies in system metrics using various ML algorithms
"""

import os
import sys
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from sklearn.ensemble import IsolationForest
from sklearn.svm import OneClassSVM
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import DBSCAN
from scipy import stats
import joblib
import argparse


def _resolve_dir(env_var, default):
    """Return an existing/writable dir, falling back to a temp location."""
    path = os.environ.get(env_var, default)
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except OSError:
        fallback = os.path.join("/tmp", "ml-anomaly")
        os.makedirs(fallback, exist_ok=True)
        return fallback


ML_LOG_DIR = _resolve_dir("ML_LOG_DIR", "/var/log/ml-anomaly")
ML_DATA_DIR = _resolve_dir("ML_DATA_DIR", "/var/lib/ml-anomaly")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(ML_LOG_DIR, 'anomaly_detection.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def sanitize(obj):
    """Recursively convert numpy types to native Python types for JSON."""
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return sanitize(obj.tolist())
    return obj


class SystemMetricsCollector:
    """Collects system metrics for anomaly detection"""
    
    def __init__(self):
        self.metrics = {}
    
    def collect_cpu_metrics(self):
        """Collect CPU usage metrics"""
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            load_avg = os.getloadavg()
            
            return {
                'cpu_usage_percent': cpu_percent,
                'cpu_count': cpu_count,
                'load_1min': load_avg[0],
                'load_5min': load_avg[1],
                'load_15min': load_avg[2]
            }
        except Exception as e:
            logger.error(f"Error collecting CPU metrics: {e}")
            return {}
    
    def collect_memory_metrics(self):
        """Collect memory usage metrics"""
        try:
            import psutil
            mem = psutil.virtual_memory()
            
            return {
                'memory_usage_percent': mem.percent,
                'memory_available_gb': mem.available / (1024**3),
                'memory_used_gb': mem.used / (1024**3),
                'memory_total_gb': mem.total / (1024**3)
            }
        except Exception as e:
            logger.error(f"Error collecting memory metrics: {e}")
            return {}
    
    def collect_disk_metrics(self):
        """Collect disk usage metrics"""
        try:
            import psutil
            disk = psutil.disk_usage('/')
            
            return {
                'disk_usage_percent': disk.percent,
                'disk_used_gb': disk.used / (1024**3),
                'disk_free_gb': disk.free / (1024**3),
                'disk_total_gb': disk.total / (1024**3)
            }
        except Exception as e:
            logger.error(f"Error collecting disk metrics: {e}")
            return {}
    
    def collect_network_metrics(self):
        """Collect network metrics"""
        try:
            import psutil
            net_io = psutil.net_io_counters()
            
            return {
                'network_bytes_sent': net_io.bytes_sent,
                'network_bytes_recv': net_io.bytes_recv,
                'network_packets_sent': net_io.packets_sent,
                'network_packets_recv': net_io.packets_recv
            }
        except Exception as e:
            logger.error(f"Error collecting network metrics: {e}")
            return {}
    
    def collect_process_metrics(self):
        """Collect process metrics"""
        try:
            import psutil
            processes = list(psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']))
            
            total_processes = len(processes)
            high_cpu_processes = sum(1 for p in processes if p.info['cpu_percent'] and p.info['cpu_percent'] > 80)
            high_mem_processes = sum(1 for p in processes if p.info['memory_percent'] and p.info['memory_percent'] > 80)
            
            return {
                'total_processes': total_processes,
                'high_cpu_processes': high_cpu_processes,
                'high_mem_processes': high_mem_processes
            }
        except Exception as e:
            logger.error(f"Error collecting process metrics: {e}")
            return {}
    
    def collect_all_metrics(self):
        """Collect all system metrics"""
        metrics = {}
        metrics.update(self.collect_cpu_metrics())
        metrics.update(self.collect_memory_metrics())
        metrics.update(self.collect_disk_metrics())
        metrics.update(self.collect_network_metrics())
        metrics.update(self.collect_process_metrics())
        metrics['timestamp'] = datetime.now().isoformat()
        
        return metrics


class AnomalyDetector:
    """Base class for anomaly detection algorithms"""
    
    def __init__(self, model_name):
        self.model_name = model_name
        self.model = None
        self.scaler = StandardScaler()
        self.is_trained = False
        self.model_dir = os.path.join(ML_DATA_DIR, 'models')
        os.makedirs(self.model_dir, exist_ok=True)
    
    def prepare_data(self, metrics_list):
        """Prepare metrics data for ML processing"""
        df = pd.DataFrame(metrics_list)
        
        # Remove non-numeric columns
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        df_numeric = df[numeric_cols].fillna(0)
        
        return df_numeric
    
    def train(self, metrics_list):
        """Train the anomaly detection model"""
        raise NotImplementedError("Subclasses must implement train method")
    
    def detect_anomalies(self, metrics):
        """Detect anomalies in the given metrics"""
        raise NotImplementedError("Subclasses must implement detect_anomalies method")
    
    def save_model(self):
        """Save the trained model"""
        model_path = os.path.join(self.model_dir, f'{self.model_name}.pkl')
        joblib.dump({'model': self.model, 'scaler': self.scaler, 'is_trained': self.is_trained}, model_path)
        logger.info(f"Model saved to {model_path}")
    
    def load_model(self):
        """Load a trained model"""
        model_path = os.path.join(self.model_dir, f'{self.model_name}.pkl')
        if os.path.exists(model_path):
            saved_data = joblib.load(model_path)
            self.model = saved_data['model']
            self.scaler = saved_data['scaler']
            self.is_trained = saved_data['is_trained']
            logger.info(f"Model loaded from {model_path}")
            return True
        return False


class IsolationForestDetector(AnomalyDetector):
    """Anomaly detection using Isolation Forest"""
    
    def __init__(self):
        super().__init__('isolation_forest')
        self.contamination = 0.1  # Expected proportion of outliers
    
    def train(self, metrics_list):
        """Train Isolation Forest model"""
        logger.info("Training Isolation Forest model...")
        
        df = self.prepare_data(metrics_list)
        
        # Scale the data
        X_scaled = self.scaler.fit_transform(df)
        
        # Train model
        self.model = IsolationForest(
            contamination=self.contamination,
            random_state=42,
            n_estimators=100
        )
        self.model.fit(X_scaled)
        
        self.is_trained = True
        self.save_model()
        
        logger.info("Isolation Forest model trained successfully")
    
    def detect_anomalies(self, metrics):
        """Detect anomalies using Isolation Forest"""
        if not self.is_trained:
            logger.warning("Model not trained, cannot detect anomalies")
            return None
        
        # Prepare single metrics entry
        df = self.prepare_data([metrics])
        X_scaled = self.scaler.transform(df)
        
        # Predict
        prediction = self.model.predict(X_scaled)
        anomaly_score = self.model.score_samples(X_scaled)
        
        return {
            'is_anomaly': prediction[0] == -1,
            'anomaly_score': float(anomaly_score[0]),
            'model': 'isolation_forest'
        }


class OneClassSVMDetector(AnomalyDetector):
    """Anomaly detection using One-Class SVM"""
    
    def __init__(self):
        super().__init__('one_class_svm')
        self.nu = 0.1  # Upper bound on the fraction of outliers
    
    def train(self, metrics_list):
        """Train One-Class SVM model"""
        logger.info("Training One-Class SVM model...")
        
        df = self.prepare_data(metrics_list)
        
        # Scale the data
        X_scaled = self.scaler.fit_transform(df)
        
        # Train model
        self.model = OneClassSVM(
            nu=self.nu,
            kernel='rbf',
            gamma='scale'
        )
        self.model.fit(X_scaled)
        
        self.is_trained = True
        self.save_model()
        
        logger.info("One-Class SVM model trained successfully")
    
    def detect_anomalies(self, metrics):
        """Detect anomalies using One-Class SVM"""
        if not self.is_trained:
            logger.warning("Model not trained, cannot detect anomalies")
            return None
        
        # Prepare single metrics entry
        df = self.prepare_data([metrics])
        X_scaled = self.scaler.transform(df)
        
        # Predict
        prediction = self.model.predict(X_scaled)
        
        return {
            'is_anomaly': prediction[0] == -1,
            'model': 'one_class_svm'
        }


class StatisticalAnomalyDetector(AnomalyDetector):
    """Statistical anomaly detection using Z-score"""
    
    def __init__(self):
        super().__init__('statistical')
        self.z_threshold = 3.0
        self.baseline_stats = {}
    
    def train(self, metrics_list):
        """Calculate baseline statistics"""
        logger.info("Calculating baseline statistics...")
        
        df = self.prepare_data(metrics_list)
        
        # Calculate statistics for each metric
        for column in df.columns:
            self.baseline_stats[column] = {
                'mean': df[column].mean(),
                'std': df[column].std(),
                'median': df[column].median(),
                'q1': df[column].quantile(0.25),
                'q3': df[column].quantile(0.75)
            }
        
        self.is_trained = True
        self.save_model()
        
        logger.info("Baseline statistics calculated successfully")
    
    def detect_anomalies(self, metrics):
        """Detect anomalies using Z-score"""
        if not self.is_trained:
            logger.warning("Baseline not calculated, cannot detect anomalies")
            return None
        
        # Prepare single metrics entry
        df = self.prepare_data([metrics])
        
        anomalies = {}
        for column in df.columns:
            if column in self.baseline_stats:
                value = df[column].values[0]
                mean = self.baseline_stats[column]['mean']
                std = self.baseline_stats[column]['std']
                
                if std > 0:
                    z_score = abs((value - mean) / std)
                    if z_score > self.z_threshold:
                        anomalies[column] = {
                            'value': value,
                            'baseline_mean': mean,
                            'z_score': z_score
                        }
        
        return {
            'is_anomaly': len(anomalies) > 0,
            'anomalies': anomalies,
            'model': 'statistical'
        }
    
    def save_model(self):
        """Save baseline statistics"""
        model_path = os.path.join(self.model_dir, f'{self.model_name}.pkl')
        joblib.dump({
            'baseline_stats': self.baseline_stats,
            'is_trained': self.is_trained
        }, model_path)
        logger.info(f"Baseline statistics saved to {model_path}")
    
    def load_model(self):
        """Load baseline statistics"""
        model_path = os.path.join(self.model_dir, f'{self.model_name}.pkl')
        if os.path.exists(model_path):
            saved_data = joblib.load(model_path)
            self.baseline_stats = saved_data['baseline_stats']
            self.is_trained = saved_data['is_trained']
            logger.info(f"Baseline statistics loaded from {model_path}")
            return True
        return False


class EnsembleAnomalyDetector:
    """Ensemble of multiple anomaly detection methods"""
    
    def __init__(self):
        self.detectors = [
            IsolationForestDetector(),
            OneClassSVMDetector(),
            StatisticalAnomalyDetector()
        ]
        self.metrics_history = []
        self.max_history = 1000

    @property
    def is_trained(self):
        return all(d.is_trained for d in self.detectors)

    def load_model(self):
        loaded_any = False
        for d in self.detectors:
            try:
                if d.load_model():
                    loaded_any = True
            except Exception as e:
                logger.error(f"Error loading {d.model_name}: {e}")
        return loaded_any
    
    def train_all(self, metrics_list):
        """Train all detectors"""
        logger.info("Training ensemble of anomaly detectors...")
        
        # Store training data
        self.metrics_history.extend(metrics_list)
        if len(self.metrics_history) > self.max_history:
            self.metrics_history = self.metrics_history[-self.max_history:]
        
        # Train each detector
        for detector in self.detectors:
            try:
                if not detector.is_trained:
                    detector.train(self.metrics_history)
                else:
                    detector.load_model()
            except Exception as e:
                logger.error(f"Error training {detector.model_name}: {e}")
    
    def detect_anomalies(self, metrics):
        """Detect anomalies using ensemble"""
        results = {}
        
        # Add metrics to history
        self.metrics_history.append(metrics)
        if len(self.metrics_history) > self.max_history:
            self.metrics_history = self.metrics_history[-self.max_history:]
        
        # Get predictions from each detector
        anomaly_votes = 0
        for detector in self.detectors:
            try:
                result = detector.detect_anomalies(metrics)
                if result and result.get('is_anomaly'):
                    anomaly_votes += 1
                results[detector.model_name] = result
            except Exception as e:
                logger.error(f"Error in {detector.model_name}: {e}")
        
        # Ensemble decision (majority voting)
        ensemble_decision = anomaly_votes > len(self.detectors) / 2
        
        return {
            'is_anomaly': ensemble_decision,
            'anomaly_votes': anomaly_votes,
            'total_detectors': len(self.detectors),
            'individual_results': results,
            'timestamp': datetime.now().isoformat()
        }


class MetricsStorage:
    """Handles storage and retrieval of metrics data"""
    
    def __init__(self):
        self.storage_dir = os.path.join(ML_DATA_DIR, 'metrics')
        os.makedirs(self.storage_dir, exist_ok=True)
    
    def save_metrics(self, metrics):
        """Save metrics to storage"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = os.path.join(self.storage_dir, f'metrics_{timestamp}.json')
        
        with open(filename, 'w') as f:
            json.dump(metrics, f, indent=2)
    
    def load_recent_metrics(self, count=100):
        """Load recent metrics for training"""
        try:
            # Get most recent metric files
            files = sorted([f for f in os.listdir(self.storage_dir) if f.endswith('.json')], reverse=True)[:count]
            
            metrics_list = []
            for filename in files:
                filepath = os.path.join(self.storage_dir, filename)
                with open(filepath, 'r') as f:
                    metrics_list.append(json.load(f))
            
            return metrics_list
        except Exception as e:
            logger.error(f"Error loading metrics: {e}")
            return []


def main():
    """Main function for anomaly detection"""
    parser = argparse.ArgumentParser(description='ML-based anomaly detection for system metrics')
    parser.add_argument('--mode', choices=['train', 'detect', 'continuous'], default='detect',
                       help='Operation mode: train, detect, or continuous')
    parser.add_argument('--training-samples', type=int, default=100,
                       help='Number of training samples to use')
    parser.add_argument('--detector', choices=['isolation_forest', 'one_class_svm', 'statistical', 'ensemble'],
                        default='ensemble', help='Anomaly detection method')
    parser.add_argument('--output', default=os.path.join(ML_LOG_DIR, 'latest_detection.json'),
                        help='Path to write the anomaly report JSON')
    
    args = parser.parse_args()
    
    # Initialize components
    collector = SystemMetricsCollector()
    storage = MetricsStorage()
    
    # Select detector
    if args.detector == 'ensemble':
        detector = EnsembleAnomalyDetector()
    elif args.detector == 'isolation_forest':
        detector = IsolationForestDetector()
    elif args.detector == 'one_class_svm':
        detector = OneClassSVMDetector()
    else:
        detector = StatisticalAnomalyDetector()
    
    if args.mode == 'train':
        logger.info("Training anomaly detection model...")
        
        # Collect training data
        training_data = []
        for i in range(args.training_samples):
            logger.info(f"Collecting training sample {i+1}/{args.training_samples}")
            metrics = collector.collect_all_metrics()
            storage.save_metrics(metrics)
            training_data.append(metrics)
            
            if i < args.training_samples - 1:
                # Wait between samples to get variation
                import time
                time.sleep(10)
        
        # Train detector
        if isinstance(detector, EnsembleAnomalyDetector):
            detector.train_all(training_data)
        else:
            detector.train(training_data)
        
        logger.info("Training completed successfully")
    
    elif args.mode == 'detect':
        logger.info("Detecting anomalies...")
        
        # Load or train detector
        if not detector.is_trained:
            if not detector.load_model():
                # Load training data and train
                training_data = storage.load_recent_metrics(args.training_samples)
                if len(training_data) >= 10:
                    logger.info("Loading training data and training detector...")
                    if isinstance(detector, EnsembleAnomalyDetector):
                        detector.train_all(training_data)
                    else:
                        detector.train(training_data)
                else:
                    logger.error("Insufficient training data. Collect at least 10 samples first.")
                    return
        
        # Collect current metrics
        current_metrics = collector.collect_all_metrics()
        storage.save_metrics(current_metrics)
        
        # Detect anomalies
        result = detector.detect_anomalies(current_metrics)
        
        # Persist latest report for the fix engine / exporter
        output_path = args.output
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
        except OSError:
            output_path = os.path.join("/tmp", "ml-anomaly", "latest_detection.json")
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
        try:
            with open(output_path, 'w') as f:
                json.dump(sanitize(result), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to persist detection report: {e}")
        
        # Output results
        print(json.dumps(sanitize(result), indent=2))
        
        # Log if anomaly detected
        if result.get('is_anomaly'):
            logger.warning(f"ANOMALY DETECTED: {result}")
            # Could trigger alert here
        else:
            logger.info("No anomalies detected")
    
    elif args.mode == 'continuous':
        logger.info("Starting continuous anomaly detection...")
        
        # Train if needed
        if not detector.is_trained:
            training_data = storage.load_recent_metrics(args.training_samples)
            if len(training_data) >= 10:
                if isinstance(detector, EnsembleAnomalyDetector):
                    detector.train_all(training_data)
                else:
                    detector.train(training_data)
        
        import time
        try:
            while True:
                # Collect metrics
                current_metrics = collector.collect_all_metrics()
                storage.save_metrics(current_metrics)
                
                # Detect anomalies
                result = detector.detect_anomalies(current_metrics)
                
                # Persist latest report for the fix engine / exporter
                try:
                    with open('/var/log/ml-anomaly/latest_detection.json', 'w') as f:
                        json.dump(sanitize(result), f, indent=2)
                except Exception as e:
                    logger.error(f"Failed to persist detection report: {e}")
                
                # Log results
                if result.get('is_anomaly'):
                    logger.warning(f"ANOMALY DETECTED: {result}")
                else:
                    logger.info("System metrics normal")
                
                # Wait before next collection
                time.sleep(60)  # Check every minute
                
        except KeyboardInterrupt:
            logger.info("Continuous monitoring stopped")


if __name__ == '__main__':
    main()
