#!/usr/bin/env python3
"""
CORTEX Session-End Hook

Triggers automatically when a Hermes session completes.
Processes new memory entries through the CORTEX pipeline in real-time.

Installation:
    Add to ~/.hermes/config.yaml hooks:
    
    hooks:
      session_end:
        - python /HOME/workspace/cortex/scripts/session-end-hook.py

Usage:
    python session-end-hook.py              # Run on current session
    python session-end-hook.py --session-id <id>  # Run on specific session
    python session-end-hook.py --dry-run    # Show what would happen
"""

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
HERMES_HOME = Path.home() / ".hermes"
GRAYMATTER_DB = HERMES_HOME / "context" / "stats.db"
CORTEX_SCRIPTS_DIR = Path(__file__).parent
HERMES_CONFIG = HERMES_HOME / "config.yaml"


def get_db_connection() -> sqlite3.Connection:
    """Get graymatter DB connection."""
    if not GRAYMATTER_DB.exists():
        print(f"❌ Database not found: {GRAYMATTER_DB}")
        sys.exit(1)
    
    conn = sqlite3.connect(str(GRAYMATTER_DB))
    conn.row_factory = sqlite3.Row
    return conn


def get_latest_session_id(conn: sqlite3.Connection) -> str:
    """Get the most recent session identifier from filepath."""
    # Extract session info from filepath (e.g., /HOME/.hermes/memories/2026-04-08.md)
    cursor = conn.execute("""
        SELECT DISTINCT filepath
        FROM fts_index
        ORDER BY timestamp DESC
        LIMIT 1
    """)
    row = cursor.fetchone()
    return row[0] if row else None


def get_new_entries_since(conn: sqlite3.Connection, since: datetime, limit: int = 1000) -> list:
    """Get entries created since a given timestamp."""
    cursor = conn.execute("""
        SELECT rowid, filepath, content, tier, content_hash, timestamp
        FROM fts_index
        WHERE datetime(timestamp) > datetime(?)
        ORDER BY timestamp DESC
        LIMIT ?
    """, (since.isoformat(), limit))
    
    return cursor.fetchall()


def get_unprocessed_entries(conn: sqlite3.Connection, limit: int = 1000) -> list:
    """Get entries that haven't been processed (no tier or hash)."""
    cursor = conn.execute("""
        SELECT rowid, filepath, content, timestamp
        FROM fts_index
        WHERE tier IS NULL OR tier = '' OR content_hash IS NULL
        ORDER BY timestamp DESC
        LIMIT ?
    """, (limit,))
    
    return cursor.fetchall()


def run_fingerprint(filepath_pattern: str = None, dry_run: bool = False) -> int:
    """Run fingerprinting on new entries."""
    print("\n🔍 Running fingerprinting...")
    
    script = CORTEX_SCRIPTS_DIR / "memory-fingerprint.py"
    cmd = [sys.executable, str(script)]
    
    if dry_run:
        cmd.append("--dry-run")
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        # Parse output for count
        if "Backfilled" in result.stdout:
            for line in result.stdout.split("\n"):
                if "Backfilled" in line:
                    print(f"   {line.strip()}")
                    return int(line.split()[1])
        print("   ✅ Fingerprinting complete")
        return 0
    else:
        print(f"   ❌ Fingerprinting failed: {result.stderr[:200]}")
        return -1


def run_classification(filepath_pattern: str = None, dry_run: bool = False) -> int:
    """Run tier classification on new entries."""
    print("\n🎯 Running tier classification...")
    
    script = CORTEX_SCRIPTS_DIR / "tier-classifier.py"
    cmd = [sys.executable, str(script)]
    
    if dry_run:
        cmd.append("--dry-run")
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        # Parse output for counts
        for line in result.stdout.split("\n"):
            if any(f"   {tier}:" in line for tier in ["T1", "T2", "T3", "T4"]):
                print(f"   {line.strip()}")
        print("   ✅ Classification complete")
        return 0
    else:
        print(f"   ❌ Classification failed: {result.stderr[:200]}")
        return -1


def run_reference_sync(dry_run: bool = False) -> int:
    """Run reference tracking sync."""
    print("\n🔄 Running reference sync...")
    
    script = CORTEX_SCRIPTS_DIR / "ref-tracker.py"
    cmd = [sys.executable, str(script)]
    
    if dry_run:
        cmd.append("--dry-run")
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print("   ✅ Reference sync complete")
        return 0
    else:
        print(f"   ❌ Reference sync failed: {result.stderr[:200]}")
        return -1


