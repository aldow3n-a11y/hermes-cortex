#!/usr/bin/env python3
"""
CORTEX Memory Fingerprint

Generates SHA256 content fingerprints for deduplication.
Adds content_hash column to graymatter FTS5 index.

Usage:
    python memory-fingerprint.py              # Backfill all entries
    python memory-fingerprint.py --dry-run    # Show what would happen
    python memory-fingerprint.py --status     # Show current hash coverage
"""

import argparse
import hashlib
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Configuration
HERMES_HOME = Path.home() / ".hermes"
GRAYMATTER_DB = HERMES_HOME / "context" / "stats.db"

# Fingerprint settings
HASH_LENGTH = 16  # First 16 chars of SHA256 (64 bits)


def content_fingerprint(text: str) -> str:
    """
    Generate content fingerprint (hash) for deduplication.
    
    Normalizes:
    - Whitespace (multiple spaces → single space)
    - Dates (YYYY-MM-DD → [DATE])
    - Case (lowercase)
    
    Returns first 16 chars of SHA256 hash.
    """
    if not text:
        return ""
    
    # Normalize
    normalized = text.lower().strip()
    normalized = re.sub(r'\s+', ' ', normalized)  # Collapse whitespace
    normalized = re.sub(r'\d{4}-\d{2}-\d{2}', '[DATE]', normalized)  # Normalize dates
    normalized = re.sub(r'\d{2}:\d{2}:\d{2}', '[TIME]', normalized)  # Normalize times
    
    # Hash
    hash_full = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    return hash_full[:HASH_LENGTH]


def get_db_connection() -> sqlite3.Connection:
    """Get graymatter DB connection."""
    if not GRAYMATTER_DB.exists():
        print(f"❌ Database not found: {GRAYMATTER_DB}")
        sys.exit(1)
    
    conn = sqlite3.connect(str(GRAYMATTER_DB))
    conn.row_factory = sqlite3.Row
    return conn


def check_schema(conn: sqlite3.Connection) -> bool:
    """Check if content_hash column exists."""
    cursor = conn.execute("PRAGMA table_info(fts_index)")
    columns = [row[1] for row in cursor.fetchall()]
    return "content_hash" in columns


def add_content_hash_column(conn: sqlite3.Connection, dry_run: bool = False):
    """Add content_hash column to FTS5 table."""
    # FTS5 doesn't support ALTER TABLE ADD COLUMN directly
    # Need to rebuild the virtual table
    
    print("📝 Adding content_hash column to fts_index...")
    
    if dry_run:
        print("  [DRY RUN] Would add content_hash column")
        return
    
    # Step 1: Create new FTS5 table with content_hash (matching current schema)
    # First, clean up any failed migration
    conn.execute("DROP TABLE IF EXISTS fts_index_new")
    conn.execute("""
        CREATE VIRTUAL TABLE fts_index_new USING fts5(
            skill,
            command,
            content,
            timestamp,
            tier,
            filepath,
            content_hash
        )
    """)
    
    # Step 2: Copy data from old table (without content_hash)
    # Must match column order exactly
    conn.execute("""
        INSERT INTO fts_index_new (
            skill, command, content, timestamp, tier, filepath
        )
        SELECT skill, command, content, timestamp, tier, filepath
        FROM fts_index
    """)
    
    # Step 3: Drop old table
    conn.execute("DROP TABLE fts_index")
    
    # Step 4: Rename new table
    conn.execute("ALTER TABLE fts_index_new RENAME TO fts_index")
    
    # Step 5: FTS5 tables are self-indexing, no additional indexes needed
    # (FTS5 creates its own internal indexes for full-text search)
    
    conn.commit()
    print("✅ content_hash column added")


