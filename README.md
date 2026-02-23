# Proactive Monitoring Bot

An AI-powered monitoring solution that continuously monitors AWS CloudWatch for anomalies and incidents, automatically classifies them by severity (P1-P6), creates ServiceNow incidents, and learns from historical data.

## Features

- **CloudWatch Monitoring**: Collects alarms, metrics, logs, and log insights
- **AI-Powered Analysis**: Uses Amazon Bedrock (Claude) for anomaly detection
- **Severity Classification**: Automatically classifies incidents P1-P6
- **ServiceNow Integration**: Creates and manages incidents based on severity
- **Smart Notifications**: Email alerts via SNS/SES based on priority
- **Continuous Learning**: RAG-based learning from runbooks and case history
- **EKS Deployment**: Runs on Amazon EKS with full Terraform automation

## Quick Start

### Prerequisites

- AWS CLI configured with credentials
- Terraform >= 1.0
- Docker
- kubectl
- ServiceNow instance with API access

### Deploy

```bash
# Clone and setup
cd pro-acti-moni-bot
chmod +x scripts/*.sh

# Run setup (will prompt for configuration)
./scripts/setup.sh
```

### Access

```bash
# Port forward to access locally
kubectl port-forward -n monitoring svc/monitoring-agent 8080:8080

# Health check
curl http://localhost:8080/health

# Test connections
curl http://localhost:8080/test/connections
```

## Architecture

See [docs/Architecture.md](docs/Architecture.md) for detailed architecture documentation.

## RAG Setup (Runbooks & Learning)

See [docs/RAG-Setup-Guide.md](docs/RAG-Setup-Guide.md) for how to upload your runbooks.

**Quick start:**
```bash
# Upload your runbooks to S3
aws s3 sync ./your-runbooks/ s3://YOUR-BUCKET/runbooks/

# Import to the system
./scripts/import-rag-data.sh
```

```
CloudWatch  -->  Collectors  -->  Anomaly Detector  -->  Classifier (P1-P6)
                     |                  |                      |
                     v                  v                      v
                OpenSearch <------ Bedrock (Claude) ---->  ServiceNow + Notifications
                (RAG/History)                              (Incidents + Alerts)
```

## Severity Levels

| Priority | Severity | Auto-Close | Notification |
|----------|----------|------------|--------------|
| P1 | Critical - Production down | No | Immediate |
| P2 | High - Major impact | No | Immediate |
| P3 | Medium - Minor impact | No | Standard |
| P4 | Low - Minimal impact | Yes | Summary |
| P5 | Very Low - Informational | Yes | Summary |
| P6 | Trivial - No impact | Yes | None |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/status` | GET | Agent status |
| `/collect` | POST | Trigger collection |
| `/incidents` | GET | List incidents |
| `/incidents/{id}` | GET | Get incident |
| `/incidents/{id}/resolve` | POST | Resolve incident |
| `/runbooks` | POST | Index runbook |
| `/runbooks/search` | GET | Search runbooks |
| `/test/connections` | GET | Test all connections |
| `/s3/status` | GET | S3 RAG sync status |
| `/s3/runbooks` | GET | List S3 runbooks |
| `/s3/runbooks` | POST | Upload runbook to S3 |
| `/s3/sync/runbooks` | POST | Sync runbooks from S3 |
| `/s3/sync/case-history` | POST | Sync case history from S3 |
| `/s3/sync/all` | POST | Bulk import all from S3 |
| `/extract/runbook` | POST | Extract schema from raw text |
| `/extract/runbook/index` | POST | Extract and index raw runbook |

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `AWS_REGION` | AWS region | Yes |
| `BEDROCK_MODEL_ID` | Claude model ID | No |
| `CLOUDWATCH_NAMESPACES` | Namespaces to monitor | No |
| `COLLECTION_INTERVAL` | Polling interval (seconds) | No |
| `SERVICENOW_INSTANCE` | ServiceNow instance name | Yes |
| `SERVICENOW_USERNAME` | ServiceNow service account | Yes |
| `SERVICENOW_PASSWORD` | ServiceNow password | Yes |
| `SERVICENOW_ASSIGNMENT_GROUP` | Assignment group (optional) | No |
| `SERVICENOW_CALLER_ID` | Caller sys_id (optional) | No |
| `OPENSEARCH_ENDPOINT` | OpenSearch endpoint | Yes |
| `SNS_TOPIC_ARN` | SNS topic for alerts | Yes |
| `RAG_S3_BUCKET` | S3 bucket for RAG data | Yes |
| `RAG_S3_RUNBOOKS_PREFIX` | S3 prefix for runbooks | No |
| `RAG_S3_CASE_HISTORY_PREFIX` | S3 prefix for case history | No |

### Terraform Variables

See `terraform/terraform.tfvars.example` for all configuration options.

## Project Structure

```
pro-acti-moni-bot/
├── docs/
│   └── Architecture.md      # Detailed architecture
├── terraform/               # Infrastructure as Code
│   ├── main.tf
│   ├── vpc.tf
│   ├── eks.tf
│   ├── iam.tf
│   ├── opensearch.tf
│   └── variables.tf
├── agent/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── src/
│   │   ├── app.py           # FastAPI application
│   │   ├── agent.py         # LangGraph agent
│   │   ├── config.py        # Configuration
│   │   ├── collectors/      # CloudWatch collectors
│   │   ├── processors/      # Anomaly & classification
│   │   ├── integrations/    # ServiceNow & notifications
│   │   ├── rag/            # RAG retriever
│   │   └── models/         # Data models
│   └── manifests/          # Kubernetes manifests
├── scripts/
│   ├── setup.sh            # Initial setup
│   ├── deploy.sh           # Redeploy after changes
│   └── cleanup.sh          # Destroy resources
└── README.md
```

## Extending

### Add New Collector

1. Create collector in `agent/src/collectors/`
2. Inherit from `BaseCollector`
3. Implement `collect()` and `test_connection()`
4. Register in `CollectorManager`

### Add Runbooks

```bash
# Index a runbook via API
curl -X POST http://localhost:8080/runbooks \
  -H "Content-Type: application/json" \
  -d '{
    "title": "High CPU Troubleshooting",
    "content": "Steps to diagnose high CPU...",
    "category": "performance",
    "keywords": ["cpu", "performance", "ec2"]
  }'
```

## Troubleshooting

### Check pod status
```bash
kubectl get pods -n monitoring
kubectl logs -n monitoring -l app=monitoring-agent -f
```

### Test connections
```bash
curl http://localhost:8080/test/connections
```

### Manual collection
```bash
curl -X POST http://localhost:8080/collect
```

## License

MIT