def generate_summary(conn: sqlite3.Connection, filepath_pattern: str) -> dict:
    """Generate a summary of what was processed."""
    # Use filepath pattern instead of session_id
    cursor = conn.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN tier = 'T1' THEN 1 ELSE 0 END) as t1_count,
            SUM(CASE WHEN tier = 'T2' THEN 1 ELSE 0 END) as t2_count,
            SUM(CASE WHEN tier = 'T3' THEN 1 ELSE 0 END) as t3_count,
            SUM(CASE WHEN tier = 'T4' THEN 1 ELSE 0 END) as t4_count,
            SUM(CASE WHEN security_flagged = 1 THEN 1 ELSE 0 END) as flagged_count
        FROM fts_index
        WHERE filepath LIKE ?
    """, (f"%{filepath_pattern}%",) if filepath_pattern else ("%",))
    
    return dict(cursor.fetchone())


def process_session(session_id: str, dry_run: bool = False) -> dict:
    """Process a single session through the CORTEX pipeline."""
    print(f"\n🧠 Processing session: {session_id}")
    print("=" * 60)
    
    conn = get_db_connection()
    
    results = {
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
        "fingerprinted": 0,
        "classified": 0,
        "references_synced": 0,
        "summary": {}
    }
    
    # Step 1: Fingerprint
    results["fingerprinted"] = run_fingerprint(session_id, dry_run)
    
    # Step 2: Classify
    results["classified"] = run_classification(session_id, dry_run)
    
    # Step 3: Sync references
    results["references_synced"] = run_reference_sync(dry_run)
    
    # Generate summary
    results["summary"] = generate_summary(conn, session_id)
    
    conn.close()
    
    # Print summary
    print("\n" + "=" * 60)
    print(f"📊 Session Summary: {session_id}")
    print(f"   Total entries:    {results['summary'].get('total', 0)}")
    print(f"   T1 (Principles):  {results['summary'].get('t1_count', 0)}")
    print(f"   T2 (Projects):    {results['summary'].get('t2_count', 0)}")
    print(f"   T3 (Knowledge):   {results['summary'].get('t3_count', 0)}")
    print(f"   T4 (Logs):        {results['summary'].get('t4_count', 0)}")
    print(f"   Security flagged: {results['summary'].get('flagged_count', 0)}")
    
    return results


def install_hook(dry_run: bool = False):
    """Install the session-end hook in Hermes config."""
    print("📦 Installing session-end hook in Hermes config...\n")
    
    if not HERMES_CONFIG.exists():
        print(f"❌ Hermes config not found: {HERMES_CONFIG}")
        print("   Please create it first with:")
        print(f"   mkdir -p {HERMES_HOME}")
        sys.exit(1)
    
    # Read current config
    with open(HERMES_CONFIG, "r") as f:
        content = f.read()
    
    # Check if hook already exists
    if "session-end-hook.py" in content:
        print("✅ Hook already installed")
        return
    
    # Add hook configuration
    hook_config = """
hooks:
  session_end:
    - python /HOME/workspace/cortex/scripts/session-end-hook.py
"""
    
    if dry_run:
        print("  [DRY RUN] Would add to config.yaml:")
        print(hook_config)
        return
    
    # Append to config
    with open(HERMES_CONFIG, "a") as f:
        f.write(hook_config)
    
    print("✅ Hook installed successfully")
    print(f"\n   Added to: {HERMES_CONFIG}")
    print("\n   The hook will now run automatically after every Hermes session.")


def main():
    parser = argparse.ArgumentParser(
        description="CORTEX Session-End Hook — Real-time memory processing"
    )
    parser.add_argument(
        "--session-id",
        type=str,
        help="Process a specific session (default: latest)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes"
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Install hook in Hermes config"
    )
    parser.add_argument(
        "--since-hours",
        type=int,
        default=1,
        help="Process entries from the last N hours (default: 1)"
    )
    
    args = parser.parse_args()
    
    print(f"🧠 CORTEX Session-End Hook — {datetime.now().isoformat()}\n")
    
    if args.install:
        install_hook(args.dry_run)
        return
    
    conn = get_db_connection()
    
    # Get session ID
    session_id = args.session_id or get_latest_session_id(conn)
    
    if not session_id:
        print("❌ No session found to process")
        conn.close()
        return
    
    # Process the session
    results = process_session(session_id, args.dry_run)
    
    # If not dry run, save results
    if not args.dry_run:
        # Save to processing log
        log_dir = HERMES_HOME / "context" / "processing_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / f"session-{session_id[:8]}.json"
        with open(log_file, "w") as f:
            json.dump(results, f, indent=2)
        
        print(f"\n💾 Results saved to: {log_file}")
    
    conn.close()
    
    # Exit with appropriate code
    if any(v < 0 for k, v in results.items() if isinstance(v, int)):
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
