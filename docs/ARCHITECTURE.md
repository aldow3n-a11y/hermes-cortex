# CORTEX Architecture

**Version:** 0.1.0  
**Status:** Foundation Phase (Week 1)  
**Target:** Any environment with Python 3.8+ and SQLite

---

## System Overview

CORTEX is a **tier-based memory and knowledge management system** designed to run on minimal infrastructure while providing enterprise-grade features.

### Key Constraints

| Constraint | Limit | Rationale |
|------------|-------|-----------|
| RAM | 512MB minimum | Run on cheap VPS |
| CPU | Single core acceptable | No parallelization required |
| Disk | 100MB for 100K entries | Efficient storage |
| Dependencies | 1-2 packages max | Easy deployment |
| GPU | Not required | Cost savings |
| Internet | Optional | Air-gapped support |

---

## Core Architecture

### Data Flow

```
Agent Conversation → Session End → CORTEX Pipeline → Destinations

Pipeline Steps:
1. Extract content from session JSONL
2. Classify each item (T1/T2/T3/T4)
3. Apply security filter (block credentials)
4. Compute fingerprint (dedup check)
5. Route to destinations based on tier
6. Update reference tracking
```

### Tier Classification

**Keywords + Heuristics** (no ML required):

```python
T1_KEYWORDS = ["decided", "principle", "rule", "policy", "security", 
               "boundary", "never", "always", "must", "critical", "core"]

T2_KEYWORDS = ["project", "task", "milestone", "deadline", "deliverable",
               "sprint", "phase", "in progress", "working on"]

T3_KEYWORDS = ["how to", "workflow", "guide", "tutorial", "learned",
               "discovered", "figured out", "solution", "configured"]

T4_KEYWORDS = ["output", "result", "debug", "error", "trace", "log",
               "command", "executed", "ran", "tested", "queried"]
```

**Scoring:**
- Count keyword matches
- Apply position weights (earlier in text = higher weight)
- Threshold: T1 ≥ 3 matches, T2 ≥ 2, T3 ≥ 1, else T4

### Security Filter

**Pattern matching** (regex):

```python
SECURITY_PATTERNS = [
    r"password\s*[=:]\s*\S+",
    r"api[_-]?key\s*[=:]\s*\S+",
    r"token\s*[=:]\s*\S+",
    r"secret\s*[=:]\s*\S+",
    r"credential",
    r"private[_-]?key",
    r"bearer\s+\S+",
]
```

**Action:** If match found → Block from Obsidian, store encrypted in Hermes-only.

---

## Database Schema

### FTS5 Index (graymatter.db)

```sql
-- Main search index
CREATE VIRTUAL TABLE fts_index USING fts5(
    session_id,
    content,
    tier,
    content_hash,
    created_at,
    updated_at,
    security_flagged,
    security_resolved,
    security_reason
);

-- Reference tracking
CREATE TABLE content_references (
    content_hash TEXT PRIMARY KEY,
    hermes BOOLEAN DEFAULT FALSE,
    graymatter BOOLEAN DEFAULT FALSE,
    obsidian BOOLEAN DEFAULT FALSE,
    ref_count INTEGER DEFAULT 0,
    first_seen DATETIME,
    last_accessed DATETIME
);

-- Tier statistics
CREATE TABLE tier_stats (
    date DATE PRIMARY KEY,
    t1_count INTEGER,
    t2_count INTEGER,
    t3_count INTEGER,
    t4_count INTEGER,
    total_count INTEGER
);

-- Indexes for performance
CREATE INDEX idx_tier ON fts_index(tier);
CREATE INDEX idx_content_hash ON fts_index(content_hash);
CREATE INDEX idx_created_at ON fts_index(created_at);
```

---

## Memory Budget Allocation

### Hermes Memory (8.8K chars)

```
User Profile (user.md):    5.5K — Never evicted
Working Memory (memory.md): 3.3K — Dynamic

Working Memory Breakdown:
├─ Active Projects (T2): 1.5K
├─ Current Rules (T1):   1.0K
├─ Recent Lessons (T1):  0.5K
└─ Session Context (T3): 0.3K
```

### Eviction Algorithm

```python
def evict_if_needed(current_usage, limit=8800):
    if current_usage < limit:
        return
    
    # Tier-first eviction (recency ≠ importance)
    for tier in ["T4", "T3", "T2", "T1"]:
        if current_usage < limit:
            break
        
        max_age = get_tier_max_age(tier)
        evict_by_tier(tier, max_age_days=max_age)
    
    # Last resort: alert user
    if current_usage >= limit:
        alert_user("Memory critical — manual pruning needed")
```

---

## Sync Destinations

