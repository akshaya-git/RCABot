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

resource "aws_secretsmanager_secret" "servicenow_credentials" {
  name        = "${local.name}/servicenow-credentials"
  description = "ServiceNow API credentials for monitoring bot"

  tags = local.common_tags
}

resource "aws_secretsmanager_secret_version" "servicenow_credentials" {
  secret_id = aws_secretsmanager_secret.servicenow_credentials.id
  secret_string = jsonencode({
    instance         = var.servicenow_instance
    username         = var.servicenow_username
    password         = var.servicenow_password
    assignment_group = var.servicenow_assignment_group
    caller_id        = var.servicenow_caller_id
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

# =============================================================================
# S3 Bucket for RAG Data Storage
# =============================================================================

resource "aws_s3_bucket" "rag_data" {
  bucket = "${local.name}-rag-data-${local.account_id}"

  tags = merge(local.common_tags, {
    Purpose = "RAG knowledge base storage"
  })
}

resource "aws_s3_bucket_versioning" "rag_data" {
  bucket = aws_s3_bucket.rag_data.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "rag_data" {
  bucket = aws_s3_bucket.rag_data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "rag_data" {
  bucket = aws_s3_bucket.rag_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "rag_data" {
  bucket = aws_s3_bucket.rag_data.id

  rule {
    id     = "archive-old-versions"
    status = "Enabled"

    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "STANDARD_IA"
    }

    noncurrent_version_transition {
      noncurrent_days = 90
      storage_class   = "GLACIER"
    }

    noncurrent_version_expiration {
      noncurrent_days = 365
    }
  }
}

# Create folder structure in S3
resource "aws_s3_object" "runbooks_folder" {
  bucket  = aws_s3_bucket.rag_data.id
  key     = "runbooks/"
  content = ""
}

resource "aws_s3_object" "case_history_folder" {
  bucket  = aws_s3_bucket.rag_data.id
  key     = "case-history/"
  content = ""
}

resource "aws_s3_object" "imports_folder" {
  bucket  = aws_s3_bucket.rag_data.id
  key     = "imports/"
  content = ""
}

# S3 Event Notification for automatic indexing (optional - via SNS)
resource "aws_sns_topic" "rag_sync" {
  name = "${local.name}-rag-sync"

  tags = local.common_tags
}

resource "aws_sns_topic_policy" "rag_sync" {
  arn = aws_sns_topic.rag_sync.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "s3.amazonaws.com"
        }
        Action   = "sns:Publish"
        Resource = aws_sns_topic.rag_sync.arn
        Condition = {
          ArnLike = {
            "aws:SourceArn" = aws_s3_bucket.rag_data.arn
          }
        }
      }
    ]
  })
}

resource "aws_s3_bucket_notification" "rag_data" {
  bucket = aws_s3_bucket.rag_data.id

  topic {
    topic_arn     = aws_sns_topic.rag_sync.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "runbooks/"
    filter_suffix = ".json"
  }

  topic {
    topic_arn     = aws_sns_topic.rag_sync.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "case-history/"
    filter_suffix = ".json"
  }

  depends_on = [aws_sns_topic_policy.rag_sync]
}
