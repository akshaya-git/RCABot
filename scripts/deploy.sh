#!/bin/bash
# =============================================================================
# Deploy Script - Rebuild and redeploy after code changes
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================"
echo "Redeploying Monitoring Agent"
echo "========================================"

# Get configuration from Terraform
cd "$PROJECT_DIR/terraform"
ECR_REPO=$(terraform output -raw ecr_repository_url 2>/dev/null)
AWS_REGION=$(terraform output -raw 2>/dev/null | grep -oP 'aws_region\s*=\s*"\K[^"]+' || echo "us-east-1")

if [ -z "$ECR_REPO" ]; then
    echo "Error: Could not get ECR repository URL. Run setup.sh first."
    exit 1
fi

# Build and push Docker image
echo "Building Docker image..."
cd "$PROJECT_DIR/agent"
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REPO"
docker build -t "$ECR_REPO:latest" .
docker push "$ECR_REPO:latest"

# Restart deployment
echo "Restarting deployment..."
kubectl rollout restart deployment/monitoring-agent -n monitoring

# Wait for rollout
echo "Waiting for rollout to complete..."
kubectl rollout status deployment/monitoring-agent -n monitoring --timeout=300s

echo "========================================"
echo "Deployment Complete!"
echo "========================================"
