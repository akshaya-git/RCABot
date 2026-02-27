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

```
CloudWatch  -->  Collectors  -->  Anomaly Detector  -->  Classifier (P1-P6)
                     |                  |                      |
                     v                  v                      v
                OpenSearch <------ Bedrock (Claude) ---->  ServiceNow + Notifications
                (RAG/History)                              (Incidents + Alerts)
```

---

## Configuration

All configuration is done via environment variables in the Kubernetes ConfigMap (`agent/manifests/configmap.yaml`) and Secrets (`agent/manifests/secrets.yaml`).

### LLM Model Configuration

The agent uses Amazon Bedrock (Claude) for anomaly detection, root cause analysis, and incident classification.

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `BEDROCK_MODEL_ID` | Bedrock model ID | No | `anthropic.claude-3-sonnet-20240229-v1:0` |

**Available Models:**

| Model | Model ID | Notes |
|-------|----------|-------|
| Claude 3.5 Sonnet v2 | `anthropic.claude-3-5-sonnet-20241022-v2:0` | Recommended |
| Claude 3.5 Sonnet | `anthropic.claude-3-5-sonnet-20240620-v1:0` | High quality |
| Claude 3 Sonnet | `anthropic.claude-3-sonnet-20240229-v1:0` | Default |
| Claude 3 Haiku | `anthropic.claude-3-haiku-20240307-v1:0` | Faster, lower cost |
| Claude 3 Opus | `anthropic.claude-3-opus-20240229-v1:0` | Highest quality |

**Example:**
```yaml
# In agent/manifests/configmap.yaml
data:
  BEDROCK_MODEL_ID: "anthropic.claude-3-5-sonnet-20241022-v2:0"
```

**Verify model access:**
```bash
aws bedrock-runtime invoke-model \
  --model-id "anthropic.claude-3-sonnet-20240229-v1:0" \
  --content-type "application/json" \
  --body '{"anthropic_version":"bedrock-2023-05-31","max_tokens":100,"messages":[{"role":"user","content":"Hello"}]}' \
  /dev/stdout
```

---

### CloudWatch Configuration

The agent collects CloudWatch signals through four collectors: Alarms, Metrics, Logs, and Log Insights.

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `AWS_REGION` | AWS region for CloudWatch | Yes | `us-east-1` |
| `CLOUDWATCH_NAMESPACES` | Comma-separated namespaces to monitor | Yes | - |
| `COLLECTION_INTERVAL` | Polling interval in seconds | No | `60` |

**Supported Namespaces:**

| Namespace | What It Monitors |
|-----------|------------------|
| `AWS/EC2` | EC2 instances |
| `AWS/RDS` | RDS databases |
| `AWS/ECS` | ECS services |
| `AWS/EKS` | EKS clusters |
| `AWS/Lambda` | Lambda functions |
| `AWS/ApplicationELB` | Load balancers |
| Custom (e.g., `DemoApp`) | Your applications |

**Example:**
```yaml
# In agent/manifests/configmap.yaml
data:
  AWS_REGION: "us-east-1"
  CLOUDWATCH_NAMESPACES: "AWS/EC2,AWS/RDS,AWS/Lambda,DemoApp"
  COLLECTION_INTERVAL: "60"
```

**Find your namespaces:**
```bash
# List all namespaces with metrics
aws cloudwatch list-metrics --query 'Metrics[*].Namespace' --output text | tr '\t' '\n' | sort -u

# List alarms
aws cloudwatch describe-alarms --query 'MetricAlarms[*].[AlarmName,Namespace]' --output table
```

**Find your log groups:**
```bash
aws logs describe-log-groups --query 'logGroups[*].logGroupName' --output table
```

---

### ServiceNow Configuration

| Variable | Description | Required |
|----------|-------------|----------|
| `SERVICENOW_INSTANCE` | Instance name (e.g., `mycompany`) | Yes |
| `SERVICENOW_USERNAME` | Service account username | Yes |
| `SERVICENOW_PASSWORD` | Service account password | Yes |
| `SERVICENOW_ASSIGNMENT_GROUP` | Default assignment group | No |
| `SERVICENOW_CALLER_ID` | Caller sys_id | No |

**Example (in secrets.yaml):**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: monitoring-agent-secrets
  namespace: monitoring
