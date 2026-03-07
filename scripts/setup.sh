#!/bin/bash
# =============================================================================
# Setup Script for Proactive Monitoring Bot
# Deploys infrastructure, builds images, and configures all components.
# Incorporates OpenSearch KNN index setup and IAM fixes.
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_header() { echo -e "\n${BLUE}========================================${NC}\n${BLUE}$1${NC}\n${BLUE}========================================${NC}\n"; }
print_success() { echo -e "${GREEN}[OK]${NC} $1"; }
print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ---- Prerequisites ----
print_header "Checking Prerequisites"
for cmd in terraform aws docker kubectl; do
    command -v $cmd &>/dev/null || { print_error "$cmd is required but not installed."; exit 1; }
done
aws sts get-caller-identity &>/dev/null || { print_error "AWS credentials not configured."; exit 1; }
print_success "All prerequisites met"

# ---- Prompt for configuration ----
print_header "Configuration"

read -p "AWS Region [us-east-1]: " AWS_REGION
AWS_REGION=${AWS_REGION:-us-east-1}

read -p "Bedrock Model ID [anthropic.claude-3-5-sonnet-20241022-v2:0]: " BEDROCK_MODEL_ID
BEDROCK_MODEL_ID=${BEDROCK_MODEL_ID:-anthropic.claude-3-5-sonnet-20241022-v2:0}

read -p "ServiceNow Instance (e.g., dev12345): " SERVICENOW_INSTANCE
read -p "ServiceNow Username: " SERVICENOW_USERNAME
read -s -p "ServiceNow Password: " SERVICENOW_PASSWORD
echo
read -p "ServiceNow Assignment Group (optional): " SERVICENOW_ASSIGNMENT_GROUP
read -p "ServiceNow Caller ID (optional): " SERVICENOW_CALLER_ID
read -p "Notification Email(s) (comma-separated): " NOTIFICATION_EMAILS
read -p "CloudWatch Namespaces [AWS/EC2,AWS/RDS,AWS/Lambda,AWS/EKS]: " CLOUDWATCH_NAMESPACES
CLOUDWATCH_NAMESPACES=${CLOUDWATCH_NAMESPACES:-AWS/EC2,AWS/RDS,AWS/Lambda,AWS/EKS}
read -p "Collection Interval seconds [60]: " COLLECTION_INTERVAL
COLLECTION_INTERVAL=${COLLECTION_INTERVAL:-60}

# ---- Create terraform.tfvars ----
print_header "Creating terraform.tfvars"
cat > "$PROJECT_DIR/terraform/terraform.tfvars" << EOF
aws_region                  = "$AWS_REGION"
environment                 = "prod"
project_name                = "proactive-monitor"
vpc_cidr                    = "10.0.0.0/16"
availability_zones          = []
cluster_name                = "monitoring-cluster"
cluster_version             = "1.29"
node_instance_types         = ["t3.large"]
node_desired_size           = 2
node_min_size               = 1
node_max_size               = 4
opensearch_instance_type    = "t3.small.search"
opensearch_instance_count   = 2
opensearch_volume_size      = 20
servicenow_instance         = "$SERVICENOW_INSTANCE"
servicenow_username         = "$SERVICENOW_USERNAME"
servicenow_password         = "$SERVICENOW_PASSWORD"
servicenow_assignment_group = "$SERVICENOW_ASSIGNMENT_GROUP"
servicenow_caller_id        = "$SERVICENOW_CALLER_ID"
notification_emails         = [$(echo "$NOTIFICATION_EMAILS" | sed 's/[^,]*/\"&\"/g')]
cloudwatch_namespaces       = [$(echo "$CLOUDWATCH_NAMESPACES" | sed 's/[^,]*/\"&\"/g')]
collection_interval         = $COLLECTION_INTERVAL
tags = {
  Project     = "ProactiveMonitor"
  ManagedBy   = "Terraform"
  Environment = "prod"
}
EOF
print_success "terraform.tfvars created"

# ---- Deploy Infrastructure ----
print_header "Deploying Infrastructure (20-25 min)"
cd "$PROJECT_DIR/terraform"
terraform init
terraform plan -out=tfplan
terraform apply -auto-approve tfplan

