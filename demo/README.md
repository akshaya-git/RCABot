# Proactive Monitoring Bot - Demo Environment

This demo environment allows you to test the Proactive Monitoring Bot with a real application deployment, including RDS PostgreSQL, CloudWatch alarms, and anomaly generation.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AWS Account                                     │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                         Existing EKS Cluster                          │  │
│  │                                                                       │  │
│  │   ┌─────────────────┐         ┌─────────────────┐                    │  │
│  │   │   Demo App      │         │  Monitoring     │                    │  │
│  │   │   (Inventory)   │◄───────►│  Agent          │                    │  │
│  │   │   namespace:    │         │  namespace:     │                    │  │
│  │   │   demo-app      │         │  monitoring     │                    │  │
│  │   └────────┬────────┘         └────────┬────────┘                    │  │
│  │            │                           │                              │  │
│  └────────────┼───────────────────────────┼──────────────────────────────┘  │
│               │                           │                                  │
│               ▼                           ▼                                  │
│  ┌─────────────────────┐     ┌─────────────────────────────────────┐       │
│  │   RDS PostgreSQL    │     │         CloudWatch                   │       │
│  │   (db.t3.micro)     │────►│  - Alarms (CPU, Memory, Connections) │       │
│  │   - inventory DB    │     │  - Log Groups                        │       │
│  │   - 20GB storage    │     │  - Metrics                           │       │
│  └─────────────────────┘     └──────────────┬──────────────────────┘       │
│                                              │                              │
│                                              ▼                              │
│                              ┌─────────────────────────────────────┐       │
│                              │           SNS Topic                  │       │
│                              │   → Email Notifications             │       │
│                              │   → Monitoring Agent Webhook        │       │
│                              └─────────────────────────────────────┘       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- AWS CLI configured with appropriate credentials
- kubectl installed and configured
- Terraform >= 1.0.0
- Docker
- An existing EKS cluster (deployed via `/terraform/eks/`)
- jq (for JSON processing)

## Quick Start

### 1. Run the Setup Script

```bash
cd demo/app/scripts
chmod +x setup-demo.sh generate-anomaly.sh
./setup-demo.sh
```

The script will:
- Prompt for your AWS region
- List and validate your existing EKS cluster
- Ask for database password
- Optionally set up email notifications
- Deploy all infrastructure via Terraform
- Build and push the demo app Docker image
- Seed the database with sample data
- Display the application URL

### 2. Access the Demo Application

Once deployed, access the inventory management system at:
```
http://<load-balancer-hostname>
```

The app displays:
- Product inventory from PostgreSQL
- Statistics (total products, value, categories)
- Search functionality
- Low stock alerts

### 3. Generate Anomalies

Use the anomaly generator to trigger CloudWatch alarms:

```bash
# Interactive menu
./generate-anomaly.sh

# Or run specific tests
./generate-anomaly.sh cpu 60      # CPU stress for 60 seconds
./generate-anomaly.sh memory 200  # Allocate 200MB memory
./generate-anomaly.sh db 100      # Open 100 DB connections
./generate-anomaly.sh traffic 500 # Generate 500 API requests
./generate-anomaly.sh errors 20   # Generate 20 application errors
./generate-anomaly.sh all         # Run all tests
```

### 4. Monitor with the Bot

The Proactive Monitoring Agent will:
1. Receive CloudWatch alarm notifications via SNS webhook
2. Analyze the incident using AI (Claude)
3. Correlate with runbook knowledge (RAG)
4. Create a ServiceNow ticket with actionable intelligence
5. Provide remediation suggestions

## CloudWatch Alarms

| Alarm Name | Metric | Threshold | Description |
|------------|--------|-----------|-------------|
| `demo-app-demo-rds-cpu-high` | CPUUtilization | >80% | RDS CPU spike |
| `demo-app-demo-rds-connections-high` | DatabaseConnections | >50 | Connection flood |
| `demo-app-demo-rds-memory-low` | FreeableMemory | <100MB | Memory pressure |
| `demo-app-demo-rds-read-latency-high` | ReadLatency | >20ms | Slow reads |
| `demo-app-demo-rds-write-latency-high` | WriteLatency | >50ms | Slow writes |
| `demo-app-demo-rds-storage-low` | FreeStorageSpace | <5GB | Low disk |
| `demo-app-demo-application-errors` | ApplicationErrors | >10/5min | App errors |

