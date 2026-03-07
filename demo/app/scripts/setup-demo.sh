#!/bin/bash
# =============================================================================
# Demo Application Setup Script
# Sets up the demo inventory application on an existing EKS cluster
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="$SCRIPT_DIR/../terraform"

print_header() {
    echo -e "\n${BLUE}============================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}============================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    print_header "Checking Prerequisites"

    local missing=()

    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        missing+=("aws-cli")
    else
        print_success "AWS CLI found"
    fi

    # Check kubectl
    if ! command -v kubectl &> /dev/null; then
        missing+=("kubectl")
    else
        print_success "kubectl found"
    fi

    # Check Terraform
    if ! command -v terraform &> /dev/null; then
        missing+=("terraform")
    else
        print_success "Terraform found"
    fi

    # Check Docker
    if ! command -v docker &> /dev/null; then
        missing+=("docker")
    else
        print_success "Docker found"
    fi

    # Check jq
    if ! command -v jq &> /dev/null; then
        missing+=("jq")
    else
        print_success "jq found"
    fi

    if [ ${#missing[@]} -ne 0 ]; then
        print_error "Missing prerequisites: ${missing[*]}"
        echo "Please install the missing tools and try again."
        exit 1
    fi
}

# Get AWS region
get_region() {
    print_header "AWS Region Selection"

    echo "Available AWS regions with EKS support:"
    echo "  - us-east-1 (N. Virginia)"
    echo "  - us-east-2 (Ohio)"
    echo "  - us-west-1 (N. California)"
    echo "  - us-west-2 (Oregon)"
    echo "  - eu-west-1 (Ireland)"
    echo "  - eu-west-2 (London)"
    echo "  - eu-central-1 (Frankfurt)"
    echo "  - ap-southeast-1 (Singapore)"
    echo "  - ap-southeast-2 (Sydney)"
    echo "  - ap-northeast-1 (Tokyo)"
    echo ""

    read -p "Enter AWS region: " AWS_REGION

    if [ -z "$AWS_REGION" ]; then
        print_error "Region cannot be empty"
        exit 1
    fi

    # Validate region
    if ! aws ec2 describe-regions --region-names "$AWS_REGION" &> /dev/null; then
        print_error "Invalid AWS region: $AWS_REGION"
        exit 1
    fi

    print_success "Using region: $AWS_REGION"
    export AWS_DEFAULT_REGION="$AWS_REGION"
}

# Get and validate EKS cluster
get_eks_cluster() {
    print_header "EKS Cluster Selection"

    # List available clusters in the region
    print_info "Checking for EKS clusters in $AWS_REGION..."

    clusters=$(aws eks list-clusters --region "$AWS_REGION" --output json 2>/dev/null | jq -r '.clusters[]' 2>/dev/null || true)

    if [ -z "$clusters" ]; then
        print_error "No EKS clusters found in region $AWS_REGION"
        echo ""
        echo "Please ensure you have an EKS cluster deployed in this region."
        echo "You can deploy one using the infrastructure in /terraform/eks/"
        exit 1
    fi

    echo "Available EKS clusters in $AWS_REGION:"
    echo "$clusters" | while read -r cluster; do
        echo "  - $cluster"
    done
    echo ""

    read -p "Enter EKS cluster name: " EKS_CLUSTER_NAME

    if [ -z "$EKS_CLUSTER_NAME" ]; then
        print_error "Cluster name cannot be empty"
        exit 1
    fi

    # Validate cluster exists
    print_info "Validating cluster '$EKS_CLUSTER_NAME'..."

    if ! aws eks describe-cluster --name "$EKS_CLUSTER_NAME" --region "$AWS_REGION" &> /dev/null; then
        print_error "EKS cluster '$EKS_CLUSTER_NAME' not found in region $AWS_REGION"
        exit 1
    fi

    # Get cluster details
    cluster_status=$(aws eks describe-cluster --name "$EKS_CLUSTER_NAME" --region "$AWS_REGION" --query 'cluster.status' --output text)

    if [ "$cluster_status" != "ACTIVE" ]; then
        print_error "EKS cluster '$EKS_CLUSTER_NAME' is not ACTIVE (status: $cluster_status)"
        exit 1
    fi

    print_success "EKS cluster '$EKS_CLUSTER_NAME' is ACTIVE"

    # Update kubeconfig
    print_info "Updating kubeconfig..."
    aws eks update-kubeconfig --name "$EKS_CLUSTER_NAME" --region "$AWS_REGION"

    # Test kubectl connectivity
    if kubectl cluster-info &> /dev/null; then
        print_success "kubectl connected to cluster"
    else
        print_error "Failed to connect kubectl to cluster"
        exit 1
    fi
}

# Get database password
get_db_password() {
    print_header "Database Configuration"

    read -sp "Enter database password (min 8 characters): " DB_PASSWORD
    echo ""

    if [ ${#DB_PASSWORD} -lt 8 ]; then
        print_error "Password must be at least 8 characters"
        exit 1
    fi

    read -sp "Confirm database password: " DB_PASSWORD_CONFIRM
    echo ""

    if [ "$DB_PASSWORD" != "$DB_PASSWORD_CONFIRM" ]; then
        print_error "Passwords do not match"
        exit 1
    fi

    print_success "Database password set"
}

# Optional email for notifications
get_notification_email() {
    print_header "Notification Configuration (Optional)"

    read -p "Enter email for CloudWatch alarm notifications (press Enter to skip): " NOTIFICATION_EMAIL

    if [ -n "$NOTIFICATION_EMAIL" ]; then
        print_info "Notifications will be sent to: $NOTIFICATION_EMAIL"
        print_warning "You will need to confirm the SNS subscription via email"
    else
        print_info "Skipping email notifications"
    fi
}

# Deploy infrastructure with Terraform
deploy_infrastructure() {
    print_header "Deploying Infrastructure"

    cd "$TERRAFORM_DIR"

    # Create terraform.tfvars
    cat > terraform.tfvars <<EOF
aws_region         = "$AWS_REGION"
eks_cluster_name   = "$EKS_CLUSTER_NAME"
db_username        = "demoadmin"
db_password        = "$DB_PASSWORD"
db_name            = "inventory"
environment        = "demo"
notification_email = "$NOTIFICATION_EMAIL"
EOF

    print_info "terraform.tfvars created"

    # Initialize Terraform
    print_info "Initializing Terraform..."
    terraform init

    # Plan
    print_info "Planning infrastructure..."
    terraform plan -out=tfplan

    # Show summary
    echo ""
    print_warning "The following resources will be created:"
    echo "  - RDS PostgreSQL instance (db.t3.micro)"
    echo "  - ECR repository for demo app"
    echo "  - CloudWatch alarms (6 for RDS, 1 for app)"
    echo "  - SNS topic for alerts"
    echo "  - Security groups"
    echo "  - Kubernetes namespace, deployment, and service"
    echo ""

    read -p "Do you want to proceed? (yes/no): " confirm

    if [ "$confirm" != "yes" ]; then
        print_info "Deployment cancelled"
        exit 0
    fi

    # Apply
    print_info "Applying infrastructure..."
    terraform apply tfplan

    # Get outputs
    RDS_ENDPOINT=$(terraform output -raw rds_endpoint)
    ECR_REPO=$(terraform output -raw ecr_repository_url)

    print_success "Infrastructure deployed successfully"
}

# Build and push Docker image
build_and_push_image() {
    print_header "Building and Pushing Docker Image"

    cd "$SCRIPT_DIR/.."

    # Login to ECR
    print_info "Logging into ECR..."
    aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REPO"

    # Build image
    print_info "Building Docker image..."
    docker build -t demo-inventory:latest .

    # Tag and push
    print_info "Pushing to ECR..."
    docker tag demo-inventory:latest "$ECR_REPO:latest"
    docker push "$ECR_REPO:latest"

    print_success "Docker image pushed to ECR"
}

# Seed database
seed_database() {
    print_header "Seeding Database"

    # Wait for RDS to be fully available
    print_info "Waiting for database to be ready..."
    sleep 30

    # Get RDS address (without port)
    RDS_ADDRESS=$(cd "$TERRAFORM_DIR" && terraform output -raw rds_address)

    # Run seed script via kubectl
    print_info "Creating database seed job..."

    kubectl run db-seed \
        --namespace demo-app \
        --image=postgres:15 \
        --restart=Never \
        --rm \
        -i \
        --env="PGPASSWORD=$DB_PASSWORD" \
        -- psql -h "$RDS_ADDRESS" -U demoadmin -d inventory < "$SCRIPT_DIR/seed-data.sql"

    print_success "Database seeded successfully"
}

# Restart deployment to pull new image
restart_deployment() {
    print_header "Restarting Application"

    kubectl rollout restart deployment/demo-inventory -n demo-app

    print_info "Waiting for deployment to be ready..."
    kubectl rollout status deployment/demo-inventory -n demo-app --timeout=300s

    print_success "Application restarted"
}

# Get application URL
get_app_url() {
    print_header "Application URL"

    print_info "Waiting for load balancer..."

    for i in {1..30}; do
        APP_URL=$(kubectl get svc demo-inventory -n demo-app -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)
        if [ -n "$APP_URL" ]; then
            break
        fi
        echo -ne "\r[INFO] Waiting for load balancer... ($i/30)"
        sleep 10
    done
    echo ""

    if [ -z "$APP_URL" ]; then
        print_warning "Load balancer not ready yet. Check later with:"
        echo "  kubectl get svc demo-inventory -n demo-app"
    else
        print_success "Application URL: http://$APP_URL"
        echo ""
        echo "You can access the demo inventory app at:"
        echo "  http://$APP_URL"
        echo ""
        echo "Health check:"
        echo "  http://$APP_URL/health"
    fi
}

# Print summary
print_summary() {
    print_header "Setup Complete!"

    echo "Resources created:"
    echo "  - RDS PostgreSQL: $RDS_ENDPOINT"
    echo "  - ECR Repository: $ECR_REPO"
    echo "  - Kubernetes Namespace: demo-app"
    echo ""
    echo "CloudWatch Alarms:"
    echo "  - demo-app-demo-rds-cpu-high"
    echo "  - demo-app-demo-rds-connections-high"
    echo "  - demo-app-demo-rds-memory-low"
    echo "  - demo-app-demo-rds-read-latency-high"
    echo "  - demo-app-demo-rds-write-latency-high"
    echo "  - demo-app-demo-rds-storage-low"
    echo "  - demo-app-demo-application-errors"
    echo ""
    echo "Next steps:"
    echo "  1. Access the demo app at: http://$APP_URL"
    echo "  2. Run anomaly generator: ./generate-anomaly.sh"
    echo "  3. Monitor CloudWatch alarms in AWS Console"
    echo "  4. Configure the Proactive Monitoring Agent to collect from these alarms"
    echo ""
    if [ -n "$NOTIFICATION_EMAIL" ]; then
        print_warning "Don't forget to confirm the SNS subscription email!"
    fi
}

# Cleanup function
cleanup() {
    print_header "Cleanup"

    read -p "Do you want to destroy all demo resources? (yes/no): " confirm

    if [ "$confirm" != "yes" ]; then
        print_info "Cleanup cancelled"
        return
    fi

    cd "$TERRAFORM_DIR"
    terraform destroy -auto-approve

    print_success "All demo resources destroyed"
}

# Main
main() {
    print_header "Proactive Monitoring Bot - Demo Setup"

    echo "This script will deploy a demo inventory application to your"
    echo "existing EKS cluster, along with RDS PostgreSQL and CloudWatch"
    echo "alarms for testing the Proactive Monitoring Bot."
    echo ""

    if [ "$1" == "cleanup" ]; then
        cleanup
        exit 0
    fi

    check_prerequisites
    get_region
    get_eks_cluster
    get_db_password
    get_notification_email
    deploy_infrastructure
    build_and_push_image
    seed_database
    restart_deployment
    get_app_url
    print_summary
}

main "$@"
