#!/usr/bin/env python3
"""
CORTEX Cron Job Test Script

Verifies all automated jobs can run successfully.
Use this before relying on cron automation.

Usage:
    python test-cron-jobs.py    # Run all tests
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

CORTEX_SCRIPTS = Path(__file__).parent / "scripts"

TESTS = [
    {
        "name": "Midnight Reflection",
        "command": ["python", str(CORTEX_SCRIPTS / "midnight-reflection.py"), "--dry-run"],
        "timeout": 60
    },
    {
        "name": "Memory Pruner",
        "command": ["python", str(CORTEX_SCRIPTS / "memory-pruner.py"), "--dry-run"],
        "timeout": 30
    },
    {
        "name": "Atomic Note Creator",
        "command": ["python", str(CORTEX_SCRIPTS / "atomic-note-creator.py"), "--status"],
        "timeout": 30
    },
    {
        "name": "LYT Mind Mapper",
        "command": ["python", str(CORTEX_SCRIPTS / "lyt-mind-mapper.py"), "--status"],
        "timeout": 30
    },
    {
        "name": "CORTEX CLI Status",
        "command": ["python", str(CORTEX_SCRIPTS / "cortex-cli.py"), "status"],
        "timeout": 30
    },
    {
        "name": "CORTEX CLI Health Check",
        "command": ["python", str(CORTEX_SCRIPTS / "cortex-cli.py"), "health-check"],
        "timeout": 30
    }
]


def run_test(test: dict) -> bool:
    """Run a single test."""
    print(f"\n🧪 Testing: {test['name']}")
    print(f"   Command: {' '.join(test['command'])}")
    
    try:
        result = subprocess.run(
            test["command"],
            capture_output=True,
            text=True,
            timeout=test["timeout"]
        )
        
        if result.returncode == 0:
            print(f"   ✅ PASSED ({result.returncode})")
            return True
        else:
            print(f"   ❌ FAILED ({result.returncode})")
            if result.stderr:
                print(f"   Error: {result.stderr[:200]}")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"   ⏱️  TIMEOUT (> {test['timeout']}s)")
        return False
    except Exception as e:
        print(f"   ❌ ERROR: {e}")
        return False


def main():
    print(f"🧠 CORTEX Cron Job Test — {datetime.now().isoformat()}")
    print("=" * 60)
    
    results = []
    
    for test in TESTS:
        passed = run_test(test)
        results.append((test["name"], passed))
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Summary:")
    
    passed_count = sum(1 for _, p in results if p)
    total = len(results)
    
    for name, passed in results:
        status = "✅" if passed else "❌"
        print(f"   {status} {name}")
    
    print(f"\n   Total: {passed_count}/{total} passed ({passed_count/total*100:.0f}%)")
    
    if passed_count == total:
        print("\n✅ All cron jobs ready for automation!")
        sys.exit(0)
    else:
        print(f"\n⚠️  {total - passed_count} job(s) need attention before automation")
        sys.exit(1)


if __name__ == "__main__":
    main()
