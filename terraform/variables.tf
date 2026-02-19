# =============================================================================
# Terraform Variables for Proactive Monitoring Bot
# =============================================================================

variable "aws_region" {
  description = "AWS region for deployment"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (e.g., dev, staging, prod)"
  type        = string
  default     = "prod"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "proactive-monitor"
}

# =============================================================================
# VPC Configuration
# =============================================================================

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of availability zones"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets"
  type        = list(string)
  default     = ["10.0.10.0/24", "10.0.20.0/24", "10.0.30.0/24"]
}

# =============================================================================
# EKS Configuration
# =============================================================================

variable "cluster_name" {
  description = "Name of the EKS cluster"
  type        = string
  default     = "monitoring-cluster"
}

variable "cluster_version" {
  description = "Kubernetes version for EKS"
  type        = string
  default     = "1.29"
}

variable "node_instance_types" {
  description = "EC2 instance types for EKS nodes"
  type        = list(string)
  default     = ["t3.large"]
}

variable "node_desired_size" {
  description = "Desired number of worker nodes"
  type        = number
  default     = 2
}

variable "node_min_size" {
  description = "Minimum number of worker nodes"
  type        = number
  default     = 1
}

variable "node_max_size" {
  description = "Maximum number of worker nodes"
  type        = number
  default     = 4
}

# =============================================================================
# OpenSearch Configuration
# =============================================================================

variable "opensearch_instance_type" {
  description = "OpenSearch instance type"
  type        = string
  default     = "t3.small.search"
}

variable "opensearch_instance_count" {
  description = "Number of OpenSearch instances"
  type        = number
  default     = 2
}

variable "opensearch_volume_size" {
  description = "EBS volume size for OpenSearch (GB)"
  type        = number
  default     = 20
}

# =============================================================================
# Jira Configuration
# =============================================================================

variable "jira_url" {
  description = "Jira instance URL"
  type        = string
}

variable "jira_project" {
  description = "Default Jira project key"
  type        = string
  default     = "OPS"
}

variable "jira_email" {
  description = "Jira service account email"
  type        = string
  sensitive   = true
}

variable "jira_api_token" {
  description = "Jira API token"
  type        = string
  sensitive   = true
}

# =============================================================================
# Notification Configuration
# =============================================================================

variable "notification_emails" {
  description = "List of email addresses for notifications"
  type        = list(string)
  default     = []
}

# =============================================================================
# Monitoring Configuration
# =============================================================================

variable "cloudwatch_namespaces" {
  description = "CloudWatch namespaces to monitor"
  type        = list(string)
  default = [
    "AWS/EC2",
    "AWS/EBS",
    "AWS/ECS",
    "AWS/EKS",
    "AWS/Lambda",
    "AWS/RDS",
    "AWS/ApplicationELB"
  ]
}

variable "collection_interval" {
  description = "How often to collect CloudWatch data (seconds)"
  type        = number
  default     = 60
}

# =============================================================================
# Tags
# =============================================================================

variable "tags" {
  description = "Common tags for all resources"
  type        = map(string)
  default = {
    Project     = "ProactiveMonitor"
    ManagedBy   = "Terraform"
    Environment = "prod"
  }
}
