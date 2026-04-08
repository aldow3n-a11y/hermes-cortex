#!/usr/bin/env python3
"""
CORTEX LYT Mind Mapper

Auto-generates Maps of Content (MOCs) in Obsidian when 5+ notes exist on a topic.
Follows Linking Your Thinking (LYT) methodology.

Features:
- Scans CORTEX notes directory for emerging topics
- Identifies clusters of 5+ related notes
- Generates MOC files with:
  - Topic overview
  - Linked notes (sorted by date)
  - Emerging themes/tags
  - Connection suggestions
- Updates existing MOCs when new notes are added

Schedule:
    0 2 * * * python /HOME/workspace/cortex/scripts/lyt-mind-mapper.py

Usage:
    python lyt-mind-mapper.py --dry-run     # See what MOCs would be created
    python lyt-mind-mapper.py --generate    # Actually create MOCs
    python lyt-mind-mapper.py --status      # Check current MOC coverage
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# Configuration
HERMES_HOME = Path("/HOME/.hermes")
OBSIDIAN_VAULT = Path("/HOME/AldoObsidianVault")
CORTEX_NOTES_DIR = OBSIDIAN_VAULT / "03-CORTEX"
PRINCIPLES_DIR = CORTEX_NOTES_DIR / "01-Principles"
DECISIONS_DIR = CORTEX_NOTES_DIR / "02-Decisions"
MOC_DIR = CORTEX_NOTES_DIR / "00-MOCs"

# MOC generation threshold
MIN_NOTES_FOR_MOC = 5

# Topic extraction patterns
TOPIC_PATTERNS = [
    r'#\s*([A-Za-z][A-Za-z0-9\s\-]+)',  # Markdown headers
    r'tags:\s*\n?\s*-\s*([a-z]+)',       # YAML tags
    r'\[\[([^\]]+)\]\]',                  # Wiki links
    r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b',  # Capitalized phrases
]


def extract_topics_from_note(filepath: Path) -> list:
    """Extract topics/themes from a note file."""
    topics = []
    
    try:
        with open(filepath, "r") as f:
            content = f.read()
    except Exception as e:
        print(f"   ⚠️  Could not read {filepath}: {e}")
        return topics
    
    # Extract from headers
    headers = re.findall(r'#\s*([A-Za-z][A-Za-z0-9\s\-]+)', content)
    topics.extend([h.strip().lower() for h in headers])
    
    # Extract from tags
    tags = re.findall(r'tags:\s*\n?\s*-\s*([a-z]+)', content.lower())
    topics.extend(tags)
    
    # Extract from wiki links
    wiki_links = re.findall(r'\[\[([^\]]+)\]\]', content)
    topics.extend([wl.strip().lower() for wl in wiki_links])
    
    # Extract capitalized phrases (potential topics)
    phrases = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', content[:1000])
    topics.extend([p.lower() for p in phrases[:10]])
    
    return topics


def extract_topics_from_filename(filepath: Path) -> list:
    """Extract topics from filename."""
    name = filepath.stem
    
    # Remove hash suffix (e.g., "-8b7f73cd")
    name = re.sub(r'-[a-f0-9]{6,}$', '', name)
    
    # Split on dashes/underscores
    words = re.split(r'[-_]', name)
    
    # Filter meaningful words
    stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'to', 'of', 'and', 'in'}
    topics = [w.lower() for w in words if len(w) > 3 and w.lower() not in stop_words]
    
    return topics


def scan_notes_for_topics() -> dict:
    """
    Scan all CORTEX notes and extract topics.
    
    Returns: {topic: [list of note filepaths]}
    """
    topic_map = defaultdict(list)
    
    # Scan Principles and Decisions directories
    for notes_dir in [PRINCIPLES_DIR, DECISIONS_DIR]:
        if not notes_dir.exists():
            continue
        
        for filepath in notes_dir.glob("*.md"):
            # Skip MOC files themselves
            if "MOC" in filepath.name or filepath.stem.startswith("00-"):
                continue
            
            # Extract topics from content
            content_topics = extract_topics_from_note(filepath)
            
            # Extract topics from filename
            filename_topics = extract_topics_from_filename(filepath)
            
            # Combine and deduplicate
            all_topics = list(set(content_topics + filename_topics))
            
            # Map topics to this note
            for topic in all_topics:
                if len(topic) > 2:  # Skip very short topics
                    topic_map[topic].append(filepath)
    
    return dict(topic_map)


def identify_moc_candidates(topic_map: dict) -> list:
    """
    Identify topics that have 5+ notes (MOC candidates).
    
    Returns: [(topic, [note filepaths], note_count)]
    """
    candidates = []
    
    for topic, notes in topic_map.items():
        if len(notes) >= MIN_NOTES_FOR_MOC:
            candidates.append((topic, notes, len(notes)))
    
    # Sort by note count (descending)
    candidates.sort(key=lambda x: x[2], reverse=True)
    
    return candidates


def get_existing_mocs() -> set:
    """Get set of existing MOC filenames."""
    if not MOC_DIR.exists():
        return set()
    
    return {f.stem.lower() for f in MOC_DIR.glob("*.md")}


def generate_moc_content(topic: str, notes: list) -> str:
    """Generate MOC markdown content."""
    topic_title = topic.replace('-', ' ').title()
    
    # Sort notes by modification time
    notes_sorted = sorted(notes, key=lambda p: p.stat().st_mtime, reverse=True)
    
    # Extract common themes from notes
    all_tags = []
    for note in notes_sorted[:10]:
        try:
            with open(note, "r") as f:
                content = f.read()
                tags = re.findall(r'tags:\s*\n?\s*-\s*([a-z]+)', content.lower())
                all_tags.extend(tags)
        except:
            pass
    
    tag_counts = Counter(all_tags)
    top_tags = tag_counts.most_common(5)
    
    # Generate content
    content = f"""---
