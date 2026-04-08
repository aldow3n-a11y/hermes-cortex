#!/usr/bin/env python3
"""
Unified Memory Sync — CORTEX + graymatter Integration

Combines the best of both systems into one cohesive pipeline:

1. midnight-reflection.py     → Extract wisdom from today's sessions
2. memory-pruner.py            → Clean old T4 logs (weekly)
3. atomic-note-creator.py      → Sync T1 principles to Obsidian
4. lyt-mind-mapper.py          → Generate/Update MOCs
5. knowledge-backup.py         → Push to GitHub (optional)

Usage:
    python unified-sync.py              # Full pipeline
    python unified-sync.py --dry-run     # Preview only
    python unified-sync.py --skip-pruner  # Skip weekly pruner
    python unified-sync.py --skip-backup  # Skip GitHub backup
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Configuration
CORTEX_DIR = Path("/HOME/workspace/cortex")
SCRIPTS_DIR = CORTEX_DIR / "scripts"
VAULT = Path("/HOME/AldoObsidianVault")
LOG_DIR = Path("/HOME/.hermes/logs")

# Stats
stats = {
    "start_time": None,
    "end_time": None,
    "steps": {},
    "errors": []
}


def log_step(step_name: str, success: bool, output: str = ""):
    """Log step result."""
    stats["steps"][step_name] = {
        "success": success,
        "output": output,
        "timestamp": datetime.now().isoformat()
    }


def run_script(script_path: Path, args: list = None, timeout: int = 180) -> tuple:
    """
    Run a CORTEX script and capture output.
    
    Returns: (success: bool, output: str)
    """
    cmd = ["python", str(script_path)]
    if args:
        cmd.extend(args)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(CORTEX_DIR)
        )
        
        success = result.returncode == 0
        output = result.stdout + (result.stderr if result.stderr else "")
        
        return success, output
        
    except subprocess.TimeoutExpired:
        return False, f"⏱️  Timed out after {timeout}s"
    except Exception as e:
        return False, f"❌ Error: {e}"


def step_1_midnight_reflection(dry_run: bool = False):
    """Step 1: Run midnight reflection."""
    script = SCRIPTS_DIR / "midnight-reflection.py"
    print("\n" + "=" * 60)
    print("🌙 STEP 1: Midnight Reflection")
    print("=" * 60)
    
    if dry_run:
        success, output = run_script(script, ["--dry-run"])
    else:
        success, output = run_script(script)
    
    # Extract summary from output
    if "Processed:" in output:
        summary_line = [l for l in output.split("\n") if "Processed:" in l]
        if summary_line:
            print(f"   {summary_line[0].strip()}")
    
    log_step("midnight_reflection", success, output)
    
    if success:
        print("   ✅ Midnight reflection complete")
    else:
        print(f"   ❌ Failed: {output[:200]}")
        stats["errors"].append("midnight_reflection failed")
    
    return success


def step_2_memory_pruner(dry_run: bool = False, skip: bool = False):
    """Step 2: Memory pruner (weekly cleanup)."""
    if skip:
        print("\n" + "=" * 60)
        print("⏭️  STEP 2: Memory Pruner (SKIPPED)")
        print("=" * 60)
        log_step("memory_pruner", True, "Skipped by user")
        return True
    
    script = SCRIPTS_DIR / "memory-pruner.py"
    print("\n" + "=" * 60)
    print("🧹 STEP 2: Memory Pruner")
    print("=" * 60)
    
    if dry_run:
        success, output = run_script(script, ["--dry-run"])
    else:
        # Only run if not dry run (pruner needs --execute to actually delete)
        success, output = run_script(script, ["--dry-run"])
        if success:
            print("   📋 Dry run complete. Run with --execute to prune.")
            return True
    
    log_step("memory_pruner", success, output)
    
    if success:
        print("   ✅ Memory pruner complete")
    else:
        print(f"   ⚠️  {output[:200]}")
    
    return success


def step_3_atomic_note_sync(dry_run: bool = False):
    """Step 3: Sync T1 notes to Obsidian."""
    script = SCRIPTS_DIR / "atomic-note-creator.py"
    print("\n" + "=" * 60)
    print("📝 STEP 3: Atomic Note Sync to Obsidian")
    print("=" * 60)
    
    if dry_run:
        success, output = run_script(script, ["--dry-run"])
    else:
        success, output = run_script(script, ["--sync"])
    
    # Extract summary
    if "Sync Summary:" in output:
        in_output = output.split("Sync Summary:")[1]
        for line in in_output.split("\n")[:5]:
            if line.strip():
                print(f"   {line.strip()}")
    
    log_step("atomic_note_sync", success, output)
    
    if success:
        print("   ✅ Atomic notes synced")
    else:
        print(f"   ❌ Failed: {output[:200]}")
        stats["errors"].append("atomic_note_sync failed")
    
    return success


def step_4_lyt_mind_mapper(dry_run: bool = False):
    """Step 4: Generate MOCs."""
    script = SCRIPTS_DIR / "lyt-mind-mapper.py"
    print("\n" + "=" * 60)
    print("🗺️  STEP 4: LYT Mind Mapper")
    print("=" * 60)
    
    if dry_run:
        success, output = run_script(script, ["--dry-run"])
    else:
        success, output = run_script(script, ["--generate"])
    
    # Extract summary
    if "MOC candidates:" in output:
        for line in output.split("\n"):
            if "candidates:" in line or "scanned:" in line:
                print(f"   {line.strip()}")
    
    log_step("lyt_mind_mapper", success, output)
    
    if success:
        print("   ✅ MOCs generated/updated")
    else:
        print(f"   ❌ Failed: {output[:200]}")
        stats["errors"].append("lyt_mind_mapper failed")
    
    return success


def step_5_knowledge_backup(dry_run: bool = False, skip: bool = False):
    """Step 5: Push vault to GitHub."""
    if skip:
        print("\n" + "=" * 60)
        print("⏭️  STEP 5: Knowledge Backup (SKIPPED)")
        print("=" * 60)
        log_step("knowledge_backup", True, "Skipped by user")
        return True
    
    script = SCRIPTS_DIR / "knowledge-backup.py"
    print("\n" + "=" * 60)
    print("💾 STEP 5: Knowledge Backup to GitHub")
    print("=" * 60)
    
    # Check if backup script exists in graymatter
    gm_backup = Path("/HOME/workspace/graymatter/scripts/knowledge-backup.py")
    if not script.exists() and gm_backup.exists():
        script = gm_backup
    
    if not script.exists():
        print("   ⚠️  Backup script not found, skipping")
        log_step("knowledge_backup", True, "Script not found")
        return True
    
    if dry_run:
        success, output = True, "Would push vault to GitHub"
    else:
        success, output = run_script(script, timeout=300)
    
    log_step("knowledge_backup", success, output)
    
    if success:
        print("   ✅ Vault backed up to GitHub")
    else:
        print(f"   ⚠️  Backup failed: {output[:200]}")
    
    return success


def generate_summary() -> str:
    """Generate execution summary."""
    elapsed = (stats["end_time"] - stats["start_time"]).total_seconds()
    
    summary = f"""
