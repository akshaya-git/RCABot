#!/bin/bash
# =============================================================================
# Quick Status Check - Shows current state of all deployed components
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================"
echo "Proactive Monitoring Bot - Status"
echo "========================================"
echo ""

# Cluster info
echo "--- Cluster ---"
kubectl cluster-info 2>/dev/null | head -1 || echo "Not connected to cluster"
echo ""

# Pods
echo "--- Pods (monitoring namespace) ---"
kubectl get pods -n monitoring -o wide 2>/dev/null || echo "No pods found"
echo ""

# Services
echo "--- Services ---"
kubectl get svc -n monitoring 2>/dev/null || echo "No services found"
echo ""

# Dashboard URL
DASHBOARD_URL=$(kubectl get svc monitoring-dashboard -n monitoring -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)
if [ -n "$DASHBOARD_URL" ]; then
    echo "Dashboard: http://$DASHBOARD_URL:9493"
else
    echo "Dashboard: LoadBalancer not yet provisioned"
fi
echo ""

# Demo app (if deployed)
DEMO_PODS=$(kubectl get pods -n demo-app 2>/dev/null)
if [ -n "$DEMO_PODS" ]; then
    echo "--- Demo App ---"
    echo "$DEMO_PODS"
    echo ""
fi

# CloudWatch alarms
echo "--- CloudWatch Alarms ---"
AWS_REGION=$(cat "$PROJECT_DIR/terraform/terraform.tfvars" 2>/dev/null | grep aws_region | sed 's/.*= *"\(.*\)"/\1/' || echo "us-east-1")
aws cloudwatch describe-alarms --state-value ALARM --query 'MetricAlarms[].AlarmName' --output table --region "$AWS_REGION" 2>/dev/null || echo "Could not fetch alarms"
echo ""

# Recent agent logs
echo "--- Recent Agent Logs (last 10 lines) ---"
kubectl logs -n monitoring -l app=monitoring-agent --tail=10 2>/dev/null || echo "No agent logs available"
echo ""
