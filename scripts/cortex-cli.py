#!/usr/bin/env python3
"""
CORTEX CLI — Main Command Line Interface

Unified memory management and knowledge management for any environment.
No GPU required. Runs on $5 VPS, Raspberry Pi, old laptops.

Usage:
    cortex status              # Show system status
    cortex search <query>      # Search graymatter
    cortex health-check        # Run health checks
    cortex classify            # Run tier classification
    cortex fingerprint         # Run fingerprinting
    cortex sync                # Full sync pipeline
"""

import argparse
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
HERMES_HOME = Path.home() / ".hermes"
GRAYMATTER_DB = HERMES_HOME / "context" / "stats.db"
CORTEX_VERSION = "0.1.0"
SCRIPTS_DIR = Path(__file__).parent


def get_db_connection() -> sqlite3.Connection:
    """Get graymatter DB connection."""
    if not GRAYMATTER_DB.exists():
        print(f"❌ Database not found: {GRAYMATTER_DB}")
        sys.exit(1)
    
    conn = sqlite3.connect(str(GRAYMATTER_DB))
    conn.row_factory = sqlite3.Row
    return conn


def cmd_status(args):
    """Show system status."""
    print(f"🧠 CORTEX v{CORTEX_VERSION} — {datetime.now().isoformat()}\n")
    
    conn = get_db_connection()
    
    # Total entries
    cursor = conn.execute("SELECT COUNT(*) FROM fts_index")
    total = cursor.fetchone()[0]
    
    # Tier distribution
    cursor = conn.execute("""
        SELECT tier, COUNT(*) as count
        FROM fts_index
        GROUP BY tier
        ORDER BY tier
    """)
    tiers = {row[0]: row[1] for row in cursor.fetchall()}
    
    # Security flagged
    cursor = conn.execute("""
        SELECT COUNT(*) FROM fts_index WHERE security_flagged = 1
    """)
    flagged = cursor.fetchone()[0]
    
    # Fingerprint coverage
    cursor = conn.execute("""
        SELECT COUNT(*) FROM fts_index WHERE content_hash IS NOT NULL
    """)
    fingerprinted = cursor.fetchone()[0]
    
    # DB size
    db_size = GRAYMATTER_DB.stat().st_size / 1024 / 1024
    
    print(f"Database: {GRAYMATTER_DB}")
    print(f"Size: {db_size:.2f} MB")
    print()
    
    print(f"📊 Content Overview:")
    print(f"   Total entries:     {total:,}")
    print(f"   Fingerprinted:     {fingerprinted:,} ({fingerprinted/total*100:.1f}%)")
    print(f"   Security flagged:  {flagged:,} ({flagged/total*100:.2f}%)")
    print()
    
    print(f"🎯 Tier Distribution:")
    for tier in ["T1", "T2", "T3", "T4"]:
        count = tiers.get(tier, 0)
        pct = count / total * 100 if total > 0 else 0
        bar = "█" * int(pct / 2)
        print(f"   {tier}: {count:>6,} ({pct:5.1f}%) {bar}")
    
    # Recent activity
    cursor = conn.execute("""
        SELECT COUNT(*) FROM fts_index
        WHERE datetime(timestamp) > datetime('now', '-24 hours')
    """)
    recent_24h = cursor.fetchone()[0]
    
    cursor = conn.execute("""
        SELECT COUNT(*) FROM fts_index
        WHERE datetime(timestamp) > datetime('now', '-7 days')
    """)
    recent_7d = cursor.fetchone()[0]
    
    print(f"\n📈 Recent Activity:")
    print(f"   Last 24 hours:  {recent_24h:,} entries")
    print(f"   Last 7 days:    {recent_7d:,} entries")
    
    conn.close()


