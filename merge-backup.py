#!/usr/bin/env python3
"""
Merge knowledge-backup into AldoObsidianVault

Copies:
- Atlas/Maps/ → Atlas/Maps/ (merge MOCs)
- Efforts/ → Efforts/ (session snapshots)
- Templates/ → Templates/ (merge templates)
- .obsidian/ → .obsidian/ (merge config)

Skips:
- .git directories
- Files that already exist (with prompt)
"""

import shutil
import sys
from pathlib import Path

# Paths
BACKUP = Path("/HOME/workspace/knowledge-backup")
VAULT = Path("/HOME/AldoObsidianVault")

# What to merge
MERGE_FOLDERS = [
    "Atlas",
    "Efforts",
    "Templates",
    ".obsidian"
]

# Stats
stats = {
    "copied": 0,
    "skipped": 0,
    "conflicts": 0,
    "errors": 0
}


def copy_folder(src: Path, dst: Path):
    """Copy folder with conflict handling."""
    print(f"\n📁 {src.relative_to(BACKUP)} → {dst.relative_to(VAULT)}")
    
    if not src.exists():
        print(f"   ⚠️  Source not found")
        return
    
    # Create destination
    dst.mkdir(parents=True, exist_ok=True)
    
    # Copy files
    for item in src.rglob("*"):
        if item.is_file():
            # Skip .git files
            if ".git" in str(item):
                continue
            
            # Calculate relative path
            rel_path = item.relative_to(src)
            target = dst / rel_path
            
            # Check if exists
            if target.exists():
                stats["conflicts"] += 1
                print(f"   ⚠️  Conflict: {rel_path} (keeping existing)")
                continue
            
            try:
                # Create parent dirs
                target.parent.mkdir(parents=True, exist_ok=True)
                
                # Copy file
                shutil.copy2(item, target)
                stats["copied"] += 1
                
            except Exception as e:
                stats["errors"] += 1
                print(f"   ❌ Error copying {rel_path}: {e}")
    
    print(f"   ✅ Done")


def main():
    print("🔄 Merging knowledge-backup into AldoObsidianVault")
    print("=" * 60)
    print(f"\nSource: {BACKUP}")
    print(f"Target: {VAULT}")
    
    # Confirm
    print("\n⚠️  This will copy files from backup to vault.")
    print("   Existing files will NOT be overwritten.\n")
    
    # Copy each folder
    for folder in MERGE_FOLDERS:
        src = BACKUP / folder
        dst = VAULT / folder
        copy_folder(src, dst)
    
    # Copy root files (templates, etc.)
    print(f"\n📄 Root files...")
    for item in BACKUP.iterdir():
        if item.is_file() and not item.name.startswith("."):
            target = VAULT / item.name
            if not target.exists():
                try:
                    shutil.copy2(item, target)
                    stats["copied"] += 1
                    print(f"   ✅ {item.name}")
                except Exception as e:
                    stats["errors"] += 1
                    print(f"   ❌ {item.name}: {e}")
            else:
                stats["conflicts"] += 1
                print(f"   ⚠️  {item.name} (exists)")
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Merge Summary:")
    print(f"   Files copied:    {stats['copied']}")
    print(f"   Conflicts:       {stats['conflicts']} (existing kept)")
    print(f"   Skipped:         {stats['skipped']}")
    print(f"   Errors:          {stats['errors']}")
    
    if stats["errors"] == 0:
        print("\n✅ Merge complete!")
        return 0
    else:
        print(f"\n⚠️  Merge complete with {stats['errors']} errors")
        return 1


if __name__ == "__main__":
    sys.exit(main())