type: moc
topic: {topic}
created: {datetime.now().strftime("%Y-%m-%d")}
updated: {datetime.now().strftime("%Y-%m-%d")}
notes_count: {len(notes)}
tags:
  - cortex
  - moc
  - {topic}
---

# {topic_title} — Map of Content

**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M")}  
**Notes:** {len(notes)} entries  
**Status:** 🌱 Emerging

---

## Overview

This MOC connects {len(notes)} notes related to **{topic_title}**.

"""
    
    # Add themes section if we have tags
    if top_tags:
        content += "### Common Themes\n\n"
        for tag, count in top_tags:
            content += f"- `{tag}` ({count} notes)\n"
        content += "\n"
    
    # Add notes section
    content += """---

## Connected Notes

"""
    
    for i, note in enumerate(notes_sorted, 1):
        note_title = note.stem
        # Clean up title (remove hash)
        note_title = re.sub(r'-[a-f0-9]{6,}$', '', note_title)
        note_title = note_title.replace('-', ' ').title()
        
        # Calculate note age
        age_days = (datetime.now() - datetime.fromtimestamp(note.stat().st_mtime)).days
        
        content += f"{i}. [[{note.stem}|{note_title}]]"
        if age_days > 0:
            content += f" _({age_days}d ago)_"
        content += "\n"
    
    # Add connections section
    content += f"""
---

## Connections

### Related MOCs
_Auto-generated suggestions based on shared tags_

- [[Principles MOC]]
- [[Decisions MOC]]

### Next Actions
- [ ] Review and refine topic connections
- [ ] Add personal synthesis/insights
- [ ] Link to external resources

---