def cmd_search(args):
    """Search graymatter."""
    query = args.query
    limit = args.limit
    tier = args.tier
    
    conn = get_db_connection()
    
    print(f"🔍 Searching for: \"{query}\"")
    if tier:
        print(f"   Tier filter: {tier}")
    print()
    
    # Build query
    if tier:
        sql = """
            SELECT content, tier, timestamp, filepath
            FROM fts_index
            WHERE fts_index MATCH ? AND tier = ?
            LIMIT ?
        """
        params = (query, tier, limit)
    else:
        sql = """
            SELECT content, tier, timestamp, filepath
            FROM fts_index
            WHERE fts_index MATCH ?
            LIMIT ?
        """
        params = (query, limit)
    
    cursor = conn.execute(sql, params)
    results = cursor.fetchall()
    
    if not results:
        print("❌ No results found")
        conn.close()
        return
    
    print(f"✅ Found {len(results)} results\n")
    
    for i, row in enumerate(results, 1):
        content = row[0][:300] + "..." if len(row[0]) > 300 else row[0]
        tier = row[1]
        timestamp = row[2]
        
        print(f"{i}. [{tier}] {timestamp}")
        print(f"   {content}")
        print()
    
    conn.close()


def cmd_health_check(args):
    """Run health checks."""
    print(f"🏥 CORTEX Health Check — {datetime.now().isoformat()}\n")
    
    issues = []
    warnings = []
    
    # Check database exists
    if not GRAYMATTER_DB.exists():
        issues.append("❌ Database not found")
    else:
        db_size = GRAYMATTER_DB.stat().st_size / 1024 / 1024
        print(f"✅ Database: {db_size:.2f} MB")
    
    conn = get_db_connection()
    
    # Check schema
    cursor = conn.execute("PRAGMA table_info(fts_index)")
    columns = [row[1] for row in cursor.fetchall()]
    
    required_columns = ["skill", "command", "content", "timestamp", "tier", "filepath", "content_hash"]
    missing = [c for c in required_columns if c not in columns]
    
    if missing:
        issues.append(f"❌ Missing columns: {', '.join(missing)}")
    else:
        print(f"✅ Schema: All required columns present")
    
    # Check content_hash coverage
    cursor = conn.execute("""
        SELECT COUNT(*) FROM fts_index WHERE content_hash IS NOT NULL
    """)
    fingerprinted = cursor.fetchone()[0]
    
    cursor = conn.execute("SELECT COUNT(*) FROM fts_index")
    total = cursor.fetchone()[0]
    
    coverage = fingerprinted / total * 100 if total > 0 else 0
    
    if coverage < 100:
        warnings.append(f"⚠️  Fingerprint coverage: {coverage:.1f}% ({fingerprinted}/{total})")
    else:
        print(f"✅ Fingerprints: 100% coverage")
    
    # Check tier classification
    cursor = conn.execute("""
        SELECT COUNT(*) FROM fts_index WHERE tier IS NOT NULL AND tier != ''
    """)
    classified = cursor.fetchone()[0]
    
    coverage = classified / total * 100 if total > 0 else 0
    
    if coverage < 100:
        warnings.append(f"⚠️  Tier coverage: {coverage:.1f}% ({classified}/{total})")
    else:
        print(f"✅ Tiers: 100% classified")
    
    # Check security filter
    cursor = conn.execute("""
        SELECT COUNT(*) FROM fts_index WHERE security_flagged = 1
    """)
    flagged = cursor.fetchone()[0]
    
    print(f"✅ Security: {flagged:,} entries flagged ({flagged/total*100:.2f}%)")
    
    # Check reference tracking
    cursor = conn.execute("""
        SELECT name FROM sqlite_master WHERE type='table' AND name='content_references'
    """)
    has_refs = cursor.fetchone() is not None
    
    if has_refs:
        print(f"✅ References: Tracking table exists")
    else:
        warnings.append("⚠️  Reference tracking not initialized")
    
    conn.close()
    
    # Summary
    print()
    if issues:
        print("🔴 Issues:")
        for issue in issues:
            print(f"   {issue}")
    
    if warnings:
        print("🟡 Warnings:")
        for warning in warnings:
            print(f"   {warning}")
    
    if not issues and not warnings:
        print("✅ All checks passed!")
    
    # Return exit code
    if issues:
        sys.exit(1)
    elif warnings and args.strict:
        sys.exit(1)
    else:
        sys.exit(0)


