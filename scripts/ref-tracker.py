#!/usr/bin/env python3
"""
CORTEX Reference Tracker

Tracks which content exists in which systems (Hermes, graymatter, Obsidian).
Enables intelligent archival and cross-system deduplication.

Usage:
    python ref-tracker.py              # Build/update reference tracking
    python ref-tracker.py --dry-run    # Show what would happen
    python ref-tracker.py --status     # Show reference stats
"""

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Configuration
HERMES_HOME = Path.home() / ".hermes"
GRAYMATTER_DB = HERMES_HOME / "context" / "stats.db"


def get_db_connection() -> sqlite3.Connection:
    """Get graymatter DB connection."""
    if not GRAYMATTER_DB.exists():
        print(f"❌ Database not found: {GRAYMATTER_DB}")
        sys.exit(1)
    
    conn = sqlite3.connect(str(GRAYMATTER_DB))
    conn.row_factory = sqlite3.Row
    return conn


def check_ref_table_exists(conn: sqlite3.Connection) -> bool:
    """Check if content_references table exists."""
    cursor = conn.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='content_references'
    """)
    return cursor.fetchone() is not None


def create_ref_table(conn: sqlite3.Connection, dry_run: bool = False):
    """Create content_references table."""
    print("📝 Creating content_references table...")
    
    if dry_run:
        print("  [DRY RUN] Would create table")
        return
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS content_references (
            content_hash TEXT PRIMARY KEY,
            hermes BOOLEAN DEFAULT FALSE,
            graymatter BOOLEAN DEFAULT FALSE,
            obsidian BOOLEAN DEFAULT FALSE,
            ref_count INTEGER DEFAULT 0,
            first_seen DATETIME,
            last_accessed DATETIME,
            last_updated DATETIME
        )
    """)
    
    conn.commit()
    print("✅ content_references table created")


