# Plug & Play Architecture — Modular Monitoring Agent

## Overview

This document describes a modular, plug-and-play evolution of the Proactive Monitoring Agent. The core idea: decouple **signal collection** and **action execution** from the **analysis engine**, so that each collector and each integration runs as an independent, swappable component.

Any organization can mix and match:
- **Inbound**: CloudWatch, Splunk, Prometheus, Datadog, custom sources
- **Analysis**: The existing LangGraph agent (unchanged core)
- **Outbound**: ServiceNow, Jira, Slack, PagerDuty, custom MCP servers, Splunk SOAR bots

All scenarios feed into OpenSearch for RAG-based continuous learning regardless of source or destination.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              INBOUND COLLECTOR PODS                                  │
│                          (each runs as its own K8s Deployment)                        │
│                                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │  CloudWatch   │  │   Splunk     │  │  Prometheus  │  │  Custom Collector        │ │
│  │  Collector    │  │   Collector  │  │  Collector   │  │  (gRPC/REST/MCP)         │ │
│  │  Pod          │  │   Pod        │  │  Pod         │  │  Pod                     │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └────────────┬─────────────┘ │
│         │                  │                  │                       │               │
│         └──────────────────┴─────────┬────────┴───────────────────────┘               │
│                                      │                                                │
│                              Unified Event Bus                                        │
│                         (SQS Queue / Redis Stream)                                    │
└──────────────────────────────────────┬──────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                            ANALYSIS ENGINE (Core Agent)                               │
│                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐ │
│  │                         LangGraph Workflow                                       │ │
│  │                                                                                  │ │
│  │   Ingest ──► Correlate ──► RAG Retrieve ──► Analyze ──► Classify ──► Route      │ │
│  │     │      (cross-source,       │              │            │           │        │ │
│  │     │       parameterized       ▼              ▼            ▼           ▼        │ │
│  │     │       window)       OpenSearch       Bedrock     Severity    Action Router │ │
│  │     │                  (runbooks + history  Claude     + Category  (configurable │ │
│  │     │                   + correlation RAG)  (or RAG               routing rules) │ │
│  │     │                         ▲             fast path)                  │        │ │
│  │     │                         │                                        ▼        │ │
│  │     ▼                         │                                     Store ──────┘ │
│  │  source_system tracked ──► preserved in incident ──► used for routing decisions  │ │
│  │                               │                                                  │ │
│  │                               └──► Store incident + correlation pattern           │ │
│  │                                    in OpenSearch (learning loop)                  │ │
│  └─────────────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────┬──────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                           OUTBOUND INTEGRATION PODS                                   │
│                        (each runs as its own K8s Deployment)                          │
│                                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │  ServiceNow   │  │   Jira       │  │  PagerDuty   │  │  Custom Integration      │ │
│  │  Integration  │  │   Integration│  │  Integration │  │  (MCP Server / Bot)      │ │
│  │  Pod          │  │   Pod        │  │  Pod         │  │  Pod                     │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └────────────┬─────────────┘ │
│         │                  │                  │                       │               │
│         └──────────────────┴─────────┬────────┴───────────────────────┘               │
│                                      │                                                │
│                          SRE Feedback Loop                                             │
│                  (ticket sync / email reply / dashboard UI)                            │
│                              updates confidence scores                                │
└──────────────────────────────────────┬──────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                           KNOWLEDGE STORE (OpenSearch)                                │
│                                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │  Runbooks     │  │  Case History│  │  Incidents   │  │  Correlation Patterns    │ │
│  │  Index        │  │  Index       │  │  Index       │  │  Index (with scores)     │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────────────────┘ │
│                                                                                      │
│                    ▲ RAG Retrieve reads from here                                     │
│                    ▲ Store node writes here                                           │
│                    ▲ SRE Feedback updates confidence scores here                      │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Source Awareness

The agent always knows where every event came from. `source_system` and `source_collector` are mandatory fields. This identity is preserved end-to-end:

- **Routing decisions**: Events from Splunk → Splunk SOAR, events from CloudWatch → ServiceNow
- **Correlation context**: CloudWatch alarm + Prometheus alert about the same host
- **RAG scoping**: Past incidents searchable by source or across all sources
- **Audit trail**: Every incident traces back to exactly which collector(s) reported it

---

## Unified Event Schema

Every collector normalizes signals into this common schema before publishing to the event bus:

```json
{
  "event_id": "string (UUID)",
  "source_system": "cloudwatch | splunk | prometheus | datadog | custom",
  "source_collector": "string (pod/instance identifier)",
  "event_type": "alarm | metric | log | alert | custom",
  "timestamp": "ISO 8601",
  "severity_hint": "critical | high | medium | low | info | null",
  "resource": {
    "id": "string", "type": "string", "region": "string",
    "namespace": "string", "labels": {}
  },
  "signal": {
    "title": "string", "description": "string",
    "metric_name": "string", "metric_value": 0, "threshold": 0,
    "unit": "string", "state": "ALARM | FIRING | RESOLVED",
    "raw_payload": {}
  },
  "context": {
    "tags": { "key": "value" },
    "correlation_id": "string (optional, for grouping related events)",
    "source_url": "string (optional, link back to source system)"
  }
}
```

The `raw_payload` field preserves the original event from the source system so no information is lost during normalization.

---

## Cross-Source Correlation Engine

The agent correlates signals from different sources into a single incident when they point to the same underlying issue.

Example scenario:
- CloudWatch reports high CPU on EC2 instance `i-0abc123`
- Prometheus reports pod restarts on the same host
- Splunk shows error log spikes from the application running on that host

The agent sees all three within the correlation window and groups them into one incident.

### Correlation Window (Parameterized)