╔══════════════════════════════════════════════════════════════╗
║           UNIFIED MEMORY SYNC — EXECUTION SUMMARY              ║
╚══════════════════════════════════════════════════════════════╝

Started:  {stats['start_time'].strftime('%Y-%m-%d %H:%M:%S')}
Duration: {elapsed:.1f} seconds

┌─────────────────────────────────────────────────────────────┐
│ STEP RESULTS                                                 │
├─────────────────────────────────────────────────────────────┤
"""
    
    step_names = [
        ("midnight_reflection", "Midnight Reflection"),
        ("memory_pruner", "Memory Pruner"),
        ("atomic_note_sync", "Atomic Note Sync"),
        ("lyt_mind_mapper", "LYT Mind Mapper"),
        ("knowledge_backup", "Knowledge Backup")
    ]
    
    for step_id, step_name in step_names:
        if step_id in stats["steps"]:
            result = stats["steps"][step_id]
            status = "✅" if result["success"] else "❌"
            summary += f"│ {status} {step_name:<48} │\n"
        else:
            summary += f"│ ⏭️  {step_name:<48} │\n"
    
    summary += """└─────────────────────────────────────────────────────────────┘
"""
    
    if stats["errors"]:
        summary += "\n⚠️  ERRORS:\n"
        for error in stats["errors"]:
            summary += f"   • {error}\n"
    
    # Vault stats
    if VAULT.exists():
        principles = VAULT / "03-CORTEX" / "01-Principles"
        decisions = VAULT / "03-CORTEX" / "02-Decisions"
        mocs = VAULT / "03-CORTEX" / "00-MOCs"
        
        summary += f"""
📦 VAULT STATUS:
   📁 Principles: {len(list(principles.glob('*.md'))) if principles.exists() else 0} notes
   📁 Decisions:  {len(list(decisions.glob('*.md'))) if decisions.exists() else 0} notes
   📁 MOCs:       {len(list(mocs.glob('*.md'))) if mocs.exists() else 0} maps
"""
    
    success_count = sum(1 for s in stats["steps"].values() if s["success"])
    total = len(stats["steps"])
    
    if not stats["errors"]:
        summary += f"""
╔══════════════════════════════════════════════════════════════╗
║           🎉 UNIFIED SYNC COMPLETE — {success_count}/{total} STEPS              ║
╚══════════════════════════════════════════════════════════════╝
"""
    else:
        summary += f"""
╔══════════════════════════════════════════════════════════════╗
║     ⚠️  UNIFIED SYNC COMPLETED WITH {len(stats['errors'])} ERROR(S)              ║
╚══════════════════════════════════════════════════════════════╝
"""
    
    return summary


def main():
    parser = argparse.ArgumentParser(description="CORTEX + graymatter Unified Memory Sync")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't execute")
    parser.add_argument("--skip-pruner", action="store_true", help="Skip memory pruner")
    parser.add_argument("--skip-backup", action="store_true", help="Skip GitHub backup")
    
    args = parser.parse_args()
    
    stats["start_time"] = datetime.now()
    
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║        🧠 UNIFIED MEMORY SYNC — CORTEX + graymatter         ║
║                                                              ║
║        One pipeline. Both systems. Zero complexity.         ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    if args.dry_run:
        print("⚠️  DRY RUN MODE — No changes will be made\n")
    
    # Run pipeline steps
    step_1_midnight_reflection(dry_run=args.dry_run)
    step_2_memory_pruner(dry_run=args.dry_run, skip=args.skip_pruner)
    step_3_atomic_note_sync(dry_run=args.dry_run)
    step_4_lyt_mind_mapper(dry_run=args.dry_run)
    step_5_knowledge_backup(dry_run=args.dry_run, skip=args.skip_backup)
    
    stats["end_time"] = datetime.now()
    
    # Generate and print summary
    summary = generate_summary()
    print(summary)
    
    # Return exit code
    if stats["errors"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