def sync_references(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """
    Sync reference tracking table with fts_index.
    
    Returns statistics.
    """
    print("\n🔄 Syncing references...")
    
    stats = {
        "total_hashes": 0,
        "new_entries": 0,
        "updated_entries": 0,
        "hermes_refs": 0,
        "graymatter_refs": 0,
        "obsidian_refs": 0
    }
    
    # Get all unique content hashes from fts_index
    cursor = conn.execute("""
        SELECT DISTINCT content_hash, tier, filepath
        FROM fts_index
        WHERE content_hash IS NOT NULL
    """)
    
    entries = cursor.fetchall()
    stats["total_hashes"] = len(entries)
    
    print(f"   Found {stats['total_hashes']} unique content hashes")
    
    if dry_run:
        print(f"  [DRY RUN] Would sync {stats['total_hashes']} entries")
        return stats
    
    now = datetime.now().isoformat()
    
    for row in entries:
        content_hash = row[0]
        tier = row[1]
        filepath = row[2]
        
        # Determine which systems have this content
        has_hermes = filepath and filepath.startswith("/HOME/.hermes/memories/")
        has_graymatter = True  # All entries are in graymatter by definition
        has_obsidian = tier == "T1" and filepath and "/obsidian" in filepath.lower()
        
        # Check if entry exists
        cursor = conn.execute(
            "SELECT * FROM content_references WHERE content_hash = ?",
            (content_hash,)
        )
        existing = cursor.fetchone()
        
        if existing:
            # Update existing entry
            conn.execute("""
                UPDATE content_references 
                SET hermes = ?, graymatter = ?, obsidian = ?,
                    ref_count = ?, last_updated = ?
                WHERE content_hash = ?
            """, (
                has_hermes, has_graymatter, has_obsidian,
                sum([has_hermes, has_graymatter, has_obsidian]),
                now, content_hash
            ))
            stats["updated_entries"] += 1
        else:
            # Insert new entry
            conn.execute("""
                INSERT INTO content_references (
                    content_hash, hermes, graymatter, obsidian,
                    ref_count, first_seen, last_accessed, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                content_hash, has_hermes, has_graymatter, has_obsidian,
                sum([has_hermes, has_graymatter, has_obsidian]),
                now, now, now
            ))
            stats["new_entries"] += 1
        
        # Count by system
        if has_hermes:
            stats["hermes_refs"] += 1
        if has_graymatter:
            stats["graymatter_refs"] += 1
        if has_obsidian:
            stats["obsidian_refs"] += 1
    
    conn.commit()
    print(f"✅ Synced {stats['total_hashes']} entries")
    return stats


def show_status(conn: sqlite3.Connection):
    """Show reference tracking statistics."""
    has_table = check_ref_table_exists(conn)
    
    print("📊 Reference Tracking Status\n")
    print(f"Database: {GRAYMATTER_DB}")
    print()
    
    if not has_table:
        print("❌ content_references table does not exist")
        print("   Run without --status to create it")
        return
    
    # Overall stats
    cursor = conn.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN hermes = 1 THEN 1 ELSE 0 END) as hermes_count,
            SUM(CASE WHEN graymatter = 1 THEN 1 ELSE 0 END) as graymatter_count,
            SUM(CASE WHEN obsidian = 1 THEN 1 ELSE 0 END) as obsidian_count,
            AVG(ref_count) as avg_refs
        FROM content_references
    """)
    
    stats = dict(cursor.fetchone())
    
    print(f"Total tracked:      {stats['total']:,}")
    print(f"In Hermes:          {stats['hermes_count']:,} ({stats['hermes_count']/stats['total']*100:.1f}%)")
    print(f"In graymatter:      {stats['graymatter_count']:,} ({stats['graymatter_count']/stats['total']*100:.1f}%)")
    print(f"In Obsidian:        {stats['obsidian_count']:,} ({stats['obsidian_count']/stats['total']*100:.1f}%)")
    print(f"Average ref count:  {stats['avg_refs']:.2f}")
    
    # Distribution by ref count
    print("\nReference Count Distribution:")
    cursor = conn.execute("""
        SELECT ref_count, COUNT(*) as count
        FROM content_references
        GROUP BY ref_count
        ORDER BY ref_count
    """)
    
    for row in cursor.fetchall():
        ref_count = row[0]
        count = row[1]
        pct = count / stats['total'] * 100
        bar = "█" * int(pct / 2)
        systems = []
        if ref_count >= 1:
            systems.append("1 system")
        if ref_count >= 2:
            systems.append("2 systems")
        if ref_count == 3:
            systems.append("3 systems")
        print(f"  {ref_count} systems: {count:>6,} ({pct:5.1f}%) {bar}")
    
    # Archival candidates (ref_count=1, tier=T4)
    cursor = conn.execute("""
        SELECT COUNT(*) FROM content_references
        WHERE ref_count = 1
    """)
    single_ref = cursor.fetchone()[0]
    
    print(f"\n🗑️  Archival Candidates:")
    print(f"   Single-system refs: {single_ref:,}")
    print(f"   (Review before purging)")
    
    # Sample entries
    print("\nSample entries:")
    cursor = conn.execute("""
        SELECT content_hash, hermes, graymatter, obsidian, ref_count, last_updated
        FROM content_references
        ORDER BY last_updated DESC
        LIMIT 3
    """)
    
    for row in cursor.fetchall():
        systems = []
        if row[1]: systems.append("H")
        if row[2]: systems.append("G")
        if row[3]: systems.append("O")
        
        print(f"   {row[0]} → [{','.join(systems)}] (refs: {row[4]})")


def find_archival_candidates(conn: sqlite3.Connection, max_age_days: int = 7) -> list:
    """
    Find entries that are candidates for archival.
    
    Criteria:
    - ref_count = 1 (only in one system)
    - tier = T4 (logs)
    - older than max_age_days
    """
    cursor = conn.execute("""
        SELECT cr.content_hash, f.tier, f.timestamp, cr.last_updated
        FROM content_references cr
        JOIN fts_index f ON cr.content_hash = f.content_hash
        WHERE cr.ref_count = 1 
          AND f.tier = 'T4'
          AND datetime(cr.last_updated) < datetime('now', ?)
        LIMIT 100
    """, (f"-{max_age_days} days",))
    
    return cursor.fetchall()


def main():
    parser = argparse.ArgumentParser(
        description="CORTEX Reference Tracker — Cross-system content tracking"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show reference tracking status"
    )
    parser.add_argument(
        "--find-archival",
        action="store_true",
        help="Find archival candidates (T4, single-system, old)"
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=7,
        help="Max age in days for archival candidates (default: 7)"
    )
    
    args = parser.parse_args()
    
    print(f"🧠 CORTEX Reference Tracker — {datetime.now().isoformat()}\n")
    
    conn = get_db_connection()
    
    if args.status:
        show_status(conn)
    else:
        # Create table if needed
        has_table = check_ref_table_exists(conn)
        
        if not has_table:
            create_ref_table(conn, dry_run=args.dry_run)
        
        # Sync references
        stats = sync_references(conn, dry_run=args.dry_run)
        
        # Summary
        if not args.dry_run:
            print("\n📋 Summary:")
            print(f"   Total hashes:     {stats['total_hashes']}")
            print(f"   New entries:      {stats['new_entries']}")
            print(f"   Updated entries:  {stats['updated_entries']}")
            print(f"   Hermes refs:      {stats['hermes_refs']}")
            print(f"   graymatter refs:  {stats['graymatter_refs']}")
            print(f"   Obsidian refs:    {stats['obsidian_refs']}")
            
            print("\n📊 Verification:")
            show_status(conn)
        
        # Find archival candidates
        if args.find_archival:
            candidates = find_archival_candidates(conn, args.max_age_days)
            print(f"\n🗑️  Archival Candidates (T4, >{args.max_age_days} days):")
            if candidates:
                print(f"   Found {len(candidates)} candidates")
                for c in candidates[:5]:
                    print(f"   - {c[0]} (tier: {c[1]}, timestamp: {c[2]})")
            else:
                print("   None found")
    
    conn.close()


if __name__ == "__main__":
    main()