The correlation window is a configurable parameter that controls how far back the agent looks when grouping related events:

```yaml
# In monitoring-agent-config ConfigMap
data:
  CORRELATION_WINDOW_SECONDS: "300"    # 5 minutes (default)
  # Valid range: 60 - 600 (1 to 10 minutes)
  # Shorter = fewer false correlations, might miss slow-cascading failures
  # Longer = catches cascading failures, but may over-group unrelated events
```

### Correlation Logic

```python
class CorrelationEngine:
    """
    Groups events from multiple sources that likely represent the same
    underlying issue, within a configurable time window.
    """

    def __init__(self, config: Dict[str, Any]):
        # Parameterized: read from config, default 300s (5 min), max 600s (10 min)
        self.window_seconds = min(
            int(config.get("correlation_window_seconds", 300)),
            600  # hard cap at 10 minutes
        )

    def correlate(self, events: List[UnifiedEvent]) -> List[CorrelatedGroup]:
        """
        Group events into correlated incident groups.

        Events are correlated if they fall within the correlation window AND
        match on at least one correlation key.
        """
        groups = []
        window = timedelta(seconds=self.window_seconds)

        for event in sorted(events, key=lambda e: e.timestamp):
            matched_group = self._find_matching_group(event, groups, window)
            if matched_group:
                matched_group.add(event)
            else:
                groups.append(CorrelatedGroup(seed_event=event))

        return groups

    def _find_matching_group(self, event, groups, window):
        """
        Correlation keys (checked in priority order — first match wins):
        1. Explicit correlation_id (if set by collector)
        2. Same resource.id across sources within time window
        3. Same resource.namespace + similar signal.title within time window
        4. Semantic similarity via OpenSearch knn embedding (correlation patterns index)
        """
        for group in groups:
            if not group.within_window(event.timestamp, window):
                continue
            if (event.context.correlation_id
                    and event.context.correlation_id == group.correlation_id):
                return group
            if event.resource.id and event.resource.id in group.resource_ids:
                return group
            if (event.resource.namespace
                    and event.resource.namespace in group.namespaces
                    and self._titles_similar(event.signal.title, group.titles)):
                return group
        return None
```

---

## Correlation Patterns in RAG (Confidence-Scored)

Every correlated incident — where the agent grouped events from multiple sources — is stored in OpenSearch with a **correlation confidence score**. This allows the RAG fast path to recognize known multi-source patterns in the future and skip Bedrock analysis entirely.

### How It Works

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                  CORRELATION → RAG LEARNING LOOP                              │
│                                                                              │
│  1. Agent correlates events from CloudWatch + Prometheus + Splunk            │
│     into a single incident                                                   │
│                          │                                                   │
│                          ▼                                                   │
│  2. Incident is classified, RCA generated, actions routed                    │
│                          │                                                   │
│                          ▼                                                   │
│  3. Stored in OpenSearch "correlation-patterns" index with:                   │
│     - The source combination (e.g., ["cloudwatch", "prometheus"])            │
│     - The signal fingerprint (normalized titles + resource types)            │
│     - The generated root cause analysis                                      │
│     - An initial correlation confidence score                                │
│     - times_seen = 1, times_confirmed = 0                                    │
│                          │                                                   │
│                          ▼                                                   │
│  4. SRE resolves the incident (via ticket, email, or dashboard)              │
│     → Feedback updates times_confirmed / times_corrected                     │
│     → Confidence score recalculated                                          │
│                          │                                                   │
│                          ▼                                                   │
│  5. NEXT TIME similar signals arrive from the same source combination:       │
│     - RAG retrieves the stored pattern                                       │
│     - If confidence score >= RAG_CONFIDENCE_THRESHOLD (e.g., 0.85):          │
│       → Skip Bedrock, reuse stored RCA + classification + actions            │
│     - If confidence score < threshold:                                       │
│       → Still pass to Bedrock, but include the pattern as context            │
└──────────────────────────────────────────────────────────────────────────────┘
```

### OpenSearch Correlation Patterns Index Schema

```json
{
  "index": "correlation-patterns",
  "document": {
    "pattern_id": "string (hash of source_systems + signal_fingerprint)",
    "source_systems": ["cloudwatch", "prometheus"],
    "signal_fingerprint": {
      "titles_normalized": ["high cpu utilization", "pod crashloopbackoff"],
      "resource_types": ["ec2", "pod"],
      "categories": ["performance", "availability"],
      "title_embedding": [0.12, 0.45, "...vector..."]
    },

    "correlation_confidence": 0.92,
    "times_seen": 7,
    "times_confirmed": 5,
    "times_corrected": 1,
    "last_seen": "2026-03-10T14:30:00Z",

    "stored_analysis": {
      "root_cause": "Memory leak causing OOM kills, triggering pod restarts and CPU spikes from GC pressure",
      "category": "performance",
      "priority": "P2",
      "recommended_actions": [
        "Roll back to previous deployment version",
        "Scale out temporarily to handle load",
        "Review heap dumps from affected instances"
      ]
    },

    "resolution_history": [
      {
        "incident_id": "INC-2026-0287",
        "resolved_at": "2026-02-18T11:15:00Z",
        "resolution": "Rolled back auth-service from v2.1.0 to v2.0.9",
        "time_to_resolve_minutes": 45,
        "rca_was_correct": true,
        "sre_feedback": "confirmed"
      },
      {
        "incident_id": "INC-2026-0312",
        "resolved_at": "2026-03-05T09:30:00Z",
        "resolution": "Identified and fixed memory leak in connection pool",
        "time_to_resolve_minutes": 30,
        "rca_was_correct": true,
        "sre_feedback": "confirmed"
      }
    ]
  }
}
```

### Confidence Score Calculation

The confidence score evolves over time based on how often the pattern is seen and how often the stored analysis turns out to be correct:

```python
def calculate_correlation_confidence(pattern: Dict) -> float:
    """
    Factors:
    - knn_score: Semantic similarity of current signals to stored fingerprint
    - source_match: Exact match of source_systems boosts score
    - accuracy: times_confirmed / times_seen (SRE feedback ratio)
    - recency: More recent patterns weighted higher, decays over weeks
    """
    knn_score = pattern["_score"]
    source_match = 1.0 if exact_source_match else 0.8
    accuracy = pattern["times_confirmed"] / max(pattern["times_seen"], 1)
    recency = decay_factor(pattern["last_seen"])  # 1.0 if recent, decays over weeks

    confidence = (
        0.40 * knn_score +
        0.15 * source_match +
        0.25 * accuracy +
        0.20 * recency
    )
    return min(confidence, 1.0)
