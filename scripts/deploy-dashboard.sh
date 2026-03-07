#!/bin/bash
# =============================================================================
# Deploy Dashboard - Standalone dashboard deployment
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Get config from terraform
cd "$PROJECT_DIR/terraform"
AWS_REGION=$(terraform output -raw aws_region 2>/dev/null || echo "us-east-1")
ECR_REPO=$(terraform output -raw ecr_repository_url 2>/dev/null)
ROLE_ARN=$(terraform output -raw monitoring_agent_role_arn 2>/dev/null)
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

DASHBOARD_ECR_NAME="$(echo $ECR_REPO | sed 's|.*/||' | sed 's/-agent/-dashboard/')"
DASHBOARD_ECR_REPO="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$DASHBOARD_ECR_NAME"
NAMESPACE="monitoring"

cd "$PROJECT_DIR"

echo "Deploying Monitoring Dashboard"
echo "  ECR: $DASHBOARD_ECR_REPO"
echo "  Region: $AWS_REGION"

# ECR login
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

# Create ECR repo if needed
aws ecr describe-repositories --repository-names "$DASHBOARD_ECR_NAME" --region "$AWS_REGION" 2>/dev/null || \
    aws ecr create-repository --repository-name "$DASHBOARD_ECR_NAME" --region "$AWS_REGION"

# Build and push
docker build --platform linux/amd64 -t "$DASHBOARD_ECR_REPO:latest" dashboard/
docker push "$DASHBOARD_ECR_REPO:latest"

# Deploy manifests
export AWS_REGION MONITORING_AGENT_ROLE_ARN="$ROLE_ARN" DASHBOARD_ECR_REPOSITORY_URL="$DASHBOARD_ECR_REPO"
kubectl apply -f dashboard/manifests/namespace.yaml
envsubst < dashboard/manifests/serviceaccount.yaml | kubectl apply -f -
envsubst < dashboard/manifests/deployment.yaml | kubectl apply -f -
kubectl apply -f dashboard/manifests/service.yaml

kubectl rollout status deployment/monitoring-dashboard -n "$NAMESPACE" --timeout=300s

DASHBOARD_URL=$(kubectl get svc monitoring-dashboard -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "pending")
echo ""
echo "Dashboard URL: http://$DASHBOARD_URL:9493"
echo ""