| Tier | Hermes Memory | graymatter DB | Obsidian | Archive |
|------|---------------|---------------|----------|---------|
| **T1** | ✓ | ✓ | ✓* | — |
| **T2** | ✓ | ✓ | — | — |
| **T3** | — | ✓ (30d) | — | — |
| **T4** | — | ✓ (7d) | — | — |

*T1 subject to security filter

---

## Error Handling

### Retry Strategy

```python
@retry(max_attempts=5, base_delay=1.0, max_delay=60.0)
def write_to_db(content):
    # May fail if DB locked
    db.execute("INSERT INTO ...", content)
```

### Dead Letter Queue

```
Location: ~/.cortex/dlq/
Format: JSONL (one file per day)
Processing: Daily at 4 AM (retry + manual review)
```

### Circuit Breaker

```python
class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=300):
        self.state = "CLOSED"  # or "OPEN", "HALF-OPEN"
        ...
    
    def call(self, fn):
        if self.state == "OPEN":
            raise CircuitBreakerOpenError()
        try:
            return fn()
        except Exception:
            self.failure_count += 1
            if self.failure_count >= self.threshold:
                self.state = "OPEN"
                alert()
            raise
```

---

## Performance Targets

| Operation | Target | Current | Status |
|-----------|--------|---------|--------|
| FTS5 search | < 100ms | ~50ms | ✅ |
| Fingerprint computation | < 10ms | ~2ms | ✅ |
| Tier classification | < 50ms | ~20ms | ✅ |
| DB insert (batch 100) | < 1s | ~0.5s | ✅ |
| Memory eviction | < 100ms | ~30ms | ✅ |
| Obsidian sync (10 notes) | < 5s | ~2s | ✅ |

---

## Deployment Scenarios

### Scenario 1: $5 VPS (DigitalOcean Linode)

```
Specs: 1GB RAM, 1 CPU, 25GB SSD
OS: Ubuntu 22.04
Python: 3.10
Storage: SQLite DB + logs
Cron: Daily midnight reflection
```

**Expected performance:** All targets met

### Scenario 2: Raspberry Pi 4

```
Specs: 4GB RAM, 4 CPU, SD card
OS: Raspberry Pi OS
Python: 3.9
Storage: SQLite DB + USB drive for logs
Cron: Daily processing
```

**Expected performance:** All targets met

### Scenario 3: Docker Container

```
Specs: 512MB RAM limit, 0.5 CPU
OS: Alpine Linux (python:3.10-alpine)
Python: 3.10
Storage: Volume-mounted SQLite DB
Cron: Internal scheduler
```

**Expected performance:** Search ~80ms (still acceptable)

### Scenario 4: Air-Gapped System

```
Specs: Any x86_64 machine
OS: Any Linux
Python: 3.8+
Storage: Local SQLite DB
Network: None required
```

**Expected performance:** All targets met (no network calls)

---

## Testing Strategy

### Unit Tests

```bash
# Run all tests
pytest tests/

# Coverage report
pytest --cov=cortex tests/
```

### Integration Tests

```bash
# Test full pipeline
python tests/integration/test_full_pipeline.py

# Test with staging vault
CORTEX_STAGING=1 python tests/integration/test_obsidian_sync.py
```

### Performance Tests

```bash
# Benchmark search
python tests/benchmarks/search_latency.py

# Benchmark indexing
python tests/benchmarks/indexing_speed.py
```

---

## Monitoring

### Health Check

```bash
cortex health-check

# Output:
✅ hermes_memory: healthy — 1,560 / 8,800 chars (17.7%)
✅ graymatter: healthy — 7,261 entries, 18.91 MB
✅ obsidian: healthy — 342 notes, 5 MOCs
⚠️  dlq: warning — 3 items
```

### Status Dashboard

```bash
cortex status

# Output:
Memory Usage:     1,560 / 8,800 chars (17.7%)
User Profile:     2,340 / 5,500 chars (42.5%)
graymatter:       7,261 entries
├─ T1: 1,234
├─ T2: 2,345
├─ T3: 2,890
└─ T4: 792
Obsidian:         342 notes, 5 MOCs
DLQ:              3 items
```

---

## Future Enhancements (Post-v1.0)

### v1.1: Multi-Agent Support
- Claude Code integration
- Codex CLI integration
- Agent SDK for custom integrations

### v1.2: Advanced Classification
- Embedding-based tier classification (optional)
- Confidence scoring
- Manual review queue for low-confidence items

### v1.3: Multi-Tenant
- User isolation
- Per-user quotas
- Shared knowledge base option

### v2.0: Distributed CORTEX
- SQLite → PostgreSQL (for multi-tenant)
- Redis for caching
- Horizontal scaling

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.1.0 | 2026-04-08 | Initial architecture, Phase 1 foundation |

---

**CORTEX — Intelligence through architecture, not compute.**
