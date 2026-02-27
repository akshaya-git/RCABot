# RAG Setup Guide

## What is RAG?

RAG (Retrieval-Augmented Generation) helps the monitoring bot give better recommendations by learning from your runbooks and past incidents.

```
Without RAG:  "High CPU detected" → Generic advice
With RAG:     "High CPU detected" → YOUR runbook steps + similar past incidents
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           RAG DATA FLOW                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   YOUR RUNBOOKS                                                              │
│   (any format)                                                               │
│        │                                                                     │
│        ▼                                                                     │
│   ┌─────────┐      ┌─────────────┐      ┌─────────────┐      ┌───────────┐ │
│   │   S3    │ ──── │   Import    │ ──── │   Claude    │ ──── │ OpenSearch│ │
│   │ Bucket  │      │   Script    │      │ (Extract)   │      │  (Index)  │ │
│   └─────────┘      └─────────────┘      └─────────────┘      └───────────┘ │
│                                                                     │        │
│   runbooks/            Reads files         Extracts:           Stores with  │
│   ├── cpu.md           from S3             - Title             embeddings   │
│   ├── disk.txt                             - Category          for search   │
│   └── db.json                              - Keywords                       │
│                                            - Steps                          │
│                                                                     │        │
│                                                                     ▼        │
│                                                              ┌───────────┐  │
│   INCIDENT OCCURS                                            │ Monitoring│  │
│        │                                                     │   Agent   │  │
│        ▼                                                     └─────┬─────┘  │
│   ┌─────────────┐      ┌─────────────┐      ┌─────────────┐       │        │
│   │ CloudWatch  │ ──── │   Agent     │ ──── │  OpenSearch │ ◄─────┘        │
│   │   Event     │      │  Analyzes   │      │   Search    │                 │
│   └─────────────┘      └─────────────┘      └─────────────┘                 │
│                              │                     │                         │
│                              │    ┌────────────────┘                         │
│                              │    │                                          │
│                              ▼    ▼                                          │
│                        ┌─────────────┐                                       │
│                        │   Claude    │                                       │
│                        │  Analysis   │                                       │
│                        │ + RAG Data  │                                       │
│                        └──────┬──────┘                                       │
│                               │                                              │
│                               ▼                                              │
│                        ┌─────────────┐                                       │
│                        │  ServiceNow │                                       │
│                        │  Incident   │                                       │
│                        │ with RCA +  │                                       │
│                        │ Runbook     │                                       │
│                        │ Steps       │                                       │
│                        └─────────────┘                                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Setup Steps

### Step 1: Get Your S3 Bucket Name

```bash
cd terraform
terraform output rag_s3_bucket_name
```

Save this name (e.g., `proactive-monitor-prod-rag-data-123456789`)

### Step 2: Upload Your Runbooks

```bash
# Upload your existing runbooks (any format works)
aws s3 sync ./your-runbooks/ s3://BUCKET-NAME/runbooks/
```

**Supported formats:** `.md`, `.txt`, `.json`, `.html`, `.rst`

**No schema required** - the system extracts structure automatically.

### Step 3: Run Import Script

```bash
# Make sure agent is accessible
kubectl port-forward -n monitoring svc/monitoring-agent 8080:8080 &

# Run import
./scripts/import-rag-data.sh
```

### Step 4: Verify

```bash
curl http://localhost:8080/s3/status
```

---

## S3 Bucket Structure

```
s3://your-bucket/
├── runbooks/           ← Upload your runbooks here
│   ├── high-cpu.md
│   ├── disk-space.txt
│   └── database.json
└── case-history/       ← Auto-populated from resolved incidents
    └── 2024/02/23/
        └── INC001.json