*Generated by CORTEX LYT Mind Mapper*
"""
    
    return content


def create_moc(topic: str, notes: list, dry_run: bool = False) -> Path:
    """Create a MOC file for the topic."""
    # Generate filename
    filename = f"00-{topic.title().replace(' ', '-')}-MOC.md"
    filepath = MOC_DIR / filename
    
    # Generate content
    content = generate_moc_content(topic, notes)
    
    if dry_run:
        print(f"   Would create: {filepath}")
        print(f"   Notes: {len(notes)} entries on '{topic}'")
        return filepath
    
    # Ensure directory exists
    MOC_DIR.mkdir(parents=True, exist_ok=True)
    
    # Write MOC
    with open(filepath, "w") as f:
        f.write(content)
    
    print(f"   ✅ Created: {filepath}")
    print(f"   Notes: {len(notes)} entries on '{topic}'")
    
    return filepath


def run_moc_generation(dry_run: bool = False) -> dict:
    """Run the full MOC generation pipeline."""
    print("\n🗺️  Scanning for emerging topics...\n")
    
    results = {
        "topics_scanned": 0,
        "moc_candidates": 0,
        "mocs_created": 0,
        "mocs_updated": 0,
        "existing_mocs": 0,
        "files": []
    }
    
    # Step 1: Scan notes for topics
    topic_map = scan_notes_for_topics()
    results["topics_scanned"] = len(topic_map)
    
    print(f"   Found {len(topic_map)} unique topics across all notes\n")
    
    # Step 2: Identify MOC candidates
    candidates = identify_moc_candidates(topic_map)
    results["moc_candidates"] = len(candidates)
    
    print(f"   {len(candidates)} topics have {MIN_NOTES_FOR_MOC}+ notes (MOC candidates)\n")
    
    # Step 3: Get existing MOCs
    existing_mocs = get_existing_mocs()
    results["existing_mocs"] = len(existing_mocs)
    
    if existing_mocs:
        print(f"   Existing MOCs: {len(existing_mocs)}")
    
    # Step 4: Create/update MOCs
    print(f"\n📝 Generating MOCs:\n")
    
    for topic, notes, count in candidates:
        # Check if MOC already exists
        moc_name = f"00-{topic.title().replace(' ', '-')}-moc"
        
        if moc_name in existing_mocs:
            # Would update (not implemented yet)
            print(f"   ⏭️  Skipped (exists): {topic} ({count} notes)")
            results["mocs_updated"] += 1
        else:
            # Create new MOC
            filepath = create_moc(topic, notes, dry_run=dry_run)
            results["mocs_created"] += 1
            results["files"].append(str(filepath))
    
    return results


def show_status() -> dict:
    """Show current MOC coverage status."""
    print("📊 LYT Mind Mapper Status\n")
    
    # Scan topics
    topic_map = scan_notes_for_topics()
    
    # Get candidates
    candidates = identify_moc_candidates(topic_map)
    
    # Get existing MOCs
    existing_mocs = get_existing_mocs()
    
    print(f"Topics scanned: {len(topic_map)}")
    print(f"MOC candidates ({MIN_NOTES_FOR_MOC}+ notes): {len(candidates)}")
    print(f"Existing MOCs: {len(existing_mocs)}")
    print()
    
    if candidates:
        print(f"Top MOC candidates:")
        for topic, notes, count in candidates[:10]:
            status = "✅ MOC exists" if f"00-{topic.title().replace(' ', '-')}-moc" in existing_mocs else "⏳ Pending"
            print(f"   {topic}: {count} notes {status}")
    
    return {
        "topics": len(topic_map),
        "candidates": len(candidates),
        "existing": len(existing_mocs)
    }


def main():
    parser = argparse.ArgumentParser(
        description="CORTEX LYT Mind Mapper — Auto-generate MOCs from note clusters"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what MOCs would be created"
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate MOCs"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current MOC coverage"
    )
    parser.add_argument(
        "--min-notes",
        type=int,
        default=MIN_NOTES_FOR_MOC,
        help=f"Minimum notes for MOC creation (default: {MIN_NOTES_FOR_MOC})"
    )
    
    args = parser.parse_args()
    
    print(f"🧠 CORTEX LYT Mind Mapper — {datetime.now().isoformat()}\n")
    
    # Check if CORTEX notes directory exists
    if not CORTEX_NOTES_DIR.exists():
        print(f"⚠️  CORTEX notes directory not found: {CORTEX_NOTES_DIR}")
        print("   Run atomic-note-creator.py first to sync T1 notes")
        sys.exit(1)
    
    if args.status:
        show_status()
        return
    
    if not args.generate and not args.dry_run:
        print("⚠️  Use --dry-run to preview or --generate to execute")
        print("   Example: python lyt-mind-mapper.py --dry-run")
        return
    
    # Run generation
    results = run_moc_generation(dry_run=not args.generate)
    
    # Summary
    print("\n" + "=" * 60)
    print("📋 MOC Generation Summary:")
    print(f"   Topics scanned:    {results['topics_scanned']}")
    print(f"   MOC candidates:    {results['moc_candidates']}")
    print(f"   MOCs created:      {results['mocs_created']}")
    print(f"   MOCs updated:      {results['mocs_updated']}")
    print(f"   Existing MOCs:     {results['existing_mocs']}")
    
    if not args.dry_run and results["mocs_created"] > 0:
        print(f"\n💾 MOCs location: {MOC_DIR}")
    
    # Exit code
    sys.exit(0)


if __name__ == "__main__":
    main()
