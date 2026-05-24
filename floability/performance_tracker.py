import time
import os
import json
from pathlib import Path
from datetime import datetime


class NullPerf:
    """No-op performance tracker. Used as a sentinel when no perf object is provided.
    Eliminates 'if perf:' guards at every call site.
    """

    def start_timer(self, *args, **kwargs):
        pass

    def end_timer(self, *args, **kwargs):
        pass


class PerformanceTracker:
    def __init__(self, output_dir, enabled=True):
        self.metrics = {}
        self.timers = {}
        self.enabled = enabled
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        # Initialize with basic system info
        self.metrics["system_info"] = {
            "start_time": datetime.now().isoformat(),
            "hostname": os.uname().nodename,
        }

    def start_timer(self, name):
        """Start a timer with the given name"""
        if not self.enabled:
            return
        self.timers[name] = time.time()

    def end_timer(self, name, description=None):
        """End a timer and store the elapsed time"""
        if not self.enabled or name not in self.timers:
            return

        elapsed = time.time() - self.timers[name]
        timestamp = datetime.now().isoformat()

        if "timers" not in self.metrics:
            self.metrics["timers"] = {}

        self.metrics["timers"][name] = {
            "elapsed_seconds": elapsed,
            "description": description or name,
            "report_time": timestamp,
        }

        # Also print immediately for feedback
        print(f"[floability-perf] {name}: {elapsed:.2f} seconds")

        return elapsed

    def record_metric(
        self, category, name, value, unit=None, description=None, report_time=None
    ):
        """Record a metric value"""
        if not self.enabled:
            return
        if not report_time:
            report_time = datetime.now().isoformat()

        if category not in self.metrics:
            self.metrics[category] = {}

        self.metrics[category][name] = {
            "value": value,
            "unit": unit,
            "description": description or name,
            "report_time": report_time,
        }

        # Also print immediately for feedback
        unit_str = f" {unit}" if unit else ""
        print(f"[floability-perf] {category}.{name}: {value}{unit_str}")

    def measure_file_size(self, path, name=None):
        """Measure the size of a file or directory"""
        if not self.enabled:
            return 0

        path = Path(path)
        if not path.exists():
            return 0

        if path.is_file():
            size_bytes = path.stat().st_size
        else:
            # For directories, sum all file sizes recursively
            size_bytes = sum(f.stat().st_size for f in path.glob("**/*") if f.is_file())

        # Convert to MB for readability
        size_mb = size_bytes / (1024 * 1024)

        metric_name = name or path.name
        self.record_metric(
            "file_sizes", metric_name, size_mb, unit="MB", description=f"Size of {path}"
        )

        return size_mb

    def save_report(self):
        """Save the collected metrics to a JSON file"""
        if not self.enabled:
            return

        # Add end time
        self.metrics["system_info"]["end_time"] = datetime.now().isoformat()

        # Calculate total runtime
        start_time = datetime.fromisoformat(self.metrics["system_info"]["start_time"])
        end_time = datetime.fromisoformat(self.metrics["system_info"]["end_time"])
        total_runtime = (end_time - start_time).total_seconds()

        self.metrics["system_info"]["total_runtime_seconds"] = total_runtime

        # Save to file
        report_file = os.path.join(
            self.output_dir, f"performance_report_{int(time.time())}.json"
        )
        with open(report_file, "w") as f:
            json.dump(self.metrics, f, indent=2)

        print(f"[floability-perf] Performance report saved to: {report_file}")

        # Print summary
        print("\n[floability-perf] PERFORMANCE SUMMARY:")
        print(f"Total runtime: {total_runtime:.2f} seconds")

        if "timers" in self.metrics:
            print("\nTimers:")
            for name, data in self.metrics["timers"].items():
                print(f"  - {name}: {data['elapsed_seconds']:.2f} seconds")

        return report_file