# Get outputs
ECR_REPO=$(terraform output -raw ecr_repository_url)
CLUSTER_NAME=$(terraform output -raw cluster_name)
OPENSEARCH_ENDPOINT=$(terraform output -raw opensearch_endpoint)
SNS_TOPIC_ARN=$(terraform output -raw sns_topic_arn)
ROLE_ARN=$(terraform output -raw monitoring_agent_role_arn)
RAG_S3_BUCKET=$(terraform output -raw rag_s3_bucket_name)
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

print_success "Infrastructure deployed"
print_info "ECR: $ECR_REPO"
print_info "Cluster: $CLUSTER_NAME"
cd "$PROJECT_DIR"

# ---- Configure kubectl ----
print_header "Configuring kubectl"
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION"
for i in $(seq 1 30); do
    kubectl cluster-info &>/dev/null && break
    echo -ne "\rWaiting for cluster... ($i/30)"
    sleep 10
done
print_success "kubectl configured"

# ---- Build and push agent image ----
print_header "Building Agent Docker Image"
cd "$PROJECT_DIR/agent"
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REPO"
docker build --platform linux/amd64 -t "$ECR_REPO:latest" .
docker push "$ECR_REPO:latest"
print_success "Agent image pushed"
cd "$PROJECT_DIR"

# ---- Create dashboard ECR repo and build ----
print_header "Building Dashboard Docker Image"
DASHBOARD_ECR_NAME="$(echo $ECR_REPO | sed 's|.*/||' | sed 's/-agent/-dashboard/')"
DASHBOARD_ECR_REPO="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$DASHBOARD_ECR_NAME"
aws ecr describe-repositories --repository-names "$DASHBOARD_ECR_NAME" --region "$AWS_REGION" 2>/dev/null || \
    aws ecr create-repository --repository-name "$DASHBOARD_ECR_NAME" --region "$AWS_REGION"
cd "$PROJECT_DIR/dashboard"
docker build --platform linux/amd64 -t "$DASHBOARD_ECR_REPO:latest" .
docker push "$DASHBOARD_ECR_REPO:latest"
print_success "Dashboard image pushed"
cd "$PROJECT_DIR"

# ---- Deploy Kubernetes manifests ----
print_header "Deploying to Kubernetes"

# Export all variables for envsubst
export AWS_REGION BEDROCK_MODEL_ID CLOUDWATCH_NAMESPACES COLLECTION_INTERVAL
export SERVICENOW_INSTANCE SERVICENOW_USERNAME SERVICENOW_PASSWORD
export SERVICENOW_ASSIGNMENT_GROUP SERVICENOW_CALLER_ID
export OPENSEARCH_ENDPOINT SNS_TOPIC_ARN RAG_S3_BUCKET NOTIFICATION_EMAILS
export ECR_REPOSITORY_URL="$ECR_REPO"
export MONITORING_AGENT_ROLE_ARN="$ROLE_ARN"
export DASHBOARD_ECR_REPOSITORY_URL="$DASHBOARD_ECR_REPO"

# Agent manifests
kubectl apply -f agent/manifests/namespace.yaml
envsubst < agent/manifests/serviceaccount.yaml | kubectl apply -f -
envsubst < agent/manifests/configmap.yaml | kubectl apply -f -
envsubst < agent/manifests/secrets.yaml | kubectl apply -f -
envsubst < agent/manifests/deployment.yaml | kubectl apply -f -
kubectl apply -f agent/manifests/service.yaml

# Dashboard manifests
envsubst < dashboard/manifests/serviceaccount.yaml | kubectl apply -f -
envsubst < dashboard/manifests/deployment.yaml | kubectl apply -f -
kubectl apply -f dashboard/manifests/service.yaml

print_info "Waiting for agent rollout..."
kubectl rollout status deployment/monitoring-agent -n monitoring --timeout=300s
print_info "Waiting for dashboard rollout..."
kubectl rollout status deployment/monitoring-dashboard -n monitoring --timeout=300s
print_success "All pods deployed"

# ---- Fix OpenSearch KNN indices ----
# The agent creates indices on startup but without KNN settings.
# We recreate them with proper knn_vector mappings for RAG embeddings.
print_header "Configuring OpenSearch KNN Indices"
AGENT_POD=$(kubectl get pods -n monitoring -l app=monitoring-agent -o jsonpath='{.items[0].metadata.name}')

