#!/usr/bin/env python3
"""
CORTEX Midnight Reflection v4

Tier-based daily processing pipeline.
Runs at midnight to process the day's memory entries.

What it does:
1. Processes all entries from the current day
2. Groups by tier (T1/T2/T3/T4)
3. Generates daily summary digest
4. Prepares T1 content for Obsidian sync
5. Identifies archival candidates (old T4 entries)

Schedule:
    0 0 * * * python /HOME/workspace/cortex/scripts/midnight-reflection.py

Usage:
    python midnight-reflection.py              # Run for today
    python midnight-reflection.py --date 2026-04-08
    python midnight-reflection.py --dry-run
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
OUTPUT_DIR = HERMES_HOME / "context" / "daily_digests"


def get_db_connection() -> sqlite3.Connection:
    """Get graymatter DB connection."""
    if not GRAYMATTER_DB.exists():
        print(f"❌ Database not found: {GRAYMATTER_DB}")
        sys.exit(1)
    
    conn = sqlite3.connect(str(GRAYMATTER_DB))
    conn.row_factory = sqlite3.Row
    return conn


def get_entries_for_date(conn: sqlite3.Connection, date: datetime) -> list:
    """Get all entries for a specific date."""
    date_str = date.strftime("%Y-%m-%d")
    
    cursor = conn.execute("""
        SELECT rowid, filepath, content, tier, content_hash, timestamp,
               security_flagged, security_reason
        FROM fts_index
        WHERE date(timestamp) = date(?)
        ORDER BY tier, timestamp
    """, (date_str,))
    
    return cursor.fetchall()


def group_by_tier(entries: list) -> dict:
    """Group entries by tier."""
    tiers = {"T1": [], "T2": [], "T3": [], "T4": []}
    
    for entry in entries:
        # entry indices: 0=rowid, 1=filepath, 2=content, 3=tier, 4=content_hash, 5=timestamp, 6=security_flagged, 7=security_reason
        tier = entry[3] or "T4"  # Default to T4 if null
        if tier in tiers:
            tiers[tier].append(entry)
    
    return tiers


def generate_tier_summary(tier: str, entries: list) -> dict:
    """Generate summary for a specific tier."""
    if not entries:
        return {
            "tier": tier,
            "count": 0,
            "entries": [],
            "themes": []
        }
    
    # Extract key themes/topics from content
    themes = []
    for entry in entries:
        content = entry[2][:200]  # First 200 chars
        # Simple keyword extraction (first few nouns/capitalized words)
        words = content.split()[:20]
        key_words = [w for w in words if w[0].isupper() or len(w) > 6]
        themes.extend(key_words[:3])
    
    return {
        "tier": tier,
        "count": len(entries),
        "entries": [
            {
                "filepath": e[1],
                "content_preview": e[2][:300],
                "timestamp": e[3],
                "flagged": e[4] == 1
            }
            for e in entries[:20]  # Limit to 20 per tier
        ],
        "themes": list(set(themes))[:10]
    }


def generate_daily_digest(date: datetime, tiers: dict) -> dict:
    """Generate the daily digest report."""
    total = sum(t["count"] for t in tiers.values())
    
    digest = {
        "date": date.isoformat(),
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_entries": total,
            "t1_count": tiers["T1"]["count"],
            "t2_count": tiers["T2"]["count"],
            "t3_count": tiers["T3"]["count"],
            "t4_count": tiers["T4"]["count"],
            "security_flagged": sum(
                1 for t in tiers.values() 
                for e in t.get("entries", []) 
                if e.get("flagged")
            )
        },
        "tiers": tiers,
        "insights": []
    }
    
    # Generate insights
    if tiers["T1"]["count"] > 0:
        digest["insights"].append(
            f"📌 {tiers['T1']['count']} principles/decisions captured today"
        )
    
    if tiers["T2"]["count"] > 0:
        digest["insights"].append(
            f"🚀 {tiers['T2']['count']} project updates logged"
        )
    
    if tiers["T3"]["count"] > 0:
        digest["insights"].append(
            f"📚 {tiers['T3']['count']} knowledge entries added"
        )
    
    if digest["summary"]["security_flagged"] > 0:
        digest["insights"].append(
            f"🔒 {digest['summary']['security_flagged']} entries flagged (credentials blocked)"
        )
    
    # T4 ratio insight
    if total > 0:
        t4_ratio = tiers["T4"]["count"] / total * 100
        if t4_ratio > 70:
            digest["insights"].append(
                f"📊 High log ratio: {t4_ratio:.0f}% T4 (consider archival)"
            )
    
    return digest


def identify_archival_candidates(conn: sqlite3.Connection, date: datetime) -> list:
    """
    Identify T4 entries older than 7 days for archival.
    
    Criteria:
    - tier = T4
    - older than 7 days
    - not security flagged
    """
    cutoff = date - timedelta(days=7)
    
    cursor = conn.execute("""
        SELECT rowid, filepath, content_hash, timestamp
        FROM fts_index
        WHERE tier = 'T4'
          AND datetime(timestamp) < datetime(?)
          AND (security_flagged = 0 OR security_flagged IS NULL)
        ORDER BY timestamp
        LIMIT 100
    """, (cutoff.isoformat(),))
    
    return [dict(row) for row in cursor.fetchall()]


def prepare_obsidian_sync(t1_entries: list) -> list:
    """
    Prepare T1 entries for Obsidian sync.
    
    Returns list of entries ready for atomic note creation.
    """
    ready = []
    
    for entry in t1_entries:
        # Skip flagged entries
        if entry[4] == 1:  # security_flagged
            continue
        
        ready.append({
            "filepath": entry[1],
            "content": entry[2],
            "timestamp": entry[3],
            "hash": entry[2]  # content_hash
        })
    
    return ready


def save_digest(digest: dict, date: datetime, dry_run: bool = False) -> Path:
    """Save daily digest to file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    filename = f"daily-digest-{date.strftime('%Y-%m-%d')}.json"
    filepath = OUTPUT_DIR / filename
    
    if dry_run:
        print(f"\n  [DRY RUN] Would save digest to: {filepath}")
        return filepath
    
    with open(filepath, "w") as f:
        json.dump(digest, f, indent=2)
    
    print(f"\n💾 Digest saved to: {filepath}")
    return filepath


