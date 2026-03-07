#!/bin/bash
# =============================================================================
# Cleanup Script - Destroy all deployed resources
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================"
echo "WARNING: This will destroy ALL resources"
echo "  - Kubernetes namespaces (monitoring, demo-app)"
echo "  - EKS cluster"
echo "  - OpenSearch domain"
echo "  - RDS instances"
echo "  - VPC and networking"
echo "  - ECR repositories"
echo "  - IAM roles and policies"
echo "  - S3 buckets"
echo "  - SNS topics"
echo "========================================"
read -p "Type 'yes' to confirm: " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# Delete Kubernetes resources first (avoids orphaned LBs)
echo ""
echo "Deleting Kubernetes resources..."
kubectl delete namespace monitoring --ignore-not-found=true --timeout=120s 2>/dev/null || true
kubectl delete namespace demo-app --ignore-not-found=true --timeout=120s 2>/dev/null || true
kubectl delete clusterrole dashboard-logs-reader --ignore-not-found=true 2>/dev/null || true
kubectl delete clusterrolebinding dashboard-logs-reader --ignore-not-found=true 2>/dev/null || true

# Wait for load balancers to be cleaned up
echo "Waiting for load balancers to be released..."
sleep 30

# Destroy demo app infrastructure if it exists
if [ -f "$PROJECT_DIR/demo/app/terraform/terraform.tfstate" ]; then
    echo ""
    echo "Destroying demo app infrastructure..."
    cd "$PROJECT_DIR/demo/app/terraform"
    terraform destroy -auto-approve 2>/dev/null || echo "Demo app terraform destroy had warnings (may be OK)"
fi

# Empty S3 buckets before terraform destroy
echo ""
echo "Emptying S3 buckets..."
cd "$PROJECT_DIR/terraform"
RAG_BUCKET=$(terraform output -raw rag_s3_bucket_name 2>/dev/null || true)
if [ -n "$RAG_BUCKET" ]; then
    aws s3 rm "s3://$RAG_BUCKET" --recursive 2>/dev/null || true
fi

# Destroy main infrastructure
echo ""
echo "Destroying main infrastructure (this will take 15-20 minutes)..."
terraform destroy -auto-approve

echo ""
echo "========================================"
echo "Cleanup Complete"
echo "========================================"
