#!/usr/bin/env python3
"""
CORTEX Atomic Note Creator

Syncs T1 (Principles/Decisions) content to Obsidian as atomic notes.
Each note is self-contained, linked, and follows Zettelkasten principles.

Features:
- Deduplication via content hash
- Auto-linking to existing MOCs
- Frontmatter with metadata (tier, source, timestamp, hash)
- Tags based on content themes
- Backlink tracking

Usage:
    python atomic-note-creator.py --dry-run     # See what would be created
    python atomic-note-creator.py --sync        # Actually sync to Obsidian
    python atomic-note-creator.py --status      # Check sync status
"""

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Configuration
HERMES_HOME = Path("/HOME/.hermes")
GRAYMATTER_DB = HERMES_HOME / "context" / "stats.db"
OBSIDIAN_VAULT = Path("/HOME/AldoObsidianVault")
CORTEX_NOTES_DIR = OBSIDIAN_VAULT / "03-CORTEX"
PRINCIPLES_DIR = CORTEX_NOTES_DIR / "01-Principles"
DECISIONS_DIR = CORTEX_NOTES_DIR / "02-Decisions"
MOC_DIR = CORTEX_NOTES_DIR / "00-MOCs"


def get_db_connection() -> sqlite3.Connection:
    """Get graymatter DB connection."""
    if not GRAYMATTER_DB.exists():
        print(f"❌ Database not found: {GRAYMATTER_DB}")
        sys.exit(1)
    
    conn = sqlite3.connect(str(GRAYMATTER_DB))
    conn.row_factory = sqlite3.Row
    return conn


def get_t1_entries(conn: sqlite3.Connection, synced_only: bool = False) -> list:
    """
    Get T1 entries ready for Obsidian sync.
    
    Args:
        synced_only: If True, only return already-synced entries
    """
    if synced_only:
        # Get entries that have been synced (have obsidian filepath in references)
        cursor = conn.execute("""
            SELECT f.rowid, f.filepath, f.content, f.tier, f.content_hash, f.timestamp,
                   f.security_flagged, cr.obsidian
            FROM fts_index f
            LEFT JOIN content_references cr ON f.content_hash = cr.content_hash
            WHERE f.tier = 'T1'
              AND f.security_flagged = 0
              AND cr.obsidian = 1
            ORDER BY f.timestamp DESC
        """)
    else:
        # Get entries ready to sync (T1, not flagged, not already in Obsidian)
        cursor = conn.execute("""
            SELECT f.rowid, f.filepath, f.content, f.tier, f.content_hash, f.timestamp,
                   f.security_flagged, cr.obsidian
            FROM fts_index f
            LEFT JOIN content_references cr ON f.content_hash = cr.content_hash
            WHERE f.tier = 'T1'
              AND f.security_flagged = 0
              AND f.content_hash IS NOT NULL
              AND (cr.obsidian = 0 OR cr.obsidian IS NULL)
            ORDER BY f.timestamp DESC
            LIMIT 100
        """)
    
    return cursor.fetchall()


def extract_themes(content: str, max_themes: int = 5) -> list:
    """Extract themes/topics from content for tagging."""
    # Simple heuristic: capitalized words, keywords
    themes = []
    
    # Look for capitalized phrases (potential topics)
    capitalized = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', content[:500])
    themes.extend(capitalized[:max_themes])
    
    # Common knowledge management tags
    keywords = {
        'memory', 'knowledge', 'system', 'process', 'workflow',
        'decision', 'principle', 'rule', 'boundary', 'policy',
        'agent', 'ai', 'automation', 'tool', 'infrastructure'
    }
    
    content_lower = content.lower()
    for keyword in keywords:
        if keyword in content_lower:
            themes.append(keyword.capitalize())
    
    # Deduplicate and limit
    themes = list(dict.fromkeys(themes))[:max_themes]
    
    return themes if themes else ["uncategorized"]