def cmd_classify(args):
    """Run tier classification."""
    print("🎯 Running tier classification...\n")
    
    # Run classifier script
    script = SCRIPTS_DIR / "tier-classifier.py"
    cmd = [sys.executable, str(script)]
    if args.dry_run:
        cmd.append("--dry-run")
    
    subprocess.run(cmd)


def cmd_fingerprint(args):
    """Run fingerprinting."""
    print("🔍 Running fingerprinting...\n")
    
    # Run fingerprint script
    script = SCRIPTS_DIR / "memory-fingerprint.py"
    cmd = [sys.executable, str(script)]
    if args.dry_run:
        cmd.append("--dry-run")
    
    subprocess.run(cmd)


def cmd_sync(args):
    """Run full sync pipeline."""
    print(f"🔄 CORTEX Full Sync — {datetime.now().isoformat()}\n")
    
    steps = [
        ("Fingerprinting", cmd_fingerprint),
        ("Classification", cmd_classify),
        ("Reference Tracking", lambda _: None),  # Placeholder
    ]
    
    for step_name, step_fn in steps:
        print(f"Step {len(steps)}: {step_name}")
        print("=" * 50)
        try:
            step_fn(args)
            print(f"✅ {step_name} complete\n")
        except Exception as e:
            print(f"❌ {step_name} failed: {e}\n")
            if args.strict:
                sys.exit(1)
    
    print("=" * 50)
    print("✅ Sync complete!")


def main():
    parser = argparse.ArgumentParser(
        description=f"CORTEX v{CORTEX_VERSION} — Memory & Knowledge Management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cortex status                    # Show system status
  cortex search "eviction policy"  # Search graymatter
  cortex health-check              # Run health checks
  cortex classify                  # Run tier classification
  cortex sync                      # Full sync pipeline
        """
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version=f"CORTEX {CORTEX_VERSION}"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # status
    p_status = subparsers.add_parser("status", help="Show system status")
    p_status.set_defaults(func=cmd_status)
    
    # search
    p_search = subparsers.add_parser("search", help="Search graymatter")
    p_search.add_argument("query", help="Search query (FTS5 syntax)")
    p_search.add_argument("--limit", type=int, default=10, help="Max results")
    p_search.add_argument("--tier", choices=["T1", "T2", "T3", "T4"], help="Filter by tier")
    p_search.set_defaults(func=cmd_search)
    
    # health-check
    p_health = subparsers.add_parser("health-check", help="Run health checks")
    p_health.add_argument("--strict", action="store_true", help="Fail on warnings")
    p_health.set_defaults(func=cmd_health_check)
    
    # classify
    p_classify = subparsers.add_parser("classify", help="Run tier classification")
    p_classify.add_argument("--dry-run", action="store_true", help="Show what would happen")
    p_classify.set_defaults(func=cmd_classify)
    
    # fingerprint
    p_fingerprint = subparsers.add_parser("fingerprint", help="Run fingerprinting")
    p_fingerprint.add_argument("--dry-run", action="store_true", help="Show what would happen")
    p_fingerprint.set_defaults(func=cmd_fingerprint)
    
    # sync
    p_sync = subparsers.add_parser("sync", help="Run full sync pipeline")
    p_sync.add_argument("--dry-run", action="store_true", help="Show what would happen")
    p_sync.add_argument("--strict", action="store_true", help="Fail on first error")
    p_sync.set_defaults(func=cmd_sync)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    args.func(args)


if __name__ == "__main__":
    main()
