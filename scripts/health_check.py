"""
Lightweight health check script for AAATS.

Validates system health and operational readiness.
Suitable for cron jobs and monitoring systems.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from foundation.health_monitor import HealthMonitor
from foundation.logger import get_logger
from monitoring.heartbeat_monitor import get_last_heartbeat
from monitoring.stale_data_detector import check_data_freshness

_log = get_logger("scripts", "health_check")


def check_process_locks() -> dict:
    """Check if trading processes are running."""
    lock_dir = Path("data/locks")
    
    if not lock_dir.exists():
        return {"status": "OK", "message": "No locks directory"}
    
    locks = list(lock_dir.glob("*.lock"))
    active_locks = []
    
    for lock_file in locks:
        try:
            data = lock_file.read_text().strip()
            pid, timestamp = data.split(",")
            age = datetime.now().timestamp() - float(timestamp)
            
            active_locks.append({
                "name": lock_file.stem,
                "pid": int(pid),
                "age_seconds": int(age),
            })
        except Exception:
            pass
    
    return {
        "status": "OK" if active_locks else "WARNING",
        "message": f"{len(active_locks)} active processes",
        "locks": active_locks,
    }


def check_heartbeats() -> dict:
    """Check recent heartbeats from trading processes."""
    markets = ["us", "india", "crypto"]
    heartbeats = {}
    all_ok = True
    
    for market in markets:
        hb = get_last_heartbeat(market)
        if hb:
            age = datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(
                hb.timestamp
            ).timestamp()
            
            is_stale = age > 300  # 5 minutes
            heartbeats[market] = {
                "status": hb.status,
                "age_seconds": int(age),
                "stale": is_stale,
                "cycle_count": hb.cycle_count,
            }
            
            if is_stale or hb.status == "ERROR":
                all_ok = False
        else:
            heartbeats[market] = {"status": "NO_HEARTBEAT", "stale": True}
            all_ok = False
    
    return {
        "status": "OK" if all_ok else "WARNING",
        "message": "All heartbeats fresh" if all_ok else "Stale or missing heartbeats",
        "heartbeats": heartbeats,
    }


def check_data_freshness_all() -> dict:
    """Check data freshness for all markets."""
    markets = ["us", "india", "crypto"]
    freshness = {}
    all_ok = True
    
    for market in markets:
        is_fresh = check_data_freshness(market, max_age_seconds=600)
        freshness[market] = {"fresh": is_fresh}
        if not is_fresh:
            all_ok = False
    
    return {
        "status": "OK" if all_ok else "WARNING",
        "message": "All data fresh" if all_ok else "Stale data detected",
        "freshness": freshness,
    }


def check_disk_space() -> dict:
    """Check available disk space."""
    import shutil
    
    free_bytes = shutil.disk_usage(".").free
    free_gb = free_bytes / (1024**3)
    
    status = "OK" if free_gb > 5.0 else "CRITICAL"
    
    return {
        "status": status,
        "message": f"{free_gb:.1f} GB free",
        "free_gb": round(free_gb, 2),
    }


def check_memory() -> dict:
    """Check system memory usage."""
    try:
        import psutil
        mem = psutil.virtual_memory()
        
        status = "OK" if mem.percent < 80 else "WARNING"
        
        return {
            "status": status,
            "message": f"{mem.percent:.1f}% used",
            "percent_used": round(mem.percent, 1),
        }
    except ImportError:
        return {
            "status": "UNKNOWN",
            "message": "psutil not available",
        }


def check_checkpoints() -> dict:
    """Check if recent checkpoints exist."""
    checkpoint_dir = Path("data/checkpoints")
    
    if not checkpoint_dir.exists():
        return {"status": "WARNING", "message": "No checkpoints directory"}
    
    markets = ["us", "india", "crypto"]
    checkpoints = {}
    
    for market in markets:
        latest = checkpoint_dir / f"{market}_latest.json"
        if latest.exists():
            age = datetime.now().timestamp() - latest.stat().st_mtime
            checkpoints[market] = {
                "exists": True,
                "age_seconds": int(age),
            }
        else:
            checkpoints[market] = {"exists": False}
    
    return {
        "status": "OK",
        "message": f"{sum(1 for c in checkpoints.values() if c.get('exists'))} checkpoints found",
        "checkpoints": checkpoints,
    }


def run_health_check(verbose: bool = False) -> dict:
    """
    Run comprehensive health check.
    
    Args:
        verbose: Include detailed information
    
    Returns:
        Dict with health check results
    """
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "process_locks": check_process_locks(),
            "heartbeats": check_heartbeats(),
            "data_freshness": check_data_freshness_all(),
            "disk_space": check_disk_space(),
            "memory": check_memory(),
            "checkpoints": check_checkpoints(),
        },
    }
    
    # Determine overall status
    statuses = [check["status"] for check in results["checks"].values()]
    
    if "CRITICAL" in statuses:
        results["overall_status"] = "CRITICAL"
    elif "WARNING" in statuses:
        results["overall_status"] = "WARNING"
    else:
        results["overall_status"] = "OK"
    
    return results


def main():
    """Main entry point for health check script."""
    import argparse
    
    parser = argparse.ArgumentParser(description="AAATS Health Check")
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON"
    )
    parser.add_argument(
        "--exit-code", "-e",
        action="store_true",
        help="Exit with non-zero code on WARNING or CRITICAL"
    )
    
    args = parser.parse_args()
    
    # Run health check
    results = run_health_check(verbose=args.verbose)
    
    # Output results
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"AAATS Health Check - {results['overall_status']}")
        print(f"Timestamp: {results['timestamp']}")
        print()
        
        for check_name, check_result in results["checks"].items():
            status = check_result["status"]
            message = check_result.get("message", "")
            
            status_symbol = {
                "OK": "✓",
                "WARNING": "⚠",
                "CRITICAL": "✗",
                "UNKNOWN": "?",
            }.get(status, "?")
            
            print(f"{status_symbol} {check_name}: {status} - {message}")
            
            if args.verbose and len(check_result) > 2:
                for key, value in check_result.items():
                    if key not in ("status", "message"):
                        print(f"  {key}: {value}")
    
    # Exit with appropriate code
    if args.exit_code:
        if results["overall_status"] == "CRITICAL":
            sys.exit(2)
        elif results["overall_status"] == "WARNING":
            sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    main()