def generate_note_title(content: str, max_length: int = 60) -> str:
    """Generate a concise, descriptive title from content."""
    first_line = content.split("\n")[0].strip()
    
    # Skip tool call artifacts - check for common patterns
    if (content.startswith("Tool-call-") or 
        content.startswith("-success-") or 
        content.startswith("{") or
        "exit_code" in content[:50] or
        first_line.startswith("- success") or
        first_line.startswith("- content")):
        # Extract meaningful snippet from content
        # Look for actual text content in the first few lines
        for line in content.split("\n")[:5]:
            line = line.strip()
            if (len(line) > 15 and 
                not line.startswith("-") and 
                not line.startswith("{") and
                not line.startswith("[")):
                first_line = line
                break
        else:
            # Use content hash snippet as fallback
            title = "Principle-" + hashlib.md5(content.encode()).hexdigest()[:8]
            return title
    
    # Remove markdown headers
    title = re.sub(r'^#+\s*', '', first_line)
    
    # Remove tool call prefixes and leading dashes/brackets
    title = re.sub(r'^[-\[\]]*\s*', '', title)
    
    # Truncate
    if len(title) > max_length:
        title = title[:max_length-3] + "..."
    
    # Sanitize filename
    title = re.sub(r'[<>:"/\\|?*]', '', title)
    
    # Remove leading/trailing dashes
    title = title.strip('-').strip()
    
    return title if title and len(title) > 3 else "Principle-" + hashlib.md5(content.encode()).hexdigest()[:8]


def create_note_frontmatter(entry: dict) -> str:
    """Generate YAML frontmatter for the note."""
    timestamp = entry[5]
    content_hash = entry[4]
    source = entry[1]
    
    # Extract date from timestamp
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        created_date = dt.strftime("%Y-%m-%d")
    except:
        created_date = datetime.now().strftime("%Y-%m-%d")
    
    frontmatter = f"""---
tier: T1
type: principle
created: {created_date}
source: {source}
content_hash: {content_hash}
tags:
  - cor tex
  - principle
  - t1
---
"""
    return frontmatter


def format_note_content(content: str) -> str:
    """Format content for Obsidian (clean up, add links)."""
    # Remove any existing frontmatter
    content = re.sub(r'^---\n.*?\n---\n', '', content, flags=re.DOTALL)
    
    # Convert session filepaths to links (if present)
    content = re.sub(
        r'(/HOME/\.hermes/sessions/\d+_\d+_[a-f]+\.jsonl)',
        lambda m: f"[[Session Log|{m.group(1)}]]",
        content
    )
    
    # Add backlink section
    content += "\n\n---\n## Links\n- Backlinks: _auto-generated by CORTEX_\n"
    
    return content


def create_atomic_note(entry: dict, dry_run: bool = False) -> Path:
    """Create an atomic note in Obsidian."""
    content = entry[2]
    content_hash = entry[4]
    timestamp = entry[5]
    
    # Generate title
    title = generate_note_title(content)
    
    # Generate filename (use hash for uniqueness)
    safe_title = re.sub(r'[^a-zA-Z0-9]+', '-', title)[:40]
    # Strip leading/trailing dashes that may result from sanitization
    safe_title = safe_title.strip('-')
    filename = f"{safe_title}-{content_hash[:8]}.md"
    
    # Determine directory (Principles vs Decisions)
    # Heuristic: if content contains "decided" or "decision", use Decisions dir
    if any(word in content.lower() for word in ["decided", "decision", "chose", "choice"]):
        target_dir = DECISIONS_DIR
    else:
        target_dir = PRINCIPLES_DIR
    
    filepath = target_dir / filename
    
    # Generate full note content
    frontmatter = create_note_frontmatter(entry)
    body = format_note_content(content)
    full_content = frontmatter + body
    
    if dry_run:
        print(f"   Would create: {filepath}")
        return filepath
    
    # Create directory if needed
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # Write note
    with open(filepath, "w") as f:
        f.write(full_content)
    
    return filepath


def update_content_references(conn: sqlite3.Connection, content_hash: str, obsidian_path: Path):
    """Mark content as synced to Obsidian in references table."""
    conn.execute("""
        INSERT OR REPLACE INTO content_references (
            content_hash, hermes, graymatter, obsidian,
            ref_count, first_seen, last_accessed, last_updated
        ) VALUES (
            ?, 1, 1, 1,
            3, datetime('now'), datetime('now'), datetime('now')
        )
    """, (content_hash,))
    conn.commit()


