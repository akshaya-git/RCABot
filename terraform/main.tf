# =============================================================================
# Proactive Monitoring Bot - Main Terraform Configuration
# =============================================================================

terraform {
  required_version = ">= 1.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.25"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.12"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  # Uncomment to use S3 backend for state storage
  # backend "s3" {
  #   bucket         = "your-terraform-state-bucket"
  #   key            = "proactive-monitor/terraform.tfstate"
  #   region         = "us-east-1"
  #   encrypt        = true
  #   dynamodb_table = "terraform-locks"
  # }
}

# =============================================================================
# Providers
# =============================================================================

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.tags
  }
}

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name]
  }
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name]
    }
  }
}

# =============================================================================
# Data Sources
# =============================================================================

data "aws_caller_identity" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

# =============================================================================
# Local Values
# =============================================================================

locals {
  name            = "${var.project_name}-${var.environment}"
  cluster_name    = "${var.cluster_name}-${var.environment}"
  account_id      = data.aws_caller_identity.current.account_id

  azs = length(var.availability_zones) > 0 ? var.availability_zones : slice(data.aws_availability_zones.available.names, 0, 3)

  common_tags = merge(var.tags, {
    Cluster = local.cluster_name
  })
}

# =============================================================================
# Secrets Manager - Store sensitive configuration
# =============================================================================

resource "aws_secretsmanager_secret" "jira_credentials" {
  name        = "${local.name}/jira-credentials"
  description = "Jira API credentials for monitoring bot"

  tags = local.common_tags
}

resource "aws_secretsmanager_secret_version" "jira_credentials" {
  secret_id = aws_secretsmanager_secret.jira_credentials.id
  secret_string = jsonencode({
    url       = var.jira_url
    email     = var.jira_email
    api_token = var.jira_api_token
    project   = var.jira_project
  })
}

# =============================================================================
# SNS Topic for Notifications
# =============================================================================

resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"

  tags = local.common_tags
}

resource "aws_sns_topic_subscription" "email" {
  count     = length(var.notification_emails)
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.notification_emails[count.index]
}

# =============================================================================
# SES for Email Notifications (if in supported region)
# =============================================================================

resource "aws_ses_email_identity" "notifications" {
  count = length(var.notification_emails) > 0 ? 1 : 0
  email = var.notification_emails[0]
}

# =============================================================================
# ECR Repository for Agent Image
# =============================================================================

resource "aws_ecr_repository" "agent" {
  name                 = "${local.name}-agent"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = local.common_tags
}

resource "aws_ecr_lifecycle_policy" "agent" {
  repository = aws_ecr_repository.agent.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