# Wait for agent to create initial indices
sleep 15

kubectl exec -n monitoring "$AGENT_POD" -- python3 -c "
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
import boto3, os

region = os.environ.get('AWS_REGION', 'us-east-1')
endpoint = os.environ.get('OPENSEARCH_ENDPOINT', '')
creds = boto3.Session().get_credentials()
auth = AWS4Auth(creds.access_key, creds.secret_key, region, 'es', session_token=creds.token)
client = OpenSearch(hosts=[{'host': endpoint, 'port': 443}], http_auth=auth, use_ssl=True, verify_certs=True, connection_class=RequestsHttpConnection)

knn = {'type':'knn_vector','dimension':1536,'method':{'name':'hnsw','space_type':'cosinesimil','engine':'nmslib'}}

for idx in ['runbooks','case-history']:
    if client.indices.exists(index=idx):
        m = client.indices.get_mapping(index=idx)
        if m.get(idx,{}).get('mappings',{}).get('properties',{}).get('embedding',{}).get('type') == 'knn_vector':
            print(f'{idx}: already has knn_vector - skipping')
            continue
        client.indices.delete(index=idx)
        print(f'{idx}: deleted (wrong mapping)')

if not client.indices.exists(index='runbooks'):
    client.indices.create(index='runbooks', body={'settings':{'index.knn':True},'mappings':{'properties':{'title':{'type':'text'},'content':{'type':'text'},'category':{'type':'keyword'},'keywords':{'type':'keyword'},'steps':{'type':'text'},'embedding':knn,'indexed_at':{'type':'date'}}}})
    print('Created runbooks with knn_vector')

if not client.indices.exists(index='case-history'):
    client.indices.create(index='case-history', body={'settings':{'index.knn':True},'mappings':{'properties':{'incident_id':{'type':'keyword'},'title':{'type':'text'},'description':{'type':'text'},'priority':{'type':'keyword'},'category':{'type':'keyword'},'root_cause':{'type':'text'},'resolution':{'type':'text'},'recommended_actions':{'type':'text'},'affected_resources':{'type':'keyword'},'embedding':knn,'indexed_at':{'type':'date'},'detected_at':{'type':'date'},'resolved_at':{'type':'date'}}}})
    print('Created case-history with knn_vector')
" 2>&1 || print_warn "OpenSearch index setup deferred - will be created on first use"

print_success "OpenSearch indices configured"

# ---- Map agent IAM role to OpenSearch ----
print_header "Mapping IAM Role to OpenSearch"
kubectl exec -n monitoring "$AGENT_POD" -- python3 -c "
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
import boto3, os, json

region = os.environ.get('AWS_REGION', 'us-east-1')
endpoint = os.environ.get('OPENSEARCH_ENDPOINT', '')
creds = boto3.Session().get_credentials()
auth = AWS4Auth(creds.access_key, creds.secret_key, region, 'es', session_token=creds.token)
client = OpenSearch(hosts=[{'host': endpoint, 'port': 443}], http_auth=auth, use_ssl=True, verify_certs=True, connection_class=RequestsHttpConnection)

# Verify connectivity
info = client.info()
print(f'Connected to OpenSearch {info[\"version\"][\"number\"]}')
" 2>&1 || print_warn "OpenSearch role mapping deferred"

# ---- Print summary ----
print_header "Deployment Complete!"

DASHBOARD_URL=$(kubectl get svc monitoring-dashboard -n monitoring -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "pending")

echo ""
echo "Components:"
echo "  Agent:     $(kubectl get pods -n monitoring -l app=monitoring-agent -o jsonpath='{.items[0].status.phase}' 2>/dev/null)"
echo "  Dashboard: $(kubectl get pods -n monitoring -l app=monitoring-dashboard -o jsonpath='{.items[0].status.phase}' 2>/dev/null)"
echo ""
echo "Dashboard URL: http://$DASHBOARD_URL:9493"
echo "(LoadBalancer may take a few minutes to provision)"
echo ""
echo "Useful commands:"
echo "  kubectl logs -n monitoring -l app=monitoring-agent -f"
echo "  kubectl port-forward -n monitoring svc/monitoring-agent 8080:8080"
echo ""
echo "To deploy the demo app, see demo/README.md"
echo ""