```

---

## How Extraction Works

```
┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│  YOUR FILE       │         │  CLAUDE EXTRACTS │         │  STORED SCHEMA*  │
│                  │         │                  │         │                  │
│  # High CPU      │         │  Reads content   │         │  {               │
│                  │   ───►  │  Identifies:     │   ───►  │    "title": ..   │
│  When CPU high:  │         │  - What it's for │         │    "category":.  │
│  1. Run top      │         │  - Key steps     │         │    "keywords":[].│
│  2. Check mem    │         │  - Keywords      │         │    "steps": []   │
│                  │         │                  │         │    ...           │
│                  │         │                  │         │  }               │
└──────────────────┘         └──────────────────┘         └──────────────────┘

* Simplified view. See "OpenSearch Schema Definitions" below for complete schema.
```

---

## OpenSearch Schema Definitions

The following schemas define the structure of data stored in OpenSearch for RAG retrieval.

### Runbook Schema

Stored in OpenSearch index: `runbooks`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique identifier (auto-generated) |
| `title` | string | Yes | Runbook title extracted from document |
| `category` | string | Yes | Category classification (e.g., `performance`, `security`, `database`, `networking`, `storage`) |
| `content` | string | Yes | Summary/overview of the runbook |
| `keywords` | array[string] | Yes | Search keywords for matching incidents |
| `steps` | array[string] | Yes | Ordered list of remediation steps |
| `source_file` | string | Yes | S3 URI of the original file |
| `indexed_at` | datetime | Yes | Timestamp when indexed |

**Category Values:**
- `performance` - CPU, memory, latency issues
- `security` - Access, authentication, vulnerability issues
- `database` - RDS, DynamoDB, connection issues
- `networking` - VPC, DNS, connectivity issues
- `storage` - EBS, S3, disk space issues
- `application` - Application-specific errors
- `infrastructure` - EC2, ECS, EKS issues
- `general` - Catch-all for uncategorized

---

### Case History Schema

Stored in OpenSearch index: `case-history`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `incident_id` | string | Yes | Unique incident identifier (e.g., `INC-2024-0142`) |
| `title` | string | Yes | Incident title/summary |
| `date` | datetime | Yes | When the incident occurred |
| `duration_minutes` | integer | No | How long the incident lasted |
| `priority` | string | Yes | Priority level (`P1`, `P2`, `P3`, `P4`, `P5`, `P6`) |
| `severity` | string | Yes | Severity label (`Critical`, `High`, `Medium`, `Low`, `Very Low`, `Trivial`) |
| `service_affected` | string | Yes | Which service/system was impacted |
| `description` | string | Yes | Detailed description of the incident |
| `symptoms` | array[string] | Yes | Observable symptoms during the incident |
| `root_cause` | string | Yes | Verified root cause explanation |
| `resolution` | string | Yes | How the incident was resolved |
| `resolution_steps` | array[string] | Yes | Ordered steps taken to resolve |
| `keywords` | array[string] | Yes | Search keywords for matching future incidents |
| `lessons_learned` | array[string] | No | Post-mortem learnings |
| `time_to_resolve` | string | No | Human-readable resolution time |
| `source_file` | string | Yes | S3 URI of the original file |
| `indexed_at` | datetime | Yes | Timestamp when indexed |

---

### Incident Schema (Live Incidents)

Stored in OpenSearch index: `incidents`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `incident_id` | string | Yes | Unique incident identifier |
| `title` | string | Yes | Incident title |
| `priority` | string | Yes | Priority level (`P1`-`P6`) |
| `severity` | string | Yes | Severity label |
| `status` | string | Yes | Current status (`open`, `investigating`, `resolved`, `closed`) |
| `source` | string | Yes | Where the incident originated (e.g., `cloudwatch-alarms`) |
| `resource_type` | string | Yes | AWS resource type (`ec2`, `rds`, `ecs`, `lambda`, etc.) |
| `resource_id` | string | No | Specific resource identifier |
| `namespace` | string | No | CloudWatch namespace |
| `description` | string | Yes | Incident description |
| `root_cause_analysis` | string | No | AI-generated RCA |
| `recommended_actions` | array[string] | No | AI-generated recommendations |
| `servicenow_ticket` | string | No | ServiceNow incident number |
| `created_at` | datetime | Yes | When incident was created |
| `updated_at` | datetime | Yes | Last update timestamp |
| `resolved_at` | datetime | No | When incident was resolved |
| `resolution` | string | No | How it was resolved (populated on close) |

---

## Sample Entries

### Runbook: Input vs Extracted Output

**Input File (`runbooks/high-cpu-troubleshooting.md`):**

```markdown
# High CPU Utilization Troubleshooting

