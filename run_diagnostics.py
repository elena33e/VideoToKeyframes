from gui.app import launch_gui
from extraction.performance_monitor import PerformanceMonitor


if __name__ == "__main__":
    launch_gui(monitor_factory=PerformanceMonitor)