```

### RAG Fast Path with Correlation Patterns

When the agent ingests events, the RAG retrieval step now searches two indices:
1. **case-history** (existing) — individual past incidents
2. **correlation-patterns** (new) — multi-source correlation patterns with confidence scores

```python
async def _retrieve_context_node(self, state: AgentState) -> AgentState:
    """Retrieve relevant context including correlation patterns."""
    
    event_descriptions = " ".join(e.description[:200] for e in state["events"][:5])
    source_systems = list(set(e.source_system for e in state["events"]))
    
    # Search both indices
    runbooks = await self.rag.search_runbooks(event_descriptions)
    similar_incidents = await self.rag.search_similar_incidents(event_descriptions)
    
    # NEW: Search correlation patterns, boosting matches with same source combination
    correlation_patterns = await self.rag.search_correlation_patterns(
        query=event_descriptions,
        source_systems=source_systems,  # boost patterns from same sources
    )
    
    state["runbooks"] = runbooks
    state["similar_incidents"] = similar_incidents
    state["correlation_patterns"] = correlation_patterns
    
    return state
```

In the analyze node, correlation patterns are checked first (highest confidence), then individual case history, then Bedrock as fallback:

```python
async def _analyze_node(self, state: AgentState) -> AgentState:
    """Analyze with correlation pattern fast path."""
    
    threshold = self.rag_confidence_threshold
    
    # Priority 1: Check correlation patterns (multi-source patterns)
    patterns = state.get("correlation_patterns", [])
    if patterns and patterns[0].get("correlation_confidence", 0) >= threshold:
        top_pattern = patterns[0]
        print(f"Correlation RAG fast path: pattern {top_pattern['pattern_id']} "
              f"confidence {top_pattern['correlation_confidence']:.3f}")
        # Reuse stored RCA, category, priority, actions from the pattern
        return self._build_from_pattern(state, top_pattern)
    
    # Priority 2: Check individual case history (existing fast path)
    similar = state.get("similar_incidents", [])
    if similar and similar[0].get("_score", 0) >= threshold:
        # Existing RAG fast path...
        ...
    
    # Priority 3: Full Bedrock analysis
    ...
```

### Storing New Correlation Patterns

After an incident is created from correlated multi-source events, the store node indexes the correlation pattern:

```python
async def _store_node(self, state: AgentState) -> AgentState:
    """Store incidents and correlation patterns for learning."""
    
    for incident in state.get("incidents", []):
        # Store the incident itself (existing behavior)
        await self.rag.index_incident(incident.to_dict())
        
        # NEW: If this incident was correlated from multiple sources,
        # store/update the correlation pattern
        if len(incident.source_systems) > 1:
            await self.rag.upsert_correlation_pattern({
                "pattern_id": self._compute_pattern_id(incident),
                "source_systems": incident.source_systems,
                "signal_fingerprint": {
                    "titles_normalized": [e["signal"]["title"] for e in incident.source_events],
                    "resource_types": list(set(e["resource"]["type"] for e in incident.source_events)),
                    "categories": [incident.category.value],
                },
                "stored_analysis": {
                    "root_cause": incident.root_cause_analysis,
                    "category": incident.category.value,
                    "priority": incident.priority.value,
                    "recommended_actions": incident.recommended_actions,
                },
                "correlation_confidence": incident.anomaly_score.confidence if incident.anomaly_score else 0.5,
                "times_seen": 1,       # incremented on upsert if pattern exists
                "times_confirmed": 0,  # incremented when resolution confirms the RCA
                "times_corrected": 0,  # incremented when SRE says RCA was wrong
                "last_seen": datetime.now(timezone.utc).isoformat(),
            })
    
    return state
```

### How Index Scores Originate and Evolve

The two OpenSearch indices use different scoring mechanisms, and it's important to understand where each score comes from initially vs. how it changes over time.

**Incidents Index (`case-history`) — Score = OpenSearch knn similarity**

When the store node writes an incident to `case-history`, it generates a vector embedding from the incident's normalized title and description (using Bedrock Titan Embeddings). The incident itself has no "score" — it's just a document. The `_score` only appears at retrieval time, when the RAG retrieve step searches `case-history` with the current event's embedding. OpenSearch returns a cosine similarity score (0.0–1.0) representing how semantically similar the current event is to each stored incident. A score of 0.92 means "this new event looks very similar to that past incident." This score is stateless — it's computed fresh on every search and doesn't change based on feedback.

```
Store time:   incident + embedding → indexed in case-history (no score stored)
Retrieve time: current event embedding → knn search → _score = cosine similarity
```

**Correlation Patterns Index (`correlation-patterns`) — Score = composite confidence**

Correlation patterns have a stored `correlation_confidence` field that evolves over time. Here's the lifecycle:

1. **First occurrence**: Pattern is created with `correlation_confidence = incident.anomaly_score.confidence` (from Bedrock's analysis, typically 0.5–0.8). `times_seen = 1`, `times_confirmed = 0`. At this point the pattern will NOT hit the fast path because the confidence is below the threshold (0.85) and accuracy is 0/1 = 0.

2. **Subsequent retrievals**: When the RAG retrieve step searches `correlation-patterns`, OpenSearch returns a knn `_score` (same cosine similarity as above). The `calculate_correlation_confidence` formula then combines this retrieval-time knn score with the stored pattern's accuracy and recency to produce the final confidence used for the fast path decision.

3. **After SRE feedback**: When an SRE confirms or corrects the RCA, `times_confirmed` or `times_corrected` is updated, and `correlation_confidence` is recalculated and written back to OpenSearch. This is the only time the stored confidence value changes.

```
First store:     confidence = Bedrock's anomaly score (e.g., 0.65)
                 times_seen=1, times_confirmed=0 → accuracy=0 → won't hit fast path

