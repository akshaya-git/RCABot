#!/bin/bash
# =============================================================================
# Deploy Script - Rebuild and redeploy after code changes
# Usage: ./scripts/deploy.sh [agent|dashboard|both]
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TARGET="${1:-both}"

# Get configuration from Terraform
cd "$PROJECT_DIR/terraform"
ECR_REPO=$(terraform output -raw ecr_repository_url 2>/dev/null)
AWS_REGION=$(terraform output -raw aws_region 2>/dev/null || echo "us-east-1")
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

if [ -z "$ECR_REPO" ]; then
    echo "Error: Could not get ECR repository URL. Run scripts/setup.sh first."
    exit 1
fi

DASHBOARD_ECR_NAME="$(echo $ECR_REPO | sed 's|.*/||' | sed 's/-agent/-dashboard/')"
DASHBOARD_ECR_REPO="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$DASHBOARD_ECR_NAME"

cd "$PROJECT_DIR"

# ECR login
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

if [ "$TARGET" = "agent" ] || [ "$TARGET" = "both" ]; then
    echo "Building and pushing agent..."
    docker build --platform linux/amd64 -t "$ECR_REPO:latest" agent/
    docker push "$ECR_REPO:latest"
    kubectl rollout restart deployment/monitoring-agent -n monitoring
    kubectl rollout status deployment/monitoring-agent -n monitoring --timeout=300s
    echo "Agent deployed."
fi

if [ "$TARGET" = "dashboard" ] || [ "$TARGET" = "both" ]; then
    echo "Building and pushing dashboard..."
    docker build --platform linux/amd64 -t "$DASHBOARD_ECR_REPO:latest" dashboard/
    docker push "$DASHBOARD_ECR_REPO:latest"
    kubectl rollout restart deployment/monitoring-dashboard -n monitoring
    kubectl rollout status deployment/monitoring-dashboard -n monitoring --timeout=300s
    echo "Dashboard deployed."
fi

echo "Done."
