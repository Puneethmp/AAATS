"""
Interactive CLI to encrypt AAATS credentials into the encrypted vault.

Usage:
    python scripts/setup_secrets.py
    python scripts/setup_secrets.py --show-keys   # list stored key names
    python scripts/setup_secrets.py --rotate      # re-encrypt under new password
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from foundation.secrets_manager import SecretsManager, _ENV_MASTER_KEY


def _prompt_secret(name: str, existing: str = "") -> str:
    prompt = f"  {name}" + (" [keep existing, press Enter to skip]" if existing else "") + ": "
    val = getpass.getpass(prompt)
    return val if val else existing


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="AAATS Secrets Setup")
    parser.add_argument("--show-keys", action="store_true", help="List stored key names")
    parser.add_argument("--rotate", action="store_true", help="Rotate master key")
    args = parser.parse_args()

    print("=" * 60)
    print("  AAATS Encrypted Credentials Setup")
    print("=" * 60)

    master = os.environ.get(_ENV_MASTER_KEY) or getpass.getpass(
        f"\nEnter master password (set as {_ENV_MASTER_KEY} to avoid prompt): "
    )
    os.environ[_ENV_MASTER_KEY] = master

    sm = SecretsManager()

    if args.show_keys:
        try:
            secrets = sm._load()
            if secrets:
                print(f"\nStored keys ({len(secrets)}):")
                for k in sorted(secrets.keys()):
                    print(f"  - {k}")
            else:
                print("\nNo secrets stored yet.")
        except Exception as e:
            print(f"Error reading vault: {e}")
        return

    if args.rotate:
        new_master = getpass.getpass("Enter NEW master password: ")
        confirm = getpass.getpass("Confirm new master password: ")
        if new_master != confirm:
            print("Passwords do not match. Aborting.")
            sys.exit(1)
        sm.rotate(new_master)
        print("Master key rotated successfully.")
        return

    try:
        existing = sm._load()
    except Exception:
        existing = {}

    print("\nEnter credentials (press Enter to keep existing value):\n")
    print("  [Binance Crypto]")
    binance_api = _prompt_secret("BINANCE_API_KEY", existing.get("BINANCE_API_KEY", ""))
    binance_secret = _prompt_secret("BINANCE_SECRET_KEY", existing.get("BINANCE_SECRET_KEY", ""))

    print("\n  [Angel One India]")
    angel_api = _prompt_secret("ANGEL_ONE_API_KEY", existing.get("ANGEL_ONE_API_KEY", ""))
    angel_client = _prompt_secret("ANGEL_ONE_CLIENT_ID", existing.get("ANGEL_ONE_CLIENT_ID", ""))
    angel_pin = _prompt_secret("ANGEL_ONE_PIN", existing.get("ANGEL_ONE_PIN", ""))
    angel_totp = _prompt_secret("ANGEL_ONE_TOTP_SECRET", existing.get("ANGEL_ONE_TOTP_SECRET", ""))

    print("\n  [Telegram Alerts]")
    tg_token = _prompt_secret("TELEGRAM_BOT_TOKEN", existing.get("TELEGRAM_BOT_TOKEN", ""))
    tg_chat = _prompt_secret("TELEGRAM_CHAT_ID", existing.get("TELEGRAM_CHAT_ID", ""))

    secrets = {
        "BINANCE_API_KEY": binance_api,
        "BINANCE_SECRET_KEY": binance_secret,
        "ANGEL_ONE_API_KEY": angel_api,
        "ANGEL_ONE_CLIENT_ID": angel_client,
        "ANGEL_ONE_PIN": angel_pin,
        "ANGEL_ONE_TOTP_SECRET": angel_totp,
        "TELEGRAM_BOT_TOKEN": tg_token,
        "TELEGRAM_CHAT_ID": tg_chat,
    }
    secrets = {k: v for k, v in secrets.items() if v}

    sm.save(secrets)
    print(f"\n✅ {len(secrets)} secrets encrypted and saved.")
    print("   Add AAATS_MASTER_KEY to your environment to decrypt at runtime.")
    print("   Never commit data/secrets.enc to git.")


if __name__ == "__main__":
    main()
