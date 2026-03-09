# Proactive Monitoring Bot

AI-powered monitoring agent that continuously watches AWS CloudWatch for anomalies, classifies incidents by severity (P1-P6), creates ServiceNow tickets, sends email alerts with root cause analysis, and learns from past incidents using RAG.

## How It Works

```
                          ┌───────────────────┐
                          │    CloudWatch     │
                          │  Alarms / Metrics │
                          └─────────┬─────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────┐ ┌─────────────────────────────────┐
│                  Monitoring Agent                 │ │   Amazon Bedrock (Claude)       │
│                                                   │ │                                 │
│  1. Collectors (poll every 60s)                   │ │ Call 1 (Anomaly Detector):      │
│                  │                                │ │   • Anomaly detection           │
│                  ▼                                │ │   • Root cause analysis         │
│  2. Query OpenSearch for RAG context              │ │   • Recommended actions         │
│                  │                                │ │                                 │
│                  ▼                                │ │ Call 2 (Classifier):            │
│  3. Send events + context  ◀─────────────────────▶│ │   • AI severity (P1-P6)         │
│     (alarms, metrics, thresholds,                 │ │                                 │
│      affected resources) + RAG context            │ └─────────────────────────────────┘
│                  │                                │
│                  ▼                                │
│  4. Classify: run rule-based classification       │
│     (anomaly scores + category + keywords)        │
│     and compare with AI classification from       │
│     Bedrock — take the more severe of the two     │
│                  │                                │
│      ┌───────────┼──────────────┐                 │
│      ▼           ▼              ▼                 │
│ ┌──────────┐ ┌──────────┐ ┌─────────────────┐     │
│ │SNS Email │ │ServiceNow│ │Store in         │     │
│ │(RCA      │ │          │ │OpenSearch       │     │
│ │ alert)   │ │P1-P3:open│ │(future RAG)     │     │
│ │          │ │P4-P6:auto│ │                 │     │
│ │          │ │  closed  │ │                 │     │
│ └──────────┘ └──────────┘ └─────────────────┘     │
│                                                   │
└───────────────────────────────────────────────────┘
```

1. Collectors inside the agent poll CloudWatch alarms and metrics every 60s (configurable). Alarm history is also checked so transient alarms that revert to OK are still caught.
2. The agent queries OpenSearch for similar past incidents and runbooks (RAG context)
3. The agent makes two Bedrock calls — first for anomaly detection + root cause analysis + recommended actions, then for AI severity classification (P1-P6)
4. The agent also runs rule-based classification using anomaly scores, event categories, and keyword matching — then takes the more severe of rule-based vs AI classification as the final severity
5. The agent acts on the final classification:
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
