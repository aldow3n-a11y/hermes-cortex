#!/usr/bin/env python3
"""
CORTEX Tier Classifier

Classifies content into T1/T2/T3/T4 tiers based on keywords and heuristics.
Includes security filter to block credential-like content from permanent storage.

Usage:
    python tier-classifier.py              # Classify all entries
    python tier-classifier.py --dry-run    # Show what would happen
    python tier-classifier.py --status     # Show current tier distribution
"""

import argparse
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Configuration
HERMES_HOME = Path.home() / ".hermes"
GRAYMATTER_DB = HERMES_HOME / "context" / "stats.db"

# Tier keywords (weighted by importance)
T1_KEYWORDS = [
    "decided", "principle", "rule", "policy", "security", "boundary",
    "never", "always", "must", "critical", "core", "fundamental",
    "identity", "preference", "boundary", "requirement", "constraint"
]

T2_KEYWORDS = [
    "project", "task", "milestone", "deadline", "deliverable", "sprint",
    "phase", "in progress", "working on", "building", "implementing",
    "deploying", "launching", "q1", "q2", "q3", "q4", "roadmap"
]

T3_KEYWORDS = [
    "how to", "workflow", "guide", "tutorial", "learned", "discovered",
    "figured out", "solution", "workaround", "configuration", "setup",
    "installed", "configured", "steps", "process", "method"
]

T4_KEYWORDS = [
    "output", "result", "debug", "error", "trace", "log", "command",
    "executed", "ran", "tested", "queried", "fetched", "retrieved",
    "response", "request", "api call", "curl", "exit code"
]

# Security patterns (block from Obsidian) - OPTIONAL
# Set SECURITY_FILTER_ENABLED = False to disable (recommended for local-only setups)
SECURITY_FILTER_ENABLED = False  # Set True to enable credential filtering

SECURITY_PATTERNS = [
    r"password\s*[=:]\s*\S+",
    r"passwd\s*[=:]\s*\S+",
    r"secret\s*[=:]\s*\S+",
    r"token\s*[=:]\s*\S+",
    r"api[_-]?key\s*[=:]\s*\S+",
    r"apikey\s*[=:]\s*\S+",
    r"credential",
    r"private[_-]?key",
    r"auth_token",
    r"bearer\s+\S+",
    r"aws[_-]?secret",
    r"client[_-]?secret",
]


def classify_tier(content: str) -> tuple:
    """
    Classify content into T1/T2/T3/T4.
    
    Returns: (tier, confidence_score, matched_keywords)
    """
    content_lower = content.lower()
    
    # Count keyword matches with position weighting
    def count_matches(keywords):
        score = 0
        matches = []
        for keyword in keywords:
            if keyword in content_lower:
                # Position weight: earlier in text = higher weight
                position = content_lower.find(keyword)
                weight = 1.0 if position < 100 else 0.5
                score += weight
                matches.append(keyword)
        return score, matches
    
    t1_score, t1_matches = count_matches(T1_KEYWORDS)
    t2_score, t2_matches = count_matches(T2_KEYWORDS)
    t3_score, t3_matches = count_matches(T3_KEYWORDS)
    t4_score, t4_matches = count_matches(T4_KEYWORDS)
    
    # Determine tier based on highest score
    scores = [("T1", t1_score), ("T2", t2_score), ("T3", t3_score), ("T4", t4_score)]
    scores.sort(key=lambda x: x[1], reverse=True)
    
    # Thresholds
    if scores[0][1] >= 2.0:
        tier = scores[0][0]
        confidence = "high"
    elif scores[0][1] >= 1.0:
        tier = scores[0][0]
        confidence = "medium"
    elif scores[0][1] >= 0.5:
        tier = scores[0][0]
        confidence = "low"
    else:
        tier = "T4"  # Default to logs
        confidence = "default"
    
    all_matches = t1_matches + t2_matches + t3_matches + t4_matches
    return tier, confidence, all_matches


def check_security(content: str) -> tuple:
    """
    Check if content contains credential-like patterns.
    
    Returns: (is_flagged, matched_patterns)
    """
    if not SECURITY_FILTER_ENABLED:
        return False, []
    
    matches = []
    for pattern in SECURITY_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            matches.append(pattern)
    
    return len(matches) > 0, matches


def get_db_connection() -> sqlite3.Connection:
    """Get graymatter DB connection."""
    if not GRAYMATTER_DB.exists():
        print(f"❌ Database not found: {GRAYMATTER_DB}")
        sys.exit(1)
    
    conn = sqlite3.connect(str(GRAYMATTER_DB))
    conn.row_factory = sqlite3.Row
    return conn


def check_schema(conn: sqlite3.Connection) -> bool:
    """Check if security columns exist."""
    cursor = conn.execute("PRAGMA table_info(fts_index)")
    columns = [row[1] for row in cursor.fetchall()]
    return "security_flagged" in columns