def run_daily_pipeline(date: datetime, dry_run: bool = False) -> dict:
    """Run the full midnight reflection pipeline."""
    print(f"🌙 Midnight Reflection v4 — {date.strftime('%Y-%m-%d')}")
    print("=" * 60)
    
    conn = get_db_connection()
    
    results = {
        "date": date.isoformat(),
        "entries_processed": 0,
        "tier_breakdown": {},
        "archival_candidates": 0,
        "obsidian_ready": 0,
        "digest_saved": None
    }
    
    # Step 1: Get entries for the date
    print("\n📥 Fetching entries...")
    entries = get_entries_for_date(conn, date)
    results["entries_processed"] = len(entries)
    print(f"   Found {len(entries)} entries for {date.strftime('%Y-%m-%d')}")
    
    if not entries:
        print("   No entries found for this date")
        conn.close()
        return results
    
    # Step 2: Group by tier
    print("\n🎯 Grouping by tier...")
    tiers_raw = group_by_tier(entries)
    
    # Step 3: Generate tier summaries
    print("\n📊 Generating tier summaries...")
    tier_summaries = {}
    for tier in ["T1", "T2", "T3", "T4"]:
        tier_summaries[tier] = generate_tier_summary(tier, tiers_raw[tier])
        results["tier_breakdown"][tier] = tier_summaries[tier]["count"]
        print(f"   {tier}: {tier_summaries[tier]['count']} entries")
    
    # Step 4: Generate daily digest
    print("\n📝 Generating daily digest...")
    digest = generate_daily_digest(date, tier_summaries)
    
    for insight in digest["insights"]:
        print(f"   {insight}")
    
    # Step 5: Identify archival candidates
    print("\n🗑️  Identifying archival candidates...")
    archival = identify_archival_candidates(conn, date)
    results["archival_candidates"] = len(archival)
    print(f"   Found {len(archival)} T4 entries older than 7 days")
    
    # Step 6: Prepare Obsidian sync
    print("\n📤 Preparing Obsidian sync (T1 only)...")
    obsidian_ready = prepare_obsidian_sync(tiers_raw["T1"])
    results["obsidian_ready"] = len(obsidian_ready)
    print(f"   {len(obsidian_ready)} T1 entries ready for Obsidian")
    
    # Step 7: Save digest
    print("\n💾 Saving daily digest...")
    digest_path = save_digest(digest, date, dry_run)
    results["digest_saved"] = str(digest_path)
    
    conn.close()
    
    print("\n" + "=" * 60)
    print("✅ Midnight Reflection complete!")
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description="CORTEX Midnight Reflection v4 — Tier-based daily processing"
    )
    parser.add_argument(
        "--date",
        type=str,
        help="Process a specific date (default: today)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes"
    )
    parser.add_argument(
        "--output-only",
        action="store_true",
        help="Only generate digest, skip other processing"
    )
    
    args = parser.parse_args()
    
    # Parse date
    if args.date:
        try:
            date = datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            print(f"❌ Invalid date format: {args.date}")
            print("   Use YYYY-MM-DD format")
            sys.exit(1)
    else:
        date = datetime.now()
    
    print(f"🌙 CORTEX Midnight Reflection v4 — {datetime.now().isoformat()}\n")
    
    # Run pipeline
    results = run_daily_pipeline(date, args.dry_run)
    
    # Exit with appropriate code
    if results["entries_processed"] == 0 and not args.dry_run:
        print("\n⚠️  No entries processed")
        sys.exit(0)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