def backfill_fingerprints(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """
    Backfill content_hash for all entries missing it.
    
    Returns count of updated entries.
    """
    print("\n🔨 Backfilling fingerprints...")
    
    # Find entries without hash
    cursor = conn.execute("""
        SELECT rowid, content FROM fts_index 
        WHERE content_hash IS NULL OR content_hash = ''
        LIMIT 10000
    """)
    
    entries = cursor.fetchall()
    total = len(entries)
    
    if total == 0:
        print("✅ All entries already have fingerprints")
        return 0
    
    print(f"   Found {total} entries without fingerprints")
    
    if dry_run:
        print(f"  [DRY RUN] Would update {total} entries")
        return total
    
    # Update in batches
    batch_size = 100
    updated = 0
    
    for i in range(0, total, batch_size):
        batch = entries[i:i+batch_size]
        
        for row in batch:
            rowid = row[0]
            content = row[1]
            fingerprint = content_fingerprint(content)
            
            conn.execute(
                "UPDATE fts_index SET content_hash = ? WHERE rowid = ?",
                (fingerprint, rowid)
            )
        
        updated += len(batch)
        conn.commit()
        
        # Progress
        pct = (updated / total) * 100
        print(f"   Progress: {updated}/{total} ({pct:.1f}%)")
    
    print(f"✅ Backfilled {updated} fingerprints")
    return updated


def verify_fingerprints(conn: sqlite3.Connection) -> dict:
    """Verify fingerprint uniqueness and coverage."""
    cursor = conn.execute("""
        SELECT 
            COUNT(*) as total,
            COUNT(content_hash) as with_hash,
            COUNT(DISTINCT content_hash) as unique_hashes
        FROM fts_index
    """)
    
    stats = dict(cursor.fetchone())
    
    # Check for collisions
    cursor = conn.execute("""
        SELECT content_hash, COUNT(*) as count
        FROM fts_index
        WHERE content_hash IS NOT NULL
        GROUP BY content_hash
        HAVING COUNT(*) > 1
        LIMIT 10
    """)
    
    collisions = cursor.fetchall()
    
    return {
        **stats,
        "collisions": len(collisions),
        "collision_examples": collisions[:5]
    }


def show_status(conn: sqlite3.Connection):
    """Show current fingerprint coverage."""
    has_column = check_schema(conn)
    
    print("📊 Fingerprint Status\n")
    print(f"Database: {GRAYMATTER_DB}")
    print(f"Hash length: {HASH_LENGTH} chars ({HASH_LENGTH * 4} bits)")
    print()
    
    if not has_column:
        print("❌ content_hash column does not exist")
        print("   Run without --status to add it")
        return
    
    stats = verify_fingerprints(conn)
    
    print(f"Total entries:      {stats['total']:,}")
    print(f"With fingerprints:  {stats['with_hash']:,}")
    print(f"Unique hashes:      {stats['unique_hashes']:,}")
    print(f"Coverage:           {(stats['with_hash']/stats['total']*100):.1f}%")
    print(f"Collisions:         {stats['collisions']}")
    
    if stats['collisions'] > 0:
        print("\n⚠️  Hash collisions detected (same hash, different content):")
        for collision in stats['collision_examples']:
            print(f"   Hash {collision[0]}: {collision[1]} entries")
    
    # Sample fingerprints
    print("\nSample fingerprints:")
    cursor = conn.execute("""
        SELECT content_hash, substr(content, 1, 60) as preview
        FROM fts_index
        WHERE content_hash IS NOT NULL
        LIMIT 5
    """)
    
    for row in cursor.fetchall():
        print(f"   {row[0]} — {row[1]}...")


def main():
    parser = argparse.ArgumentParser(
        description="CORTEX Memory Fingerprint — SHA256 hashing for deduplication"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current fingerprint coverage"
    )
    
    args = parser.parse_args()
    
    print(f"🧠 CORTEX Memory Fingerprint — {datetime.now().isoformat()}\n")
    
    conn = get_db_connection()
    
    if args.status:
        show_status(conn)
    else:
        # Check schema
        has_column = check_schema(conn)
        
        if not has_column:
            add_content_hash_column(conn, dry_run=args.dry_run)
        
        # Backfill
        backfill_fingerprints(conn, dry_run=args.dry_run)
        
        # Verify
        if not args.dry_run:
            print("\n📋 Verification:")
            show_status(conn)
    
    conn.close()


if __name__ == "__main__":
    main()