SRE confirms:    times_confirmed=1 → accuracy=1/1=1.0 → confidence recalculated
                 (but still only seen once, so recency and knn dominate)

Seen 5x, confirmed 4x:  accuracy=4/5=0.8, recent, good knn match
                         → confidence likely >= 0.85 → hits fast path
```

This means a pattern must be both frequently seen AND confirmed by SREs before it earns enough confidence to skip Bedrock. New or unvalidated patterns always go through full analysis.

---

## SRE Feedback Loop

The confidence scores only work if the system knows whether its RCA was actually correct. Here's how SREs provide that feedback — through three channels, from lowest-friction to most detailed:

### Channel 1: Ticket Resolution Sync (Automatic — Zero Effort)

When the SRE resolves the ServiceNow/Jira ticket, the integration pod syncs the resolution back:

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────────────┐
│  SRE resolves │     │  Integration pod  │     │  Agent updates       │
│  ticket in    │────►│  polls ticket    │────►│  OpenSearch pattern   │
│  ServiceNow   │     │  status change   │     │  times_seen += 1     │
│               │     │  + resolution    │     │  + resolution_history │
└──────────────┘     └──────────────────┘     └──────────────────────┘
```

The integration pod periodically checks open tickets for status changes. When a ticket moves to "Resolved" or "Closed":
- The resolution notes are extracted
- The agent compares the SRE's actual resolution to the stored RCA using a simple heuristic:
  - If the resolution text is semantically similar to the stored RCA → `rca_was_correct = true`, `times_confirmed += 1`
  - If the resolution text contradicts or describes a different root cause → `rca_was_correct = false`, `times_corrected += 1`
  - If unclear → no change to confirmed/corrected counts (conservative)

This is the default, zero-effort path. SREs just resolve tickets as they normally would.

### Channel 2: Email Reply Feedback (Low Effort)

The notification email already includes the RCA and recommended actions. Add a simple feedback section at the bottom:

```
══════════════════════════════════════════════════════════════════
Was this Root Cause Analysis correct?

  ✅ Yes, RCA was correct:
     Reply with "CONFIRM" or click: https://dashboard:9493/api/feedback/INC-2026-0312?rca=correct

  ❌ No, RCA was wrong:
     Reply with "INCORRECT: <actual root cause>"
     or click: https://dashboard:9493/api/feedback/INC-2026-0312?rca=incorrect

  📝 Partially correct:
     Reply with "PARTIAL: <what was different>"
══════════════════════════════════════════════════════════════════
```

The agent's email handler (or a simple Lambda on SES inbound) parses the reply:
- "CONFIRM" → `times_confirmed += 1`
- "INCORRECT: ..." → `times_corrected += 1`, stores the SRE's actual root cause as a correction
- "PARTIAL: ..." → `times_confirmed += 0.5` (partial credit), stores the note

### Channel 3: Dashboard Feedback UI (Most Detailed)

The monitoring dashboard shows resolved incidents with a feedback panel:

```
┌─────────────────────────────────────────────────────────────────┐
│  Incident INC-2026-0312 — RESOLVED                              │
│                                                                  │
│  Agent's RCA:                                                    │
│  "Memory leak causing OOM kills, triggering pod restarts         │
│   and CPU spikes from GC pressure"                               │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Was this RCA correct?                                       │ │
│  │                                                              │ │
│  │  [✅ Correct]  [⚠️ Partially Correct]  [❌ Incorrect]       │ │
│  │                                                              │ │
│  │  Actual root cause (if different):                           │ │
│  │  ┌──────────────────────────────────────────────────────┐   │ │
│  │  │                                                       │   │ │
│  │  └──────────────────────────────────────────────────────┘   │ │
│  │                                                              │ │
│  │  What actions actually resolved it?                          │ │
│  │  ┌──────────────────────────────────────────────────────┐   │ │
│  │  │                                                       │   │ │
│  │  └──────────────────────────────────────────────────────┘   │ │
│  │                                                              │ │
│  │  [Submit Feedback]                                           │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Feedback API

All three channels funnel into the same API endpoint on the agent:

```
POST /api/feedback/{incident_id}
{
  "rca_correct": true | false | "partial",
  "actual_root_cause": "string (optional, if RCA was wrong)",
  "actual_resolution": "string (optional, what actually fixed it)",
  "feedback_source": "ticket_sync | email_reply | dashboard_ui",
  "sre_id": "string (optional)"
}
```

The agent processes this feedback:

```python
async def process_feedback(self, incident_id: str, feedback: Dict) -> None:
    """
    Update correlation pattern confidence based on SRE feedback.
    """
    # Find the correlation pattern this incident belongs to
    pattern = await self.rag.find_pattern_by_incident(incident_id)
    if not pattern:
        return

    rca_correct = feedback["rca_correct"]

    if rca_correct == True:
        pattern["times_confirmed"] += 1
    elif rca_correct == False:
        pattern["times_corrected"] += 1
        # Store the SRE's actual root cause — this becomes the new
        # stored_analysis if corrections outnumber confirmations
        if feedback.get("actual_root_cause"):
            pattern["resolution_history"].append({
                "incident_id": incident_id,
                "rca_was_correct": False,
                "sre_actual_root_cause": feedback["actual_root_cause"],
                "sre_actual_resolution": feedback.get("actual_resolution", ""),
            })
    elif rca_correct == "partial":
        pattern["times_confirmed"] += 0.5

    # If corrections > confirmations, the stored RCA is probably wrong.
    # Replace it with the most recent SRE-provided root cause.
    if pattern["times_corrected"] > pattern["times_confirmed"]:
        latest_correction = next(
            (r for r in reversed(pattern["resolution_history"])
             if r.get("sre_actual_root_cause")),
            None
        )
        if latest_correction:
            pattern["stored_analysis"]["root_cause"] = latest_correction["sre_actual_root_cause"]
            print(f"Pattern {pattern['pattern_id']}: RCA replaced by SRE correction")

    # Recalculate confidence and update in OpenSearch
    pattern["correlation_confidence"] = calculate_correlation_confidence(pattern)
    await self.rag.upsert_correlation_pattern(pattern)