## Files

```
demo/
├── README.md                          # This file
└── app/
    ├── Dockerfile                     # Demo app container
    ├── src/
    │   └── app.py                     # Flask application
    ├── templates/
    │   └── index.html                 # Web UI
    ├── terraform/
    │   ├── main.tf                    # All infrastructure
    │   └── terraform.tfvars.example   # Example variables
    └── scripts/
        ├── setup-demo.sh              # Main setup script
        ├── generate-anomaly.sh        # Anomaly generator
        └── seed-data.sql              # Database seed data
```

## Manual Deployment

If you prefer to deploy manually:

### 1. Configure Terraform

```bash
cd demo/app/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values
```

### 2. Deploy Infrastructure

```bash
terraform init
terraform plan
terraform apply
```

### 3. Build and Push Docker Image

```bash
cd demo/app
aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin <ecr-repo-url>
docker build -t demo-inventory:latest .
docker tag demo-inventory:latest <ecr-repo-url>:latest
docker push <ecr-repo-url>:latest
```

### 4. Seed Database

```bash
# Get RDS endpoint from Terraform output
RDS_HOST=$(terraform output -raw rds_address)

# Run seed script
kubectl run db-seed --namespace demo-app \
  --image=postgres:15 --restart=Never --rm -i \
  --env="PGPASSWORD=<your-password>" \
  -- psql -h $RDS_HOST -U demoadmin -d inventory < scripts/seed-data.sql
```

### 5. Restart Deployment

```bash
kubectl rollout restart deployment/demo-inventory -n demo-app
```

## Cleanup

To destroy all demo resources:

```bash
./setup-demo.sh cleanup
# Or manually:
cd demo/app/terraform
terraform destroy
```

## Troubleshooting

### Application not accessible
```bash
# Check pod status
kubectl get pods -n demo-app

# Check pod logs
kubectl logs -l app=demo-inventory -n demo-app

# Check service
kubectl get svc demo-inventory -n demo-app
```

### Database connection issues
```bash
# Check RDS status in AWS Console
# Verify security group allows traffic from EKS

# Test connection from a pod
kubectl run psql-test --namespace demo-app \
  --image=postgres:15 --restart=Never --rm -it \
  --env="PGPASSWORD=<password>" \
  -- psql -h <rds-endpoint> -U demoadmin -d inventory -c "SELECT 1"
```

### CloudWatch alarms not triggering
```bash
# Check alarm status
aws cloudwatch describe-alarms --alarm-name-prefix demo-app-demo

# Verify SNS topic has subscriptions
aws sns list-subscriptions-by-topic --topic-arn <topic-arn>
```

## Integration with Monitoring Agent

Follow these steps to configure the Proactive Monitoring Agent to collect CloudWatch signals from the demo app.

### Step 1: Get Demo App CloudWatch Resources

After deploying the demo app, get the resource identifiers:

```bash
cd demo/app/terraform

# Get the CloudWatch log group name
terraform output cloudwatch_log_group
# Example output: /eks/my-cluster/demo-app

# Get the SNS topic ARN
terraform output sns_topic_arn

# Get the RDS identifier (for reference)
terraform output rds_endpoint
```

**Record these values - you'll need them in the next steps.**

### Step 2: Update Monitoring Agent ConfigMap

Edit `agent/manifests/configmap.yaml` to add the demo app namespaces:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: monitoring-agent-config
  namespace: monitoring
data:
  # Must match the region where demo app is deployed
  AWS_REGION: "<your-region>"

  # Add AWS/RDS and DemoApp namespaces
  # AWS/RDS - for RDS database alarms
  # DemoApp - for application error metrics
  CLOUDWATCH_NAMESPACES: "AWS/RDS,DemoApp"

  # Polling interval (seconds)
  COLLECTION_INTERVAL: "60"

  # ... other existing config values