stringData:
  SERVICENOW_INSTANCE: "mycompany"
  SERVICENOW_USERNAME: "svc_monitoring"
  SERVICENOW_PASSWORD: "your-password"
```

---

### RAG & Storage Configuration

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENSEARCH_ENDPOINT` | OpenSearch domain endpoint | Yes |
| `RAG_S3_BUCKET` | S3 bucket for runbooks/case history | Yes |
| `RAG_S3_RUNBOOKS_PREFIX` | S3 prefix for runbooks | No (default: `runbooks/`) |
| `RAG_S3_CASE_HISTORY_PREFIX` | S3 prefix for case history | No (default: `case-history/`) |

See [docs/RAG-Setup-Guide.md](docs/RAG-Setup-Guide.md) for how to upload your runbooks.

---

### Notification Configuration

| Variable | Description | Required |
|----------|-------------|----------|
| `SNS_TOPIC_ARN` | SNS topic ARN for alerts | Yes |
| `NOTIFICATION_EMAILS` | Comma-separated email list | No |

---

### Complete ConfigMap Example

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: monitoring-agent-config
  namespace: monitoring
data:
  # AWS Region
  AWS_REGION: "us-east-1"

  # LLM Model
  BEDROCK_MODEL_ID: "anthropic.claude-3-5-sonnet-20241022-v2:0"

  # CloudWatch Collection
  CLOUDWATCH_NAMESPACES: "AWS/EC2,AWS/RDS,AWS/Lambda,DemoApp"
  COLLECTION_INTERVAL: "60"

  # RAG Storage
  OPENSEARCH_ENDPOINT: "https://search-xxxxx.us-east-1.es.amazonaws.com"
  RAG_S3_BUCKET: "my-rag-bucket"
  RAG_S3_RUNBOOKS_PREFIX: "runbooks/"
  RAG_S3_CASE_HISTORY_PREFIX: "case-history/"

  # Notifications
  SNS_TOPIC_ARN: "arn:aws:sns:us-east-1:123456789012:alerts"

  # ServiceNow (non-sensitive)
  SERVICENOW_ASSIGNMENT_GROUP: "Cloud Operations"
```

---

## Configuring for Demo App

If you deployed the demo app from `demo/app/`, configure the agent to monitor its signals:

### Step 1: Get Demo App Values

```bash
cd demo/app/terraform
terraform output cloudwatch_log_group   # e.g., /eks/my-cluster/demo-app
terraform output sns_topic_arn
```

### Step 2: Update ConfigMap

```yaml
data:
  AWS_REGION: "us-east-1"
  CLOUDWATCH_NAMESPACES: "AWS/RDS,DemoApp"   # RDS alarms + app errors
  BEDROCK_MODEL_ID: "anthropic.claude-3-5-sonnet-20241022-v2:0"
```

### Step 3: Apply and Test

```bash
kubectl apply -f agent/manifests/configmap.yaml
kubectl rollout restart deployment/monitoring-agent -n monitoring

# Generate an anomaly
cd demo/app/scripts && ./generate-anomaly.sh cpu 60

# Check detection (after 2-3 min)
curl http://localhost:8080/incidents
```

### Demo App CloudWatch Resources

| Resource | Namespace | Alarm Name |
|----------|-----------|------------|
| RDS CPU | AWS/RDS | `demo-app-demo-rds-cpu-high` |
| RDS Connections | AWS/RDS | `demo-app-demo-rds-connections-high` |
| RDS Memory | AWS/RDS | `demo-app-demo-rds-memory-low` |
| App Errors | DemoApp | `demo-app-demo-application-errors` |
| App Logs | - | `/eks/<cluster>/demo-app` |

---

## Severity Levels

| Priority | Severity | Auto-Close | Notification |
|----------|----------|------------|--------------|
| P1 | Critical - Production down | No | Immediate |
| P2 | High - Major impact | No | Immediate |
| P3 | Medium - Minor impact | No | Standard |
| P4 | Low - Minimal impact | Yes | Summary |
| P5 | Very Low - Informational | Yes | Summary |
| P6 | Trivial - No impact | Yes | None |

---

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

---

## Terraform Variables

See `terraform/terraform.tfvars.example` for infrastructure configuration options.

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