## Overview
This runbook covers how to diagnose and resolve high CPU utilization
on EC2 instances and ECS containers.

## Symptoms
- CloudWatch alarm: CPUUtilization > 80%
- Application latency increasing
- Requests timing out

## Diagnostic Steps

1. **Identify the process**
   ```bash
   ssh ec2-user@<instance-ip>
   top -o %CPU
   ```

2. **Check for runaway processes**
   ```bash
   ps aux --sort=-%cpu | head -20
   ```

3. **Review recent deployments**
   - Check deployment history in the last 24 hours
   - Look for config changes

4. **Check memory pressure**
   ```bash
   free -m
   vmstat 1 5
   ```

5. **Review application logs**
   ```bash
   tail -f /var/log/application/app.log | grep -i error
   ```

## Resolution Steps

1. If runaway process: `kill -9 <pid>`
2. If memory leak: Restart the service or roll back deployment
3. If load-related: Scale horizontally (add instances)
4. If code issue: Roll back to previous version

## Escalation
If not resolved within 30 minutes, escalate to Platform Engineering team.
```

**Extracted Output (stored in OpenSearch):**

```json
{
  "id": "runbook-high-cpu-001",
  "title": "High CPU Utilization Troubleshooting",
  "category": "performance",
  "content": "This runbook covers how to diagnose and resolve high CPU utilization on EC2 instances and ECS containers.",
  "keywords": [
    "cpu",
    "high cpu",
    "performance",
    "ec2",
    "ecs",
    "latency",
    "timeout",
    "top",
    "process"
  ],
  "steps": [
    "SSH to instance and run 'top -o %CPU' to identify high-CPU process",
    "Run 'ps aux --sort=-%cpu | head -20' to check for runaway processes",
    "Review deployment history for the last 24 hours",
    "Check memory pressure with 'free -m' and 'vmstat 1 5'",
    "Review application logs for errors",
    "If runaway process, kill with 'kill -9 <pid>'",
    "If memory leak, restart service or roll back deployment",
    "If load-related, scale horizontally by adding instances",
    "If code issue, roll back to previous version",
    "Escalate to Platform Engineering if not resolved in 30 minutes"
  ],
  "source_file": "s3://my-bucket/runbooks/high-cpu-troubleshooting.md",
  "indexed_at": "2024-02-18T10:30:00Z"
}
```

---

### Case History: Input vs Extracted Output

**Input File (`case-history/INC-2024-0142.md`):**

```markdown
# Incident Post-Mortem: INC-2024-0142

**Date:** January 15, 2024
**Duration:** 45 minutes
**Severity:** P2 (High)
**Service Affected:** prod-api cluster

## Summary
High CPU utilization on prod-api cluster caused API latency spikes
and intermittent 504 errors for approximately 45 minutes.

## Timeline
- 10:15 UTC - Deployment of auth-service v2.1.0
- 10:28 UTC - Memory utilization started climbing
- 10:30 UTC - CloudWatch alarm triggered (CPU > 80%)
- 10:32 UTC - On-call engineer paged
- 10:45 UTC - Root cause identified (memory leak in auth-service)
- 10:55 UTC - Rolled back to auth-service v2.0.9
- 11:00 UTC - Services recovered, alarm cleared

## Root Cause
Memory leak in authentication service v2.1.0 caused excessive
garbage collection, leading to CPU spikes. The leak was in the
session token cache which wasn't properly releasing expired tokens.

## Resolution
Rolled back auth-service from v2.1.0 to v2.0.9. The memory leak
was subsequently fixed in v2.1.1.

## Lessons Learned
1. Add memory leak detection to CI/CD pipeline
2. Implement gradual rollout for auth-service changes
3. Add heap dump automation when memory threshold exceeded