```

### Step 3: Configure Log Group Collection

To monitor the demo app log group for errors, you have two options:

**Option A: Environment Variable (simple)**

The agent auto-discovers log groups. Ensure it has IAM permissions to access:
- `/eks/<your-cluster>/demo-app`

**Option B: Explicit Configuration (recommended)**

Create or update `agent/src/config/collectors.yaml`:

```yaml
collectors:
  alarms:
    enabled: true
    alarm_name_prefixes:
      - "demo-app-demo"   # Matches: demo-app-demo-rds-cpu-high, etc.

  metrics:
    enabled: true
    metrics:
      - namespace: "DemoApp"
        metric_name: "ApplicationErrors"
        threshold: 5
        comparison: "GreaterThan"
        period: 300

  logs:
    enabled: true
    log_groups:
      # Replace YOUR-CLUSTER-NAME with your actual EKS cluster name
      - "/eks/YOUR-CLUSTER-NAME/demo-app"
    error_patterns:
      - "ERROR"
      - "Exception"
      - "CRITICAL"
      - "DatabaseError"
      - "ConnectionError"

  insights:
    enabled: true
    log_groups:
      - "/eks/YOUR-CLUSTER-NAME/demo-app"
```

### Step 4: Apply Configuration and Restart Agent

```bash
# Apply updated ConfigMap
kubectl apply -f agent/manifests/configmap.yaml

# Restart the monitoring agent to pick up changes
kubectl rollout restart deployment/monitoring-agent -n monitoring

# Wait for rollout to complete
kubectl rollout status deployment/monitoring-agent -n monitoring
```

### Step 5: Verify Integration

```bash
# Port forward to the monitoring agent
kubectl port-forward -n monitoring svc/monitoring-agent 8080:8080 &

# Test all connections (should show success for CloudWatch)
curl http://localhost:8080/test/connections | jq .

# Check agent status (should list the collectors)
curl http://localhost:8080/status | jq .

# Trigger a manual collection cycle
curl -X POST http://localhost:8080/collect | jq .
```

### Step 6: Generate Anomalies and Verify Detection

```bash
# Generate a CPU stress test on the demo app
./generate-anomaly.sh cpu 120

# Wait 2-3 minutes for CloudWatch alarm to trigger

# Check if the agent detected it
curl http://localhost:8080/incidents | jq .
```

### Demo App CloudWatch Resources Reference

The demo app creates these CloudWatch resources that the agent will monitor:

| Resource | Type | Namespace | Alarm Name |
|----------|------|-----------|------------|
| RDS CPU | Alarm | AWS/RDS | `demo-app-demo-rds-cpu-high` |
| RDS Connections | Alarm | AWS/RDS | `demo-app-demo-rds-connections-high` |
| RDS Memory | Alarm | AWS/RDS | `demo-app-demo-rds-memory-low` |
| RDS Read Latency | Alarm | AWS/RDS | `demo-app-demo-rds-read-latency-high` |
| RDS Write Latency | Alarm | AWS/RDS | `demo-app-demo-rds-write-latency-high` |
| RDS Storage | Alarm | AWS/RDS | `demo-app-demo-rds-storage-low` |
| App Errors | Alarm | DemoApp | `demo-app-demo-application-errors` |
| App Logs | Log Group | - | `/eks/<cluster>/demo-app` |
| Error Metric | Custom Metric | DemoApp | `ApplicationErrors` |

### Optional: Configure SNS Webhook (Push-based)

For real-time notifications (instead of polling), configure SNS to push to the agent:

```bash
# Get the monitoring agent external URL (if exposed)
AGENT_URL=$(kubectl get svc monitoring-agent -n monitoring -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

# Subscribe SNS topic to agent webhook
aws sns subscribe \
  --topic-arn $(cd demo/app/terraform && terraform output -raw sns_topic_arn) \
  --protocol https \
  --notification-endpoint "https://${AGENT_URL}/webhook/cloudwatch"
```

### Troubleshooting Integration

| Issue | Solution |
|-------|----------|
| "No alarms found" | Trigger an anomaly with `./generate-anomaly.sh cpu 60` and wait for alarm |
| "Log group not found" | Verify log group name matches: `aws logs describe-log-groups --log-group-name-prefix "/eks/"` |
| "Access denied" | Check IAM role has CloudWatch and Logs permissions |
| Agent not detecting alarms | Verify `CLOUDWATCH_NAMESPACES` includes `AWS/RDS,DemoApp` |

For more details, see the [Configuration section in the main README](../README.md#configuration).