```

### Feedback Priority

The three channels have different reliability levels:

| Channel | Effort | Reliability | When It Fires |
|---------|--------|-------------|---------------|
| Ticket Resolution Sync | Zero (automatic) | Medium — heuristic-based text comparison | When ticket is resolved/closed |
| Email Reply | Low (one-word reply) | High — explicit SRE judgment | When SRE replies to notification |
| Dashboard UI | Medium (form fill) | Highest — detailed with context | When SRE reviews in dashboard |

If multiple channels provide feedback for the same incident, the highest-reliability source wins. Dashboard UI overrides email reply, which overrides ticket sync.

### What Happens Without Feedback

If no SRE feedback is received (common for low-priority incidents), the pattern still gets `times_seen += 1` but `times_confirmed` stays the same. This naturally lowers the accuracy ratio over time, which lowers the confidence score. Patterns that are never confirmed gradually fall below the RAG threshold and stop hitting the fast path — the system becomes conservative about unvalidated patterns.

---

## Collector Plugin Architecture

### Collector Interface

Every collector pod implements the same interface:

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any

class CollectorPlugin(ABC):
    """Base interface all collector plugins must implement."""

    @abstractmethod
    async def collect(self) -> List[Dict[str, Any]]:
        """
        Collect signals from the source system.
        Returns list of events in Unified Event Schema format.
        Must set source_system and source_collector on every event.
        """
        ...

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """Return health status of the collector and its source connection."""
        ...

    @abstractmethod
    def source_system(self) -> str:
        """Return the source system identifier (e.g., 'cloudwatch', 'splunk')."""
        ...
```

### Collector Registration

Collectors register themselves with the agent via a lightweight registry. On startup, each collector pod:

1. Publishes its metadata to a shared ConfigMap or service discovery endpoint
2. Begins polling its source system on its own schedule
3. Normalizes events to the Unified Event Schema (including mandatory `source_system`)
4. Publishes to the shared event bus (SQS or Redis Stream)

```yaml
# Example: collector-manifest.yaml (per collector)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: collector-splunk
  namespace: monitoring
  labels:
    app: monitoring-collector
    collector-type: splunk
spec:
  replicas: 1
  selector:
    matchLabels:
      app: monitoring-collector
      collector-type: splunk
  template:
    metadata:
      labels:
        app: monitoring-collector
        collector-type: splunk
    spec:
      serviceAccountName: monitoring-collector-sa
      containers:
        - name: splunk-collector
          image: ${ECR_REPO}/collector-splunk:latest
          env:
            - name: EVENT_BUS_URL
              valueFrom:
                configMapKeyRef:
                  name: monitoring-agent-config
                  key: EVENT_BUS_URL
            - name: SPLUNK_HEC_URL
              valueFrom:
                secretKeyRef:
                  name: collector-splunk-secrets
                  key: SPLUNK_HEC_URL
            - name: COLLECTION_INTERVAL
              value: "60"
```

### Example Collectors

| Collector | Source | Signal Types | Notes |
|-----------|--------|-------------|-------|
| CloudWatch | AWS CloudWatch | Alarms, Metrics, Logs, Insights | Existing — refactored into standalone pod |
| Splunk | Splunk Enterprise/Cloud | Saved searches, alerts, notable events | Uses Splunk REST API or HEC |
| Prometheus | Prometheus/Thanos | Firing alerts from Alertmanager | Polls Alertmanager API |
| Datadog | Datadog | Monitors, events | Uses Datadog API v2 |
| Grafana | Grafana Alerting | Alert rules | Webhook receiver or API polling |
| Custom gRPC | Any system | Any | gRPC server that accepts push-based signals |
| Custom REST | Any system | Any | REST endpoint that accepts POST events |

---

## Integration Plugin Architecture

### Integration Interface

Every outbound integration pod implements:

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from models.events import Incident

class IntegrationPlugin(ABC):
    """Base interface all integration plugins must implement."""

    @abstractmethod
    async def create_ticket(self, incident: Incident) -> Dict[str, Any]:
        """Create a ticket/incident in the target system. Returns ticket metadata."""
        ...

    @abstractmethod
    async def update_ticket(self, ticket_id: str, update: Dict[str, Any]) -> bool:
        """Update an existing ticket."""
        ...

    @abstractmethod
    async def notify(self, incident: Incident) -> Dict[str, Any]:
        """Send notification for the incident. Returns delivery status."""
        ...

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """Return health status of the integration and its target connection."""
        ...

    @abstractmethod
    def system_name(self) -> str:
        """Return the target system identifier (e.g., 'servicenow', 'jira')."""
        ...
