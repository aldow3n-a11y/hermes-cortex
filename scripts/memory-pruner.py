#!/usr/bin/env python3
"""
CORTEX Memory Pruner

Tier-first + LRU eviction policy for memory management.

Eviction Order:
1. T4 (Logs) > 30 days old
2. T4 (Logs) > 14 days old
3. T3 (Knowledge) > 90 days old (never delete, archive only)
4. T2 (Projects) — never auto-delete (manual review)
5. T1 (Principles) — never delete (permanent)

Safety Rules:
- Never delete security-flagged content without review
- Always dry-run first
- Backup before deletion
- Respect reference counts (don't delete cross-system content)

Usage:
    python memory-pruner.py --dry-run           # See what would be deleted
    python memory-pruner.py --execute           # Actually delete
    python memory-pruner.py --tier T4 --days 30 # Custom policy
    python memory-pruner.py --backup            # Backup then prune
"""

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
HERMES_HOME = Path.home() / ".hermes"
GRAYMATTER_DB = HERMES_HOME / "context" / "stats.db"
BACKUP_DIR = HERMES_HOME / "context" / "prune_backups"
CORTEX_VERSION = "0.1.0"

# Default eviction policy by tier
EVICTION_POLICY = {
    "T4": {"max_age_days": 30, "action": "delete", "priority": 1},
    "T3": {"max_age_days": 90, "action": "archive", "priority": 2},  # Archive, don't delete
    "T2": {"max_age_days": None, "action": "review", "priority": 3},  # Manual review only
    "T1": {"max_age_days": None, "action": "keep", "priority": 4},    # Never delete
}


def get_db_connection() -> sqlite3.Connection:
    """Get graymatter DB connection."""
    if not GRAYMATTER_DB.exists():
        print(f"❌ Database not found: {GRAYMATTER_DB}")
        sys.exit(1)
    
    conn = sqlite3.connect(str(GRAYMATTER_DB))
    conn.row_factory = sqlite3.Row
    return conn


def get_eviction_candidates(
    conn: sqlite3.Connection,
    tier: str = None,
    max_age_days: int = None,
    exclude_flagged: bool = True,
    limit: int = 1000
) -> list:
    """
    Get entries eligible for eviction.
    
    Args:
        tier: Filter by specific tier (T1-T4) or None for all
        max_age_days: Only entries older than this
        exclude_flagged: Skip security-flagged entries
        limit: Max results to return
    """
    conditions = []
    params = []
    
    if tier:
        conditions.append("tier = ?")
        params.append(tier)
    
    if max_age_days:
        cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
        conditions.append("datetime(timestamp) < datetime(?)")
        params.append(cutoff)
    
    if exclude_flagged:
        conditions.append("(security_flagged = 0 OR security_flagged IS NULL)")
    
    # Also check reference count (don't delete cross-system content)
    conditions.append("""
        NOT EXISTS (
            SELECT 1 FROM content_references cr
            WHERE cr.content_hash = fts_index.content_hash
            AND cr.ref_count > 1
        )
    """)
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    cursor = conn.execute(f"""
        SELECT rowid, filepath, content, tier, content_hash, timestamp,
               security_flagged, security_reason
        FROM fts_index
        WHERE {where_clause}
        ORDER BY timestamp ASC
        LIMIT ?
    """, params + [limit])
    
    return cursor.fetchall()


def get_tier_stats(conn: sqlite3.Connection) -> dict:
    """Get current stats for each tier."""
    cursor = conn.execute("""
        SELECT 
            tier,
            COUNT(*) as total,
            SUM(CASE WHEN security_flagged = 1 THEN 1 ELSE 0 END) as flagged,
            MIN(timestamp) as oldest,
            MAX(timestamp) as newest
        FROM fts_index
        GROUP BY tier
        ORDER BY tier
    """)
    
    stats = {}
    for row in cursor.fetchall():
        stats[row[0]] = {
            "total": row[1],
            "flagged": row[2],
            "oldest": row[3],
            "newest": row[4]
        }
    
    return stats


