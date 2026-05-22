"""
AAATS Fix Script — 2026-05-08
Fixes:
  1. paper_trades.db schema initialization (CRITICAL)
  2. Start aaats-metrics container
  3. Diagnose C3 altcoin reversion silence
  4. Report health_check.py status
"""

import paramiko
import json
import sys
import time

import os
HOST = os.environ.get("AAATS_SSH_HOST", "100.95.126.39")
USER = os.environ.get("AAATS_SSH_USER", "aaats")
PASS = os.environ.get("AAATS_SSH_PASSWORD")
if not PASS:
    raise SystemExit(
        "AAATS_SSH_PASSWORD env var not set. "
        "Copy .env.example to .env, fill in the password, and re-run."
    )

def ssh_run(client, cmd, timeout=30):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return out, err

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

def main():
    print("Connecting to Contabo via Tailscale...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(HOST, username=USER, password=PASS, timeout=15)
    except Exception as e:
        print(f"[FAIL] Cannot connect: {e}")
        sys.exit(1)
    print("[OK] Connected.")

    # ─────────────────────────────────────────────────────────────
    # 1. FIND DB MOUNT PATH
    # ─────────────────────────────────────────────────────────────
    section("1. DB MOUNT INSPECTION")
    out, err = ssh_run(client, """
docker inspect aaats-paper-crypto | python3 -c "
import json, sys
d = json.load(sys.stdin)[0]
mounts = d.get('Mounts', [])
for m in mounts:
    print(m.get('Type','?'), m.get('Source','?'), '->', m.get('Destination','?'))
if not mounts:
    print('NO MOUNTS FOUND')
"
""")
    print(out or err or "(no output)")

    # ─────────────────────────────────────────────────────────────
    # 2. FIND THE ACTUAL DB FILE
    # ─────────────────────────────────────────────────────────────
    section("2. LOCATE paper_trades.db")
    out, err = ssh_run(client,
        "docker exec aaats-paper-crypto find / -name '*.db' 2>/dev/null | grep -v proc | head -20"
    )
    print(out or err or "(none found)")
    db_path = None
    if out:
        for line in out.splitlines():
            if "paper_trade" in line or "trade" in line or "aaats" in line:
                db_path = line.strip()
                break
        if not db_path:
            db_path = out.splitlines()[0].strip()
    print(f"\n→ Using DB path: {db_path}")

    # ─────────────────────────────────────────────────────────────
    # 3. CHECK SCHEMA & INITIALIZE IF EMPTY
    # ─────────────────────────────────────────────────────────────
    section("3. SCHEMA CHECK & INIT")

    # Try Python init first
    out, err = ssh_run(client, """
docker exec aaats-paper-crypto python3 -c "
import sys, os
# Try standard init paths
tried = []
for mod in ['foundation.database', 'database', 'db', 'models']:
    try:
        m = __import__(mod, fromlist=['init_db'])
        if hasattr(m, 'init_db'):
            m.init_db()
            print(f'SUCCESS: {mod}.init_db() ran')
            sys.exit(0)
    except Exception as e:
        tried.append(f'{mod}: {e}')
print('No init_db found. Tried:')
for t in tried:
    print(' ', t)
" 2>&1
""")
    print(out or "(no output)")

    if "SUCCESS" not in out:
        print("\n→ Python init failed. Checking if db_path usable for direct SQLite init...")
        if db_path:
            init_sql = """CREATE TABLE IF NOT EXISTS paper_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  price REAL NOT NULL,
  quantity REAL NOT NULL,
  confidence REAL DEFAULT 0.0,
  strategy TEXT,
  regime TEXT,
  pnl REAL DEFAULT 0.0,
  fees REAL DEFAULT 0.0,
  notes TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  entry_price REAL NOT NULL,
  quantity REAL NOT NULL,
  entry_time TEXT NOT NULL,
  strategy TEXT,
  status TEXT DEFAULT 'open',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS performance_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT NOT NULL,
  capital REAL NOT NULL,
  total_pnl REAL DEFAULT 0.0,
  trade_count INTEGER DEFAULT 0,
  win_rate REAL DEFAULT 0.0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);"""
            cmd = f'docker exec aaats-paper-crypto sqlite3 {db_path} "{init_sql.replace(chr(10), " ").replace(chr(34), chr(39))}"'
            # Use a heredoc instead
            out2, err2 = ssh_run(client, f"""
docker exec aaats-paper-crypto python3 -c "
import sqlite3
db = '{db_path}'
conn = sqlite3.connect(db)
c = conn.cursor()
c.executescript('''
CREATE TABLE IF NOT EXISTS paper_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  price REAL NOT NULL,
  quantity REAL NOT NULL,
  confidence REAL DEFAULT 0.0,
  strategy TEXT,
  regime TEXT,
  pnl REAL DEFAULT 0.0,
  fees REAL DEFAULT 0.0,
  notes TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  entry_price REAL NOT NULL,
  quantity REAL NOT NULL,
  entry_time TEXT NOT NULL,
  strategy TEXT,
  status TEXT DEFAULT 'open',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS performance_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT NOT NULL,
  capital REAL NOT NULL,
  total_pnl REAL DEFAULT 0.0,
  trade_count INTEGER DEFAULT 0,
  win_rate REAL DEFAULT 0.0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
''')
conn.commit()
conn.close()
tables = [r[0] for r in sqlite3.connect(db).execute(\\\"SELECT name FROM sqlite_master WHERE type='table'\\\").fetchall()]
print('Tables created:', tables)
" 2>&1
""")
            print(out2 or err2 or "(no output)")
        else:
            # No DB file found — create it at a default path
            print("→ No existing DB. Creating at /home/aaats/aaats/data/paper_trades.db")
            out3, err3 = ssh_run(client, """
docker exec aaats-paper-crypto python3 -c "
import sqlite3, os
os.makedirs('/home/aaats/aaats/data', exist_ok=True)
db = '/home/aaats/aaats/data/paper_trades.db'
conn = sqlite3.connect(db)
conn.executescript('''
CREATE TABLE IF NOT EXISTS paper_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  price REAL NOT NULL,
  quantity REAL NOT NULL,
  confidence REAL DEFAULT 0.0,
  strategy TEXT,
  regime TEXT,
  pnl REAL DEFAULT 0.0,
  fees REAL DEFAULT 0.0,
  notes TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  entry_price REAL NOT NULL,
  quantity REAL NOT NULL,
  entry_time TEXT NOT NULL,
  strategy TEXT,
  status TEXT DEFAULT open,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
''')
conn.commit()
tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
print('Tables:', tables)
conn.close()
" 2>&1
""")
            print(out3 or err3 or "(no output)")

    # Final verification
    print("\n→ VERIFYING schema now:")
    if db_path:
        vout, _ = ssh_run(client, f"""
docker exec aaats-paper-crypto python3 -c "
import sqlite3
conn = sqlite3.connect('{db_path}')
rows = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
print('Tables in DB:', [r[0] for r in rows])
conn.close()
" 2>&1
""")
        print(vout or "(could not verify)")

    # ─────────────────────────────────────────────────────────────
    # 4. START aaats-metrics
    # ─────────────────────────────────────────────────────────────
    section("4. START aaats-metrics")
    out, err = ssh_run(client, "docker ps -a --filter name=aaats-metrics --format '{{.Names}} {{.Status}}'")
    print(f"Current state: {out or '(not found)'}")

    if out and "Up" not in out:
        start_out, start_err = ssh_run(client, "docker start aaats-metrics")
        print(f"Start result: {start_out or start_err}")
        time.sleep(3)
        check_out, _ = ssh_run(client, "docker ps --filter name=aaats-metrics --format '{{.Names}} {{.Status}}'")
        print(f"Post-start state: {check_out or '(not running)'}")
    elif "Up" in out:
        print("Already running.")

    # Port check
    port_out, _ = ssh_run(client, "curl -s -o /dev/null -w '%{http_code}' http://localhost:8001/metrics --max-time 3 || echo 'NO_RESPONSE'")
    print(f"Port 8001 response: {port_out}")

    # ─────────────────────────────────────────────────────────────
    # 5. DIAGNOSE C3 SILENCE
    # ─────────────────────────────────────────────────────────────
    section("5. C3 ALTCOIN REVERSION — LAST 50 LOG LINES")
    out, err = ssh_run(client,
        "docker logs aaats-paper-crypto --tail 200 2>&1 | grep -i -E '(C3|revers|altcoin|spread|zscore|mean_rev)' | tail -50"
    )
    print(out or "(no C3-related log lines found in last 200 lines)")

    # Also show last regime + signal lines
    section("5b. RECENT SIGNAL OUTPUT (last 30 lines with signal/regime)")
    out2, _ = ssh_run(client,
        "docker logs aaats-paper-crypto --tail 300 2>&1 | grep -i -E '(SIGNAL|REGIME|HOLD|BUY|SELL|confidence|strategy)' | tail -30"
    )
    print(out2 or "(no signal lines found)")

    # ─────────────────────────────────────────────────────────────
    # 6. HEALTH CHECK STATUS
    # ─────────────────────────────────────────────────────────────
    section("6. HEALTH CHECK SCRIPT STATUS")
    out, _ = ssh_run(client,
        "docker exec aaats-paper-crypto find / -name 'health_check.py' 2>/dev/null | head -5"
    )
    print(f"health_check.py locations: {out or '(not found anywhere)'}")

    hc_config, _ = ssh_run(client,
        "docker inspect aaats-paper-crypto | python3 -c \""
        "import json,sys; d=json.load(sys.stdin)[0]; "
        "hc=d.get('Config',{}).get('Healthcheck',{}); "
        "print(json.dumps(hc, indent=2))\""
    )
    print(f"Docker healthcheck config:\n{hc_config}")

    # ─────────────────────────────────────────────────────────────
    # 7. CONTAINER SUMMARY
    # ─────────────────────────────────────────────────────────────
    section("7. ALL CONTAINERS FINAL STATE")
    out, _ = ssh_run(client, "docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'")
    print(out)

    client.close()
    print("\n[DONE] Script complete.")

if __name__ == "__main__":
    main()