def add_security_columns(conn: sqlite3.Connection, dry_run: bool = False):
    """Add security filter columns to FTS5 table."""
    print("📝 Adding security filter columns to fts_index...")
    
    if dry_run:
        print("  [DRY RUN] Would add security columns")
        return
    
    # Rebuild FTS5 table with security columns
    conn.execute("DROP TABLE IF EXISTS fts_index_new")
    conn.execute("""
        CREATE VIRTUAL TABLE fts_index_new USING fts5(
            skill,
            command,
            content,
            timestamp,
            tier,
            filepath,
            content_hash,
            security_flagged,
            security_resolved,
            security_reason
        )
    """)
    
    # Copy data
    conn.execute("""
        INSERT INTO fts_index_new (
            skill, command, content, timestamp, tier, filepath, content_hash
        )
        SELECT skill, command, content, timestamp, tier, filepath, content_hash
        FROM fts_index
    """)
    
    # Swap tables
    conn.execute("DROP TABLE fts_index")
    conn.execute("ALTER TABLE fts_index_new RENAME TO fts_index")
    
    conn.commit()
    print("✅ Security columns added")


def classify_all(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """
    Classify all entries and apply security filter.
    
    Returns classification statistics.
    """
    print("\n🔨 Classifying entries...")
    
    # Get all entries (re-classify everything for accuracy)
    cursor = conn.execute("""
        SELECT rowid, content FROM fts_index 
        LIMIT 10000
    """)
    
    entries = cursor.fetchall()
    total = len(entries)
    
    stats = {"T1": 0, "T2": 0, "T3": 0, "T4": 0, "security_flagged": 0}
    
    if total == 0:
        print("✅ No entries to classify")
        return stats
    
    print(f"   Processing {total} entries")
    
    if dry_run:
        print(f"  [DRY RUN] Would classify {total} entries")
        return stats
    
    # Classify in batches
    batch_size = 100
    
    for i in range(0, total, batch_size):
        batch = entries[i:i+batch_size]
        
        for row in batch:
            rowid = row[0]
            content = row[1]
            
            # Classify tier
            tier, confidence, matches = classify_tier(content)
            
            # Check security
            is_flagged, security_matches = check_security(content)
            
            stats[tier] += 1
            if is_flagged:
                stats["security_flagged"] += 1
            
            # Update database
            security_reason = ",".join(security_matches[:3]) if security_matches else ""
            
            conn.execute("""
                UPDATE fts_index 
                SET tier = ?, security_flagged = ?, security_reason = ?
                WHERE rowid = ?
            """, (tier, 1 if is_flagged else 0, security_reason, rowid))
        
        conn.commit()
        
        # Progress
        processed = min(i + batch_size, total)
        pct = (processed / total) * 100
        print(f"   Progress: {processed}/{total} ({pct:.1f}%)")
    
    print(f"\n✅ Classified {total} entries")
    return stats


def show_status(conn: sqlite3.Connection):
    """Show current tier distribution."""
    has_security = check_schema(conn)
    
    print("📊 Tier Classification Status\n")
    print(f"Database: {GRAYMATTER_DB}")
    print()
    
    # Tier distribution
    cursor = conn.execute("""
        SELECT tier, COUNT(*) as count
        FROM fts_index
        GROUP BY tier
        ORDER BY tier
    """)
    
    tiers = {row[0]: row[1] for row in cursor.fetchall()}
    total = sum(tiers.values())
    
    print(f"Total entries: {total:,}")
    print()
    print("Tier Distribution:")
    for tier in ["T1", "T2", "T3", "T4"]:
        count = tiers.get(tier, 0)
        pct = (count / total * 100) if total > 0 else 0
        bar = "█" * int(pct / 2)
        print(f"  {tier}: {count:>6,} ({pct:5.1f}%) {bar}")
    
    # Security stats
    if has_security:
        cursor = conn.execute("""
            SELECT COUNT(*) FROM fts_index WHERE security_flagged = 1
        """)
        flagged = cursor.fetchone()[0]
        
        print(f"\n🔒 Security Filter:")
        print(f"   Flagged entries: {flagged:,} ({flagged/total*100:.2f}%)")
        
        # Sample flagged
        cursor = conn.execute("""
            SELECT substr(content, 1, 80) as preview, security_reason
            FROM fts_index
            WHERE security_flagged = 1
            LIMIT 3
        """)
        
        samples = cursor.fetchall()
        if samples:
            print(f"\n   Sample flagged content:")
            for sample in samples:
                print(f"   - {sample[0]}...")
                print(f"     Reason: {sample[1]}")
    else:
        print("\n⚠️  Security columns not present")
        print("   Run without --status to add them")


def main():
    parser = argparse.ArgumentParser(
        description="CORTEX Tier Classifier — T1-T4 classification + security filter"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current tier distribution"
    )
    
    args = parser.parse_args()
    
    print(f"🧠 CORTEX Tier Classifier — {datetime.now().isoformat()}\n")
    
    conn = get_db_connection()
    
    if args.status:
        show_status(conn)
    else:
        # Check schema
        has_security = check_schema(conn)
        
        if not has_security:
            add_security_columns(conn, dry_run=args.dry_run)
        
        # Classify
        stats = classify_all(conn, dry_run=args.dry_run)
        
        # Summary
        if not args.dry_run:
            print("\n📋 Summary:")
            for tier in ["T1", "T2", "T3", "T4"]:
                print(f"   {tier}: {stats[tier]}")
            print(f"   Security flagged: {stats['security_flagged']}")
            
            print("\n📊 Verification:")
            show_status(conn)
    
    conn.close()


if __name__ == "__main__":
    main()