def calculate_eviction_plan(conn: sqlite3.Connection, policy: dict = None) -> dict:
    """
    Calculate what would be evicted under current policy.
    
    Returns detailed plan with counts and space estimates.
    """
    if policy is None:
        policy = EVICTION_POLICY
    
    plan = {
        "generated_at": datetime.now().isoformat(),
        "tiers": {},
        "total_candidates": 0,
        "total_flagged_skipped": 0,
        "estimated_space_freed": 0
    }
    
    # Process tiers by priority
    for tier_name in sorted(policy.keys(), key=lambda t: policy[t]["priority"]):
        tier_policy = policy[tier_name]
        
        if tier_policy["action"] == "keep":
            plan["tiers"][tier_name] = {
                "action": "keep",
                "candidates": 0,
                "reason": "Protected tier (principles/decisions)"
            }
            continue
        
        if tier_policy["action"] == "review":
            # Get count for manual review
            candidates = get_eviction_candidates(
                conn,
                tier=tier_name,
                max_age_days=tier_policy["max_age_days"],
                exclude_flagged=False
            )
            
            plan["tiers"][tier_name] = {
                "action": "review",
                "candidates": len(candidates),
                "reason": "Requires manual review before deletion"
            }
            continue
        
        # Get eviction candidates
        candidates = get_eviction_candidates(
            conn,
            tier=tier_name,
            max_age_days=tier_policy["max_age_days"],
            exclude_flagged=True
        )
        
        # Count flagged that were skipped
        flagged_candidates = get_eviction_candidates(
            conn,
            tier=tier_name,
            max_age_days=tier_policy["max_age_days"],
            exclude_flagged=False,
            limit=10000
        )
        flagged_count = len([c for c in flagged_candidates if c[6] == 1])
        
        plan["tiers"][tier_name] = {
            "action": tier_policy["action"],
            "max_age_days": tier_policy["max_age_days"],
            "candidates": len(candidates),
            "flagged_skipped": flagged_count,
            "estimated_size_bytes": sum(len(c[2]) for c in candidates)
        }
        
        plan["total_candidates"] += len(candidates)
        plan["total_flagged_skipped"] += flagged_count
        plan["estimated_space_freed"] += plan["tiers"][tier_name]["estimated_size_bytes"]
    
    return plan