## Action Items
- [ ] Add memory profiling to staging tests
- [ ] Implement canary deployments for critical services
- [ ] Create runbook for memory leak diagnosis
```

**Extracted Output (stored in OpenSearch):**

```json
{
  "incident_id": "INC-2024-0142",
  "title": "High CPU Utilization on prod-api cluster - Memory Leak",
  "date": "2024-01-15T10:30:00Z",
  "duration_minutes": 45,
  "priority": "P2",
  "severity": "High",
  "service_affected": "prod-api cluster",
  "description": "High CPU utilization on prod-api cluster caused API latency spikes and intermittent 504 errors for approximately 45 minutes.",
  "symptoms": [
    "CPU utilization > 80%",
    "API latency spikes",
    "504 Gateway Timeout errors",
    "Memory utilization climbing"
  ],
  "root_cause": "Memory leak in authentication service v2.1.0 caused excessive garbage collection, leading to CPU spikes. The leak was in the session token cache which wasn't properly releasing expired tokens.",
  "resolution": "Rolled back auth-service from v2.1.0 to v2.0.9. The memory leak was subsequently fixed in v2.1.1.",
  "resolution_steps": [
    "Identified memory leak in auth-service via heap analysis",
    "Rolled back to previous stable version v2.0.9",
    "Verified services recovered and alarm cleared"
  ],
  "keywords": [
    "cpu",
    "memory leak",
    "garbage collection",
    "auth-service",
    "rollback",
    "504 error",
    "latency"
  ],
  "lessons_learned": [
    "Add memory leak detection to CI/CD pipeline",
    "Implement gradual rollout for auth-service changes",
    "Add heap dump automation when memory threshold exceeded"
  ],
  "time_to_resolve": "45 minutes",
  "source_file": "s3://my-bucket/case-history/INC-2024-0142.md",
  "indexed_at": "2024-01-16T09:00:00Z"
}
```

---

### How the Agent Uses These Entries

When a new incident occurs (e.g., "High CPU on prod-api"), the agent:

1. **Searches runbooks** for matching keywords (`cpu`, `performance`, `ec2`)
2. **Searches case history** for similar past incidents
3. **Provides context to Claude** for analysis:

```
Current Event: CPU at 92% on prod-api-asg

Relevant Runbook Found:
- "High CPU Utilization Troubleshooting"
- Steps: SSH and run top, check for runaway processes...

Similar Past Incident:
- INC-2024-0142: Memory leak caused high CPU
- Resolution: Rolled back deployment
- Time to resolve: 45 minutes

Based on this context, generate root cause analysis and recommendations...
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Get bucket name | `terraform output rag_s3_bucket_name` |
| Upload runbooks | `aws s3 sync ./runbooks/ s3://BUCKET/runbooks/` |
| Run import | `./scripts/import-rag-data.sh` |
| Check status | `curl http://localhost:8080/s3/status` |
| Search runbooks | `curl "http://localhost:8080/runbooks/search?query=cpu"` |
| List S3 files | `aws s3 ls s3://BUCKET/runbooks/` |

---

## Adding More Runbooks Later

```bash
# Upload new files
aws s3 cp new-runbook.md s3://BUCKET-NAME/runbooks/

# Re-run import
./scripts/import-rag-data.sh
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Cannot connect to API" | Run: `kubectl port-forward -n monitoring svc/monitoring-agent 8080:8080` |
| "S3 bucket not configured" | Check `RAG_S3_BUCKET` in ConfigMap |
| "No files found" | Upload files to `s3://bucket/runbooks/` first |
| "Extraction failed" | Ensure files are UTF-8 encoded and not empty |

---

## FAQ

**Q: Do my runbooks need a specific format?**
A: No. Upload as-is. The LLM extracts the structure.

**Q: What happens to case history?**
A: It's auto-saved when incidents are resolved. You can also upload historical post-mortems.

**Q: How do I update a runbook?**
A: Upload the new version to S3 and run the import script again.