```

### Action Router (Configurable Outbound Routing)

The solution supports many outbound integrations, but any given adopter will typically use only one ticketing system and one or two notification channels. The routing configuration makes this explicit — adopters declare exactly which integrations they use, and only those pods need to be deployed.

The Action Router reads the incident's `source_systems` and `category` to decide where to send it. Here's how `source_system` flows through the routing decision:

```python
class ActionRouter:
    """
    Routes incidents to the correct ticketing and notification integrations
    based on the routing config and the incident's source_system.
    """

    def __init__(self, routing_config: Dict):
        self.config = routing_config

    def resolve_ticketing_target(self, incident: Incident) -> str:
        """
        Determine which ticketing system handles this incident.

        1. Check overrides — match on source_system or resource labels
        2. Fall back to the default ticketing target
        """
        for override in self.config["ticketing"].get("overrides", []):
            match = override["match"]

            # source_system match: "events from Splunk go to Splunk SOAR"
            if "source_system" in match:
                if match["source_system"] in incident.source_systems:
                    return override["target"]

            # resource label match: "platform team uses Jira"
            if "resource_labels" in match:
                if self._labels_match(incident, match["resource_labels"]):
                    return override["target"]

        return self.config["ticketing"]["default"]

    def resolve_notification_targets(self, incident: Incident) -> List[str]:
        """
        Determine which notification channels receive this incident.
        Matches incident priority against per-priority routing rules.
        Only returns targets that are in the 'enabled' list.
        """
        enabled = set(self.config["notifications"]["enabled"])
        for rule in self.config["notifications"]["rules"]:
            if incident.priority.value in rule["priority"]:
                return [t for t in rule["targets"] if t in enabled]
        return list(enabled)  # fallback: all enabled channels
```

The routing config lives in a ConfigMap so it can be changed without rebuilding anything:

```yaml
# config/action-routing-rules.yaml
# ──────────────────────────────────────────────────────────────────────
# OUTBOUND ROUTING CONFIGURATION
#
# Each adopter configures ONLY the integrations they actually use.
# Only the pods for enabled integrations need to be deployed.
# ──────────────────────────────────────────────────────────────────────

routing:

  # ── TICKETING ──────────────────────────────────────────────────────
  # Which system creates and manages tickets/incidents.
  # Most adopters will have exactly ONE ticketing system.
  ticketing:
    # The default ticketing target for all incidents.
    # Options: servicenow | jira | splunk-soar | mcp-custom | none
    default: servicenow

    # Optional: override the default for specific sources or teams.
    # If no overrides match, the default is used.
    overrides:
      # Example: events originating from Splunk go to Splunk SOAR instead
      - match:
          source_system: splunk
        target: splunk-soar

      # Example: the platform team uses Jira instead of ServiceNow
      - match:
          resource_labels:
            team: platform
        target: jira

  # ── NOTIFICATIONS ──────────────────────────────────────────────────
  # Where alerts/notifications are sent. Can fan out to multiple targets.
  # Adopters enable only the channels they use.
  notifications:
    # List of enabled notification channels.
    # Only these pods need to be deployed.
    enabled: [ses-email]    # Minimal: just email
    # enabled: [ses-email, slack]                  # Email + Slack
    # enabled: [ses-email, slack, pagerduty]       # Full stack

    # Per-priority routing: which enabled channels get which priorities.
    # Targets listed here MUST be in the 'enabled' list above.
    rules:
      - priority: [P1, P2]
        targets: [ses-email]          # Add pagerduty, slack here if enabled
      - priority: [P3]
        targets: [ses-email]
      - priority: [P4, P5, P6]
        targets: [ses-email]

  # ── CUSTOM / MCP ──────────────────────────────────────────────────
  # Optional: route specific incident categories to custom MCP servers.
  # Leave empty if not used.
  custom: []
    # - name: security-bot
    #   match:
    #     category: security
    #   target: mcp-security-bot
```

#### Example Adopter Configurations

**Adopter A — Small team, ServiceNow + Email only:**
```yaml
routing:
  ticketing:
    default: servicenow
    overrides: []
  notifications:
    enabled: [ses-email]
    rules:
      - priority: [P1, P2, P3, P4, P5, P6]
        targets: [ses-email]
  custom: []
```
Deploy only: `integration-servicenow` + `integration-ses-email` pods.

**Adopter B — Enterprise, Jira + Slack + PagerDuty:**
```yaml
routing:
  ticketing:
    default: jira
    overrides: []
  notifications:
    enabled: [slack, pagerduty]
    rules:
      - priority: [P1, P2]
        targets: [pagerduty, slack]
      - priority: [P3, P4, P5, P6]
        targets: [slack]
  custom: []
```
Deploy only: `integration-jira` + `integration-slack` + `integration-pagerduty` pods.

**Adopter C — Multi-source with custom MCP bot:**
```yaml
routing:
  ticketing:
    default: servicenow
    overrides:
      - match:
          source_system: splunk
        target: splunk-soar
  notifications:
    enabled: [ses-email, slack]
    rules:
      - priority: [P1, P2]
        targets: [ses-email, slack]
      - priority: [P3, P4, P5, P6]
        targets: [ses-email]
  custom:
    - name: security-bot
      match:
        category: security
      target: mcp-security-bot
