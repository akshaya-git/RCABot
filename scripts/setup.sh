#!/bin/bash
# =============================================================================
# Setup Script for Proactive Monitoring Agent
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================"
echo "Proactive Monitoring Agent Setup"
echo "========================================"

# Check prerequisites
command -v terraform >/dev/null 2>&1 || { echo "Terraform is required but not installed. Aborting."; exit 1; }
command -v aws >/dev/null 2>&1 || { echo "AWS CLI is required but not installed. Aborting."; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "Docker is required but not installed. Aborting."; exit 1; }
command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required but not installed. Aborting."; exit 1; }

# Prompt for configuration
read -p "AWS Region [us-east-1]: " AWS_REGION
AWS_REGION=${AWS_REGION:-us-east-1}

read -p "Jira URL (e.g., https://company.atlassian.net): " JIRA_URL
read -p "Jira Email: " JIRA_EMAIL
read -s -p "Jira API Token: " JIRA_API_TOKEN
echo
read -p "Jira Project Key [OPS]: " JIRA_PROJECT
JIRA_PROJECT=${JIRA_PROJECT:-OPS}

read -p "Notification Email(s) (comma-separated): " NOTIFICATION_EMAILS

# Create terraform.tfvars
echo "Creating terraform.tfvars..."
cat > "$PROJECT_DIR/terraform/terraform.tfvars" << EOF
aws_region         = "$AWS_REGION"
jira_url           = "$JIRA_URL"
jira_email         = "$JIRA_EMAIL"
jira_api_token     = "$JIRA_API_TOKEN"
jira_project       = "$JIRA_PROJECT"
notification_emails = [$(echo "$NOTIFICATION_EMAILS" | sed 's/,/","/g' | sed 's/^/"/' | sed 's/$/"/' )]
EOF

# Initialize and apply Terraform
echo "========================================"
echo "Deploying Infrastructure..."
echo "========================================"

cd "$PROJECT_DIR/terraform"
terraform init
terraform plan -out=tfplan
terraform apply tfplan

# Get outputs
ECR_REPO=$(terraform output -raw ecr_repository_url)
CLUSTER_NAME=$(terraform output -raw cluster_name)
OPENSEARCH_ENDPOINT=$(terraform output -raw opensearch_endpoint)
SNS_TOPIC_ARN=$(terraform output -raw sns_topic_arn)
ROLE_ARN=$(terraform output -raw monitoring_agent_role_arn)

# Configure kubectl
echo "========================================"
echo "Configuring kubectl..."
echo "========================================"
aws eks update-kubeconfig --region "$AWS_REGION" --name "$CLUSTER_NAME"

# Build and push Docker image
echo "========================================"
echo "Building and pushing Docker image..."
echo "========================================"

cd "$PROJECT_DIR/agent"
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REPO"
docker build -t "$ECR_REPO:latest" .
docker push "$ECR_REPO:latest"

# Deploy to Kubernetes
echo "========================================"
echo "Deploying to Kubernetes..."
echo "========================================"

cd "$PROJECT_DIR/agent/manifests"

# Apply namespace
kubectl apply -f namespace.yaml

# Apply manifests with substitutions
export ECR_REPOSITORY_URL="$ECR_REPO"
export MONITORING_AGENT_ROLE_ARN="$ROLE_ARN"
export AWS_REGION="$AWS_REGION"
export JIRA_URL="$JIRA_URL"
export JIRA_EMAIL="$JIRA_EMAIL"
export JIRA_API_TOKEN="$JIRA_API_TOKEN"
export JIRA_PROJECT="$JIRA_PROJECT"
export OPENSEARCH_ENDPOINT="$OPENSEARCH_ENDPOINT"
export SNS_TOPIC_ARN="$SNS_TOPIC_ARN"
export NOTIFICATION_EMAILS="$NOTIFICATION_EMAILS"

envsubst < serviceaccount.yaml | kubectl apply -f -
envsubst < configmap.yaml | kubectl apply -f -
envsubst < secrets.yaml | kubectl apply -f -
envsubst < deployment.yaml | kubectl apply -f -
kubectl apply -f service.yaml

# Wait for deployment
echo "Waiting for deployment to be ready..."
kubectl rollout status deployment/monitoring-agent -n monitoring --timeout=300s

echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo ""
echo "To access the agent:"
echo "  kubectl port-forward -n monitoring svc/monitoring-agent 8080:8080"
echo ""
echo "Then open: http://localhost:8080/health"
echo ""
echo "To view logs:"
echo "  kubectl logs -n monitoring -l app=monitoring-agent -f"
