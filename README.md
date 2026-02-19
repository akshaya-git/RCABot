# Proactive Monitoring Bot

An AI-powered monitoring solution that continuously monitors AWS CloudWatch for anomalies and incidents, automatically classifies them by severity (P1-P6), creates Jira tickets, and learns from historical data.

## Features

- **CloudWatch Monitoring**: Collects alarms, metrics, logs, and log insights
- **AI-Powered Analysis**: Uses Amazon Bedrock (Claude) for anomaly detection
- **Severity Classification**: Automatically classifies incidents P1-P6
- **Jira Integration**: Creates and manages tickets based on severity
- **Smart Notifications**: Email alerts via SNS/SES based on priority
- **Continuous Learning**: RAG-based learning from runbooks and case history
- **EKS Deployment**: Runs on Amazon EKS with full Terraform automation

## Quick Start

### Prerequisites

- AWS CLI configured with credentials
- Terraform >= 1.0
- Docker
- kubectl
- Jira Cloud account with API access

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

```
CloudWatch  -->  Collectors  -->  Anomaly Detector  -->  Classifier (P1-P6)
                     |                  |                      |
                     v                  v                      v
                OpenSearch <------ Bedrock (Claude) ---->  Jira + Notifications
                (RAG/History)                              (Tickets + Alerts)
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

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `AWS_REGION` | AWS region | Yes |
| `BEDROCK_MODEL_ID` | Claude model ID | No |
| `CLOUDWATCH_NAMESPACES` | Namespaces to monitor | No |
| `COLLECTION_INTERVAL` | Polling interval (seconds) | No |
| `JIRA_URL` | Jira instance URL | Yes |
| `JIRA_EMAIL` | Jira service email | Yes |
| `JIRA_API_TOKEN` | Jira API token | Yes |
| `JIRA_PROJECT` | Default project key | Yes |
| `OPENSEARCH_ENDPOINT` | OpenSearch endpoint | Yes |
| `SNS_TOPIC_ARN` | SNS topic for alerts | Yes |

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
│   │   ├── integrations/    # Jira & notifications
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