```
Deploy: `integration-servicenow` + `integration-splunk-soar` + `integration-ses-email` + `integration-slack` + `integration-mcp-security-bot` pods.

### Example Integrations

| Integration | Target | Capabilities | Notes |
|-------------|--------|-------------|-------|
| ServiceNow | ServiceNow ITSM | Create/update/close incidents | Existing — refactored into standalone pod |
| Jira | Atlassian Jira | Create/update issues | REST API v3 |
| PagerDuty | PagerDuty | Trigger/resolve incidents | Events API v2 |
| Slack | Slack | Channel messages, threads | Webhook or Bot API |
| SES/SNS Email | AWS SES/SNS | Email notifications | Existing — refactored |
| Splunk SOAR | Splunk SOAR | Trigger playbooks | REST API |
| Custom MCP | Any MCP Server | Tool calls via MCP protocol | For org-specific bots |
| Microsoft Teams | Teams | Adaptive cards, channels | Webhook connector |

---

## Event Bus Design

The event bus decouples collectors from the analysis engine. Two viable options:

### Option A: Amazon SQS (Recommended for AWS-native)

```
Collectors ──► SQS Queue (monitoring-events) ──► Agent (consumer)
                    │
                    ├── Dead Letter Queue (monitoring-events-dlq)
                    ├── Message retention: 4 days
                    ├── Visibility timeout: 300s
                    └── Long polling enabled
```

Pros: Serverless, no infra to manage, built-in DLQ, scales to zero.
Cons: AWS-only, max 256KB message size (use S3 for large payloads).

### Option B: Redis Streams (Recommended for multi-cloud / low-latency)

```
Collectors ──► Redis Stream (monitoring:events) ──► Agent (consumer group)
                    │
                    ├── Consumer group: agent-workers
                    ├── Max stream length: 100,000
                    └── Acknowledgment-based processing
```

Pros: Sub-millisecond latency, works anywhere, already in the stack.
Cons: Requires Redis management, no built-in DLQ (must implement).

### Recommendation

Start with **SQS** for simplicity. The agent already runs on AWS, and SQS gives you DLQ, retry, and scaling for free. Add Redis Streams later if latency becomes critical or multi-cloud is needed.

---

## Deployment Topology

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         EKS Cluster — monitoring namespace                   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  COLLECTOR PODS (scale independently)                                    │ │
│  │                                                                          │ │
│  │  collector-cloudwatch (1 replica)                                        │ │
│  │  collector-splunk (1 replica)                                            │ │
│  │  collector-prometheus (1 replica)                                        │ │
│  │  collector-custom-grpc (1 replica)                                       │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  CORE AGENT (the brain)                                                  │ │
│  │                                                                          │ │
│  │  monitoring-agent (1-2 replicas)                                         │ │
│  │    Reads from event bus → Correlate → Analyze → Classify → Route         │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  INTEGRATION PODS (deploy only what you use)                             │ │
│  │                                                                          │ │
│  │  integration-servicenow (1 replica)    ← if ticketing.default=servicenow │ │
│  │  integration-jira (1 replica)          ← if ticketing.default=jira       │ │
│  │  integration-ses-email (1 replica)     ← if in notifications.enabled     │ │
│  │  integration-slack (1 replica)         ← if in notifications.enabled     │ │
│  │  integration-pagerduty (1 replica)     ← if in notifications.enabled     │ │
│  │  integration-mcp-custom (1 replica)    ← if in custom routes             │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  SHARED SERVICES                                                         │ │
│  │                                                                          │ │
│  │  monitoring-dashboard (1 replica)                                        │ │
│  │  redis (1 replica, optional)                                             │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Agent ConfigMap (All Parameterized Values)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: monitoring-agent-config
  namespace: monitoring
data:
  # ── Existing config ──
  AWS_REGION: "us-east-1"
  BEDROCK_MODEL_ID: "..."
  COLLECTION_INTERVAL: "60"
  RAG_CONFIDENCE_THRESHOLD: "0.85"

  # ── Plug & Play: Correlation ──
  CORRELATION_WINDOW_SECONDS: "300"       # 5 min default, range: 60-600
  CORRELATION_DEDUP_TTL_SECONDS: "600"    # How long to remember event_ids for dedup

  # ── Plug & Play: Outbound Routing ──
  ACTION_ROUTING_CONFIG: "/etc/monitoring/action-routing-rules.yaml"
```

The routing rules live in a separate ConfigMap volume-mounted into the agent pod. Changing routing = update ConfigMap + restart agent. No image rebuild.

---

## Custom MCP Server Integration

For organizations that have custom bots or MCP servers that need to receive incidents:

```python
class MCPIntegration(IntegrationPlugin):
    """
    Generic MCP server integration.
    Calls tools on a remote MCP server to create tickets or trigger actions.
    """

    async def create_ticket(self, incident: Incident) -> Dict[str, Any]:
        result = await self.mcp_client.call_tool(
            tool_name=self.config["create_tool"],
            arguments=self._map_incident_to_args(incident)
        )
        return result

    async def notify(self, incident: Incident) -> Dict[str, Any]:
        result = await self.mcp_client.call_tool(
            tool_name=self.config["notify_tool"],
            arguments=self._map_incident_to_args(incident)
        )
        return result
```

---

## Communication Patterns

### Collector → Agent (Inbound)

```
                    Async (Event Bus)
Collector Pod ──────────────────────────► Agent Pod
              publish to SQS/Redis        consume from SQS/Redis
```

Collectors are fire-and-forget. They publish normalized events and move on. A slow collector doesn't block the agent. A collector crash doesn't affect other collectors. Collectors can be added/removed without agent restart.

### Agent → Integration (Outbound)

- **Ticketing**: Direct HTTP (synchronous) — need ticket ID back immediately
- **Notifications**: Action queue (async) — fan-out to Slack + Email + PagerDuty simultaneously

### All → OpenSearch (Learning)

