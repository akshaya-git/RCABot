# =============================================================================
# Terraform Outputs for Proactive Monitoring Bot
# =============================================================================

# =============================================================================
# VPC Outputs
# =============================================================================

output "vpc_id" {
  description = "ID of the VPC"
  value       = module.vpc.vpc_id
}

output "private_subnets" {
  description = "List of private subnet IDs"
  value       = module.vpc.private_subnets
}

output "public_subnets" {
  description = "List of public subnet IDs"
  value       = module.vpc.public_subnets
}

# =============================================================================
# EKS Outputs
# =============================================================================

output "cluster_name" {
  description = "Name of the EKS cluster"
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "Endpoint for EKS control plane"
  value       = module.eks.cluster_endpoint
}

output "cluster_security_group_id" {
  description = "Security group ID attached to the EKS cluster"
  value       = module.eks.cluster_security_group_id
}

output "cluster_arn" {
  description = "ARN of the EKS cluster"
  value       = module.eks.cluster_arn
}

output "cluster_oidc_provider_arn" {
  description = "ARN of the OIDC Provider for IRSA"
  value       = module.eks.oidc_provider_arn
}

output "monitoring_agent_role_arn" {
  description = "ARN of the IAM role for the monitoring agent"
  value       = module.monitoring_agent_irsa_role.iam_role_arn
}

# =============================================================================
# OpenSearch Outputs
# =============================================================================

output "opensearch_endpoint" {
  description = "Endpoint of the OpenSearch domain"
  value       = aws_opensearch_domain.main.endpoint
}

output "opensearch_dashboard_endpoint" {
  description = "Dashboard endpoint of the OpenSearch domain"
  value       = aws_opensearch_domain.main.dashboard_endpoint
}

output "opensearch_credentials_secret_arn" {
  description = "ARN of the secret containing OpenSearch credentials"
  value       = aws_secretsmanager_secret.opensearch_credentials.arn
}

# =============================================================================
# ECR Outputs
# =============================================================================

output "ecr_repository_url" {
  description = "URL of the ECR repository for the agent image"
  value       = aws_ecr_repository.agent.repository_url
}

output "ecr_repository_arn" {
  description = "ARN of the ECR repository"
  value       = aws_ecr_repository.agent.arn
}

# =============================================================================
# Secrets Manager Outputs
# =============================================================================

output "jira_credentials_secret_arn" {
  description = "ARN of the secret containing Jira credentials"
  value       = aws_secretsmanager_secret.jira_credentials.arn
}

# =============================================================================
# SNS Outputs
# =============================================================================

output "sns_topic_arn" {
  description = "ARN of the SNS topic for alerts"
  value       = aws_sns_topic.alerts.arn
}

# =============================================================================
# Connection Commands
# =============================================================================

output "configure_kubectl" {
  description = "Command to configure kubectl"
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}

output "ecr_login" {
  description = "Command to login to ECR"
  value       = "aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${aws_ecr_repository.agent.repository_url}"
}

# =============================================================================
# Summary
# =============================================================================

output "summary" {
  description = "Deployment summary"
  value = {
    region              = var.aws_region
    cluster_name        = module.eks.cluster_name
    opensearch_endpoint = aws_opensearch_domain.main.endpoint
    ecr_repository      = aws_ecr_repository.agent.repository_url
    sns_topic           = aws_sns_topic.alerts.arn
  }
}
