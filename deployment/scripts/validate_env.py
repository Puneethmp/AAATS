#!/usr/bin/env python3
"""
AAATS Environment Validation Script
Validates all required environment variables and configuration before deployment
"""

import os
import sys
from pathlib import Path


def validate_env():
    """Validate environment configuration"""
    errors = []
    warnings = []
    
    print("=" * 50)
    print("AAATS Environment Validation")
    print("=" * 50)
    print()
    
    # Check .env file exists
    env_file = Path(".env")
    if not env_file.exists():
        errors.append(".env file not found - copy config/.env.example to .env")
        print("✗ .env file: NOT FOUND")
    else:
        print("✓ .env file: FOUND")
    
    # Required environment variables
    required_vars = {
        # System
        "SYSTEM__TRADING_MODE": "paper",
        "SYSTEM__LOG_LEVEL": "INFO",
        
        # US Market
        "US__ALPACA_API_KEY": None,
        "US__ALPACA_SECRET_KEY": None,
        "US__ALPACA_BASE_URL": "https://paper-api.alpaca.markets",
        
        # India Market
        "INDIA__ANGEL_API_KEY": None,
        "INDIA__ANGEL_CLIENT_ID": None,
        "INDIA__ANGEL_PIN": None,
        "INDIA__ANGEL_TOTP_SECRET": None,
        
        # Alerts
        "ALERTS__TELEGRAM_BOT_TOKEN": None,
        "ALERTS__TELEGRAM_CHAT_ID": None,
    }
    
    print()
    print("Checking required environment variables:")
    print("-" * 50)
    
    for var, default in required_vars.items():
        value = os.getenv(var)
        if not value:
            if default:
                warnings.append(f"{var} not set, will use default: {default}")
                print(f"⚠ {var}: USING DEFAULT ({default})")
            else:
                errors.append(f"{var} is required but not set")
                print(f"✗ {var}: NOT SET")
        else:
            # Mask sensitive values
            if any(x in var.lower() for x in ["key", "secret", "token", "pin"]):
                display_value = value[:4] + "..." + value[-4:] if len(value) > 8 else "***"
            else:
                display_value = value
            print(f"✓ {var}: {display_value}")
    
    # Validate trading mode
    print()
    print("Validating trading mode:")
    print("-" * 50)
    trading_mode = os.getenv("SYSTEM__TRADING_MODE", "paper")
    if trading_mode != "paper":
        errors.append(f"SYSTEM__TRADING_MODE must be 'paper', got '{trading_mode}'")
        print(f"✗ Trading mode: {trading_mode} (MUST BE 'paper')")
    else:
        print(f"✓ Trading mode: {trading_mode}")
    
    # Check Python version
    print()
    print("Checking Python version:")
    print("-" * 50)
    py_version = sys.version_info
    if py_version.major < 3 or (py_version.major == 3 and py_version.minor < 11):
        errors.append(f"Python 3.11+ required, got {py_version.major}.{py_version.minor}")
        print(f"✗ Python version: {py_version.major}.{py_version.minor}.{py_version.micro}")
    else:
        print(f"✓ Python version: {py_version.major}.{py_version.minor}.{py_version.micro}")
    
    # Check required directories
    print()
    print("Checking required directories:")
    print("-" * 50)
    required_dirs = ["logs", "data", "data/state", "data/checkpoints"]
    for dir_path in required_dirs:
        path = Path(dir_path)
        if not path.exists():
            warnings.append(f"Directory {dir_path} will be created")
            print(f"⚠ {dir_path}: WILL BE CREATED")
            path.mkdir(parents=True, exist_ok=True)
        else:
            print(f"✓ {dir_path}: EXISTS")
    
    # Summary
    print()
    print("=" * 50)
    print("VALIDATION SUMMARY")
    print("=" * 50)
    
    if errors:
        print(f"\n✗ FAILED with {len(errors)} error(s):")
        for error in errors:
            print(f"  - {error}")
    
    if warnings:
        print(f"\n⚠ {len(warnings)} warning(s):")
        for warning in warnings:
            print(f"  - {warning}")
    
    if not errors:
        print("\n✓ VALIDATION PASSED")
        print("\nReady for deployment!")
        return 0
    else:
        print("\n✗ VALIDATION FAILED")
        print("\nFix the errors above before deploying.")
        return 1


if __name__ == "__main__":
    sys.exit(validate_env())