Every incident is indexed regardless of source or destination. Correlation patterns are stored with confidence scores. This ensures the RAG knowledge base captures cross-source patterns and gets smarter over time.

---

## Challenges and Considerations

### 1. Schema Evolution
**Challenge**: As new collectors are added, the Unified Event Schema may need new fields.
**Mitigation**: `raw_payload` and `labels`/`tags` as escape hatches. Additive changes (new optional fields) are non-breaking. Use `schema_version` field.

### 2. Event Deduplication
**Challenge**: Multiple collectors might report the same underlying issue.
**Mitigation**: The correlation engine handles this. Events with matching `resource.id` within the correlation window are grouped, not duplicated. `event_id` dedup cache (Redis, TTL = `CORRELATION_DEDUP_TTL_SECONDS`).

### 3. Credential Management at Scale
**Challenge**: Each collector and integration pod needs its own credentials.
**Mitigation**: AWS Secrets Manager with IRSA per pod. Consider External Secrets Operator for K8s-native secret sync.

### 4. Ordering and Exactly-Once Processing
**Challenge**: SQS provides at-least-once delivery.
**Mitigation**: Agent is idempotent — `event_id` dedup cache prevents duplicate incidents.

### 5. Collector Failure Isolation
**Challenge**: A misbehaving collector shouldn't flood the event bus.
**Mitigation**: Per-collector rate limits. Health check + circuit breaker pattern.

### 6. Integration Timeout / Failure
**Challenge**: ServiceNow is down, Jira API is slow, etc.
**Mitigation**: Retry with exponential backoff. DLQ for failed actions. Incident still stored in OpenSearch regardless.

### 7. RAG Consistency Across Sources
**Challenge**: Incidents from Splunk and CloudWatch use different terminology.
**Mitigation**: Unified Event Schema normalizes before indexing. RAG embeddings generated from normalized `title` and `description`. Correlation patterns use normalized signal fingerprints.

### 8. Correlation Pattern Drift
**Challenge**: A stored correlation pattern may become stale if infrastructure changes.
**Mitigation**: Confidence score includes recency decay. Patterns not seen for 90 days have their confidence reduced. Patterns with low `times_confirmed / times_seen` ratio are deprioritized. Dashboard shows pattern health.

---

## Migration Path from Current Architecture

| Phase | Change | Risk |
|-------|--------|------|
| **Phase 1** | Add event bus (SQS). Agent reads from both direct collectors AND the bus. | Low — additive only |
| **Phase 2** | Extract CloudWatch collectors into standalone pod. They publish to the bus. | Medium — one moving part |
| **Phase 3** | Extract ServiceNow + Email into standalone integration pods. Add routing config. | Medium — one moving part |
| **Phase 4** | Add correlation engine to the agent. Add correlation-patterns index to OpenSearch. | Medium — new feature |
| **Phase 5** | Add new collectors (Splunk, Prometheus) as new pods. No agent changes. | Low — additive only |
| **Phase 6** | Add new integrations (Jira, PagerDuty, Slack) as new pods. Update routing rules. | Low — additive only |

Each phase is independently deployable and rollback-safe.

---

## Proposed Directory Structure

```
pro-acti-moni-bot/
├── agent/                          # Core analysis engine
│   ├── src/
│   │   ├── correlation/            # NEW: Correlation engine
│   │   │   ├── engine.py
│   │   │   └── patterns.py         # Pattern storage/retrieval
│   │   ├── routing/                # NEW: Action router
│   │   │   └── router.py
│   │   └── ...                     # Existing code
│   └── manifests/
├── collectors/                     # One directory per collector plugin
│   ├── cloudwatch/
│   ├── splunk/
│   ├── prometheus/
│   ├── datadog/
│   └── _template/                  # Starter template for new collectors
├── integrations/                   # One directory per integration plugin
│   ├── servicenow/
│   ├── jira/
│   ├── pagerduty/
│   ├── slack/
│   ├── mcp-custom/
│   └── _template/                  # Starter template for new integrations
├── shared/                         # Shared libraries
│   ├── event_schema.py             # Unified Event Schema
│   ├── plugin_base.py              # CollectorPlugin + IntegrationPlugin ABCs
│   └── bus_client.py               # Event bus publish/consume helpers
├── config/
│   └── action-routing-rules.yaml   # Routing configuration
├── dashboard/
├── terraform/
├── scripts/
├── docs/
│   ├── Architecture.md
│   └── ArchitecturePandP.md        # This file
└── README.md
```

---

## Summary

The plug-and-play architecture turns the monitoring agent from a CloudWatch-specific tool into a **universal monitoring analysis engine**. The core value — AI-powered anomaly detection, severity classification, RAG-based learning — stays the same. What changes is that the inputs and outputs become swappable pods that any team can add without touching the core.

The key design decisions:
- **Source awareness**: The agent always knows where every event came from (`source_system` is mandatory and tracked end-to-end)
- **Cross-source correlation**: Events from different sources are grouped into single incidents within a parameterized time window (`CORRELATION_WINDOW_SECONDS`, default 300s, range 60–600s)
- **Correlation patterns in RAG**: Multi-source correlation patterns are stored in OpenSearch with confidence scores. When the same pattern recurs, the RAG fast path reuses stored RCA/classification, skipping Bedrock. Confidence scores evolve based on accuracy and recency.
- **Configurable outbound routing**: Adopters declare which ticketing system and notification channels they use in a routing ConfigMap — only those integration pods need to be deployed
- **Event bus** decouples collectors from the agent (async, resilient)
- **Unified Event Schema** is the contract between all components
- **OpenSearch captures everything** — incidents, correlation patterns with confidence scores, resolution history — keeping RAG effective across all sources and getting smarter over time