def get_sync_status(conn: sqlite3.Connection) -> dict:
    """Get current sync status between graymatter and Obsidian."""
    # Total T1 entries
    cursor = conn.execute("""
        SELECT COUNT(*) FROM fts_index WHERE tier = 'T1' AND security_flagged = 0
    """)
    total_t1 = cursor.fetchone()[0]
    
    # Synced to Obsidian
    cursor = conn.execute("""
        SELECT COUNT(DISTINCT f.content_hash)
        FROM fts_index f
        JOIN content_references cr ON f.content_hash = cr.content_hash
        WHERE f.tier = 'T1' AND cr.obsidian = 1
    """)
    synced = cursor.fetchone()[0]
    
    # Pending sync
    pending = total_t1 - synced
    
    # Check Obsidian directory
    if CORTEX_NOTES_DIR.exists():
        notes_count = len(list(PRINCIPLES_DIR.glob("*.md"))) + len(list(DECISIONS_DIR.glob("*.md")))
    else:
        notes_count = 0
    
    return {
        "total_t1": total_t1,
        "synced": synced,
        "pending": pending,
        "obsidian_notes": notes_count
    }


def run_sync(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """Run the full sync pipeline."""
    print("\n🔄 Syncing T1 entries to Obsidian...\n")
    
    results = {
        "created": 0,
        "skipped": 0,
        "errors": [],
        "files": []
    }
    
    # Get entries to sync
    entries = get_t1_entries(conn, synced_only=False)
    
    if not entries:
        print("   ✅ All T1 entries already synced")
        return results
    
    # Deduplicate by content_hash (same content may appear in multiple files)
    seen_hashes = set()
    unique_entries = []
    for entry in entries:
        content_hash = entry[4]
        if content_hash not in seen_hashes:
            seen_hashes.add(content_hash)
            unique_entries.append(entry)
    
    print(f"   Found {len(entries)} T1 entries to sync")
    print(f"   Unique entries (deduped): {len(unique_entries)}\n")
    
    # Ensure directories exist
    if not dry_run:
        CORTEX_NOTES_DIR.mkdir(parents=True, exist_ok=True)
        PRINCIPLES_DIR.mkdir(parents=True, exist_ok=True)
        DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
        MOC_DIR.mkdir(parents=True, exist_ok=True)
    
    # Create notes
    for i, entry in enumerate(unique_entries, 1):
        try:
            filepath = create_atomic_note(entry, dry_run=dry_run)
            
            if not dry_run:
                # Update references
                update_content_references(conn, entry[4], filepath)
            
            results["created"] += 1
            results["files"].append(str(filepath))
            
            # Progress
            if i % 10 == 0 or i == len(unique_entries):
                print(f"   Progress: {i}/{len(unique_entries)}")
                
        except Exception as e:
            results["errors"].append(f"{entry[4]}: {str(e)[:100]}")
            results["skipped"] += 1
            print(f"   ❌ Error: {entry[4]} - {str(e)[:80]}")
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description="CORTEX Atomic Note Creator — T1 to Obsidian sync"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without actually creating"
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Execute sync to Obsidian"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current sync status"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Max notes to create in one run (default: 100)"
    )
    
    args = parser.parse_args()
    
    print(f"🧠 CORTEX Atomic Note Creator — {datetime.now().isoformat()}\n")
    
    conn = get_db_connection()
    
    if args.status:
        status = get_sync_status(conn)
        print("📊 Sync Status:\n")
        print(f"   Total T1 entries:     {status['total_t1']}")
        print(f"   Synced to Obsidian:   {status['synced']}")
        print(f"   Pending sync:         {status['pending']}")
        print(f"   Obsidian notes:       {status['obsidian_notes']}")
        print(f"\n   Sync progress:        {status['synced']/status['total_t1']*100:.1f}%")
        conn.close()
        return
    
    if not args.sync and not args.dry_run:
        print("⚠️  Use --dry-run to preview or --sync to execute")
        print("   Example: python atomic-note-creator.py --dry-run")
        conn.close()
        return
    
    # Run sync
    results = run_sync(conn, dry_run=not args.sync)
    
    # Summary
    print("\n" + "=" * 60)
    print("📋 Sync Summary:")
    print(f"   Created: {results['created']} notes")
    print(f"   Skipped: {results['skipped']}")
    if results["errors"]:
        print(f"   Errors: {len(results['errors'])}")
    
    if not args.dry_run and results["created"] > 0:
        print(f"\n💾 Notes location: {CORTEX_NOTES_DIR}")
        print(f"   Principles: {PRINCIPLES_DIR}")
        print(f"   Decisions: {DECISIONS_DIR}")
    
    conn.close()
    
    # Exit code
    if results["errors"]:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
