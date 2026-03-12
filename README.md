# Proactive Monitoring Bot

AI-powered monitoring agent that continuously watches AWS CloudWatch for anomalies, classifies incidents by severity (P1-P6), creates ServiceNow tickets, sends email alerts with root cause analysis, and learns from past incidents using RAG.

## How It Works

```
                                  ┌─────────────────────┐
                                  │     CloudWatch      │
                                  │   Alarms / Metrics  │
                                  └──────────┬──────────┘
                                             │
                                             ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                            Monitoring Agent                                    │
│                                                                                │
│   1. Collectors (poll every 60s)                                               │
│                       │                                                        │
│                       ▼                                                        │
│   2. Query OpenSearch for similar past incidents & runbooks                     │
│                       │                                                        │
│                       ▼                                                        │
│   3. Check RAG confidence score                                                │
│                       │                                                        │
│            ┌──────────┴──────────┐                                             │
│            ▼                     ▼                                             │
│   ┌─────────────────┐  ┌─────────────────────────────────┐                     │
│   │ Score >= thresh  │  │ Score < thresh (or disabled)    │                     │
│   │                  │  │                                 │                     │
│   │  RAG Fast Path   │  │  Standard Path                  │                     │
│   │                  │  │                                 │                     │
│   │  Reuse stored:   │  │  ┌───────────────────────────┐  │                     │
│   │  • RCA           │  │  │  Amazon Bedrock (Claude)  │  │                     │
│   │  • Actions       │  │  │                           │  │                     │
│   │  • Priority      │  │  │  Call 1 (Anomaly):        │  │                     │
│   │    (compared     │  │  │   • Anomaly detection     │  │                     │
│   │    with rule-    │  │  │   • Root cause analysis   │  │                     │
│   │    based, take   │  │  │   • Recommended actions   │  │                     │
│   │    more severe)  │  │  │                           │  │                     │
│   │                  │  │  │  Call 2 (Classifier):     │  │                     │
│   │  Skip Bedrock    │  │  │   • AI severity (P1-P6)   │  │                     │
│   │                  │  │  │   • Compare with rules    │  │                     │
│   └────────┬─────────┘  │  └─────────────┬─────────────┘  │                     │
│            │            │                │                │                     │
│            │            └────────────────┘                │                     │
│            │                      │                       │                     │
│            └──────────┬───────────┘                       │                     │
│                       │                                                        │
│                       ▼                                                        │
│            ┌──────────┼──────────┐                                             │
│            ▼          ▼          ▼                                             │
│      ┌──────────┐ ┌─────────┐ ┌──────────────┐                                │
│      │SNS Email │ │Service  │ │ Store in     │                                │
│      │(RCA      │ │Now      │ │ OpenSearch   │                                │
│      │ alert)   │ │         │ │ (future RAG) │                                │
│      │          │ │P1-P3:   │ │              │                                │
│      │          │ │  open   │ │              │                                │
│      │          │ │P4-P6:   │ │              │                                │
│      │          │ │  closed │ │              │                                │
│      └──────────┘ └─────────┘ └──────────────┘                                │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘
```

1. Collectors inside the agent poll CloudWatch alarms and metrics every 60s (configurable). Alarm history is also checked so transient alarms that revert to OK are still caught.
2. The agent queries OpenSearch for similar past incidents and runbooks (RAG context), each result includes a confidence score
3. The agent checks the top RAG match score against `RAG_CONFIDENCE_THRESHOLD` (configurable, default 0.0 = disabled):
   - **Score >= threshold (RAG fast path):** Reuses the stored RCA, recommended actions, and priority from the past incident. Skips both Bedrock calls. Rule-based classification still runs and the more severe priority wins.
   - **Score < threshold (standard path):** Sends events + RAG context to Amazon Bedrock for anomaly detection, RCA, and AI classification. Rule-based classification also runs and the more severe priority wins.
4. The agent acts on the final classification:
   - Creates ServiceNow tickets (P1-P3 stay open, P4-P6 are auto-closed)
   - Sends email notifications via SNS with detailed RCA
   - Stores the completed incident back into OpenSearch for future RAG learning

## Prerequisites

- AWS CLI configured with credentials
- Terraform >= 1.0
- Docker
- kubectl
- A ServiceNow instance with API access (free dev instance at [developer.servicenow.com](https://developer.servicenow.com))
- Amazon Bedrock model access enabled in your region

## Quick Start

```bash
# 1. Clone the repo
git clone <repo-url> && cd pro-acti-moni-bot

# 2. Make scripts executable
chmod +x scripts/*.sh

# 3. Run setup (prompts for all configuration)
./scripts/setup.sh
```

> After setup completes, check your email and confirm the SNS subscription — otherwise you won't receive incident alerts.

The setup script will:
- Prompt for AWS region, Bedrock model ID, ServiceNow credentials, notification emails
- Deploy infrastructure via Terraform (VPC, EKS, OpenSearch, IAM, ECR, SNS)
- Build and push Docker images (agent + dashboard)
- Deploy Kubernetes manifests with your configuration
- Set up OpenSearch indices with proper KNN vector mappings for RAG

## Deploying to a Different Region

Just run `./scripts/setup.sh` and enter your target region when prompted. The only prerequisite is that Amazon Bedrock must be enabled in that region with access to your chosen model.

If your model isn't available in the target region, use a cross-region inference profile ARN as the Bedrock Model ID (e.g., `us.anthropic.claude-3-5-sonnet-20241022-v2:0`).

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/setup.sh` | Full deployment — infra + images + K8s + OpenSearch |
| `scripts/deploy.sh [agent\|dashboard\|both]` | Rebuild and redeploy after code changes |
| `scripts/deploy-dashboard.sh` | Standalone dashboard deployment |
| `scripts/import-rag-data.sh` | Import runbooks/case history from S3 to OpenSearch |
| `scripts/check-status.sh` | Quick status overview of all components |
| `scripts/cleanup.sh` | Destroy all deployed resources |

## Demo Application

A sample Flask + PostgreSQL app is included in `demo/` with its own Terraform config and CloudWatch alarms. See `demo/README.md` for setup instructions. The dashboard can trigger these alarms to demonstrate the full incident pipeline.

## Useful Commands

```bash
# Check status
./scripts/check-status.sh

# View agent logs
kubectl logs -n monitoring -l app=monitoring-agent -f

# Port-forward agent API
kubectl port-forward -n monitoring svc/monitoring-agent 8080:8080

# Redeploy after code changes
./scripts/deploy.sh both

# Destroy everything
./scripts/cleanup.sh
```

## Architecture

See [docs/Architecture.md](docs/Architecture.md) for detailed architecture documentation.

## Configuration Reference

All configuration is provided during `setup.sh` and stored in:
- `terraform/terraform.tfvars` — infrastructure config (gitignored)
- K8s ConfigMap/Secrets — runtime config (applied via `envsubst`)

Key parameters:
- `AWS_REGION` — deployment region
- `BEDROCK_MODEL_ID` — Amazon Bedrock model for AI analysis
- `COLLECTION_INTERVAL` — how often to poll CloudWatch (default: 60s)
- `CLOUDWATCH_NAMESPACES` — which AWS services to monitor
- `SERVICENOW_INSTANCE` — ServiceNow instance for ticket creation
- `NOTIFICATION_EMAILS` — email addresses for SNS alerts
- `RAG_CONFIDENCE_THRESHOLD` — cosine similarity score (0.0-1.0) above which the agent reuses stored RCA instead of calling Bedrock. Default 0.0 (disabled). Recommended starting value: 0.85-0.92
