#!/bin/bash
# =============================================================================
# Cleanup Script - Destroy all resources
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================"
echo "WARNING: This will destroy all resources!"
echo "========================================"
read -p "Are you sure? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# Delete Kubernetes resources
echo "Deleting Kubernetes resources..."
kubectl delete namespace monitoring --ignore-not-found=true || true

# Destroy Terraform resources
echo "Destroying infrastructure..."
cd "$PROJECT_DIR/terraform"
terraform destroy -auto-approve

echo "========================================"
echo "Cleanup Complete!"
echo "========================================"
