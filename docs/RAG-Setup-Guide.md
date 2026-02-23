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
│  YOUR FILE       │         │  CLAUDE EXTRACTS │         │  STORED SCHEMA   │
│                  │         │                  │         │                  │
│  # High CPU      │         │  Reads content   │         │  {               │
│                  │   ───►  │  Identifies:     │   ───►  │    "title": ..   │
│  When CPU high:  │         │  - What it's for │         │    "category":.  │
│  1. Run top      │         │  - Key steps     │         │    "keywords":[].│
│  2. Check mem    │         │  - Keywords      │         │    "steps": []   │
│                  │         │                  │         │  }               │
└──────────────────┘         └──────────────────┘         └──────────────────┘
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