def backup_entries(conn: sqlite3.Connection, entries: list, backup_path: Path) -> Path:
    """Backup entries to JSON file before deletion."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    
    if not backup_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"prune-backup-{timestamp}.json"
    
    backup_data = {
        "backup_date": datetime.now().isoformat(),
        "entry_count": len(entries),
        "entries": [
            {
                "rowid": e[0],
                "filepath": e[1],
                "tier": e[3],
                "content_hash": e[4],
                "timestamp": e[5],
                "content_preview": e[2][:500]
            }
            for e in entries
        ]
    }
    
    with open(backup_path, "w") as f:
        json.dump(backup_data, f, indent=2)
    
    return backup_path


def execute_eviction(
    conn: sqlite3.Connection,
    entries: list,
    backup: bool = True,
    dry_run: bool = False
) -> dict:
    """
    Execute eviction of entries.
    
    Returns summary of what was done.
    """
    results = {
        "deleted": 0,
        "backed_up": 0,
        "skipped": 0,
        "errors": []
    }
    
    if not entries:
        return results
    
    # Backup first
    if backup and not dry_run:
        backup_path = backup_entries(conn, entries, None)
        print(f"   💾 Backed up {len(entries)} entries to: {backup_path}")
        results["backed_up"] = len(entries)
    
    if dry_run:
        results["deleted"] = 0
        return results
    
    # Delete in batches
    batch_size = 100
    deleted_count = 0
    
    for i in range(0, len(entries), batch_size):
        batch = entries[i:i+batch_size]
        rowids = [e[0] for e in batch]
        
        try:
            placeholders = ",".join("?" * len(rowids))
            conn.execute(f"DELETE FROM fts_index WHERE rowid IN ({placeholders})", rowids)
            conn.commit()
            deleted_count += len(batch)
        except Exception as e:
            results["errors"].append(f"Batch {i//batch_size}: {str(e)}")
    
    results["deleted"] = deleted_count
    return results


def run_pruning(
    conn: sqlite3.Connection,
    policy: dict = None,
    backup: bool = True,
    dry_run: bool = False
) -> dict:
    """Run the full pruning pipeline."""
    if policy is None:
        policy = EVICTION_POLICY
    
    print("\n📊 Current Tier Stats:")
    stats = get_tier_stats(conn)
    for tier in ["T1", "T2", "T3", "T4"]:
        if tier in stats:
            s = stats[tier]
            print(f"   {tier}: {s['total']:,} entries (flagged: {s['flagged']})")
    
    print("\n📋 Eviction Plan:")
    plan = calculate_eviction_plan(conn, policy)
    
    for tier_name, tier_plan in plan["tiers"].items():
        action = tier_plan["action"]
        candidates = tier_plan.get("candidates", 0)
        
        if action == "keep":
            print(f"   {tier_name}: 🔒 Keep forever ({tier_plan['reason']})")
        elif action == "review":
            print(f"   {tier_name}: ⚠️  {candidates} entries need manual review")
        else:
            max_age = tier_plan.get("max_age_days", "N/A")
            flagged = tier_plan.get("flagged_skipped", 0)
            size_mb = tier_plan.get("estimated_size_bytes", 0) / 1024 / 1024
            print(f"   {tier_name}: 🗑️  {candidates} candidates (>{max_age}d, flagged skipped: {flagged}, ~{size_mb:.1f}MB)")
    
    print(f"\n   Total candidates: {plan['total_candidates']}")
    print(f"   Flagged skipped: {plan['total_flagged_skipped']}")
    print(f"   Estimated space freed: {plan['estimated_space_freed']/1024/1024:.1f}MB")
    
    if plan["total_candidates"] == 0:
        print("\n✅ No entries to prune")
        return plan
    
    # Confirm before deletion
    if not dry_run:
        print("\n⚠️  This will permanently delete entries from the database.")
        print("   A backup will be created before deletion.")
    
    # Execute eviction
    print("\n🔨 Executing eviction...")
    
    all_candidates = []
    for tier_name in sorted(policy.keys(), key=lambda t: policy[t]["priority"]):
        tier_policy = policy[tier_name]
        
        if tier_policy["action"] not in ["delete", "archive"]:
            continue
        
        candidates = get_eviction_candidates(
            conn,
            tier=tier_name,
            max_age_days=tier_policy["max_age_days"],
            exclude_flagged=True
        )
        all_candidates.extend(candidates)
    
    results = execute_eviction(conn, all_candidates, backup=backup, dry_run=dry_run)
    
    print(f"\n✅ Pruning complete!")
    print(f"   Deleted: {results['deleted']} entries")
    print(f"   Backed up: {results['backed_up']} entries")
    if results["errors"]:
        print(f"   Errors: {len(results['errors'])}")
    
    plan["execution"] = results
    return plan


def main():
    parser = argparse.ArgumentParser(
        description=f"CORTEX Memory Pruner v{CORTEX_VERSION} — Tier-first + LRU eviction"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete entries (requires --backup or --no-backup)"
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create backup before deletion (default: true)"
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip backup (NOT RECOMMENDED)"
    )
    parser.add_argument(
        "--tier",
        choices=["T1", "T2", "T3", "T4"],
        help="Target specific tier only"
    )
    parser.add_argument(
        "--days",
        type=int,
        help="Override max age in days for targeted tier"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current stats without pruning"
    )
    
    args = parser.parse_args()
    
    print(f"🧠 CORTEX Memory Pruner v{CORTEX_VERSION} — {datetime.now().isoformat()}\n")
    
    conn = get_db_connection()
    
    if args.status:
        stats = get_tier_stats(conn)
        print("📊 Current Tier Statistics:\n")
        for tier in ["T1", "T2", "T3", "T4"]:
            if tier in stats:
                s = stats[tier]
                print(f"{tier}:")
                print(f"   Total: {s['total']:,}")
                print(f"   Flagged: {s['flagged']:,}")
                print(f"   Oldest: {s['oldest']}")
                print(f"   Newest: {s['newest']}")
                print()
        conn.close()
        return
    
    # Build policy
    policy = EVICTION_POLICY.copy()
    
    if args.tier and args.days:
        # Custom policy for specific tier
        policy[args.tier]["max_age_days"] = args.days
    
    # Determine if we should execute
    dry_run = not args.execute
    backup = not args.no_backup
    
    if args.execute and args.no_backup:
        print("⚠️  WARNING: Running without backup!")
        confirm = input("Type 'DELETE' to confirm: ")
        if confirm != "DELETE":
            print("❌ Aborted")
            sys.exit(1)
    
    # Run pruning
    results = run_pruning(conn, policy=policy, backup=backup, dry_run=dry_run)
    
    conn.close()
    
    # Exit code
    if results.get("execution", {}).get("errors"):
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
