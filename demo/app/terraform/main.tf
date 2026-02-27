# =============================================================================
# Demo Application Infrastructure
# Deploys RDS PostgreSQL, CloudWatch Alarms, and Demo App to existing EKS
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
  }
}

# =============================================================================
# Variables
# =============================================================================

variable "aws_region" {
  description = "AWS region where EKS cluster exists"
  type        = string
}

variable "eks_cluster_name" {
  description = "Name of the existing EKS cluster"
  type        = string
}

variable "db_username" {
  description = "Database master username"
  type        = string
  default     = "demoadmin"
}

variable "db_password" {
  description = "Database master password"
  type        = string
  sensitive   = true
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "inventory"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "demo"
}

variable "notification_email" {
  description = "Email for CloudWatch alarm notifications"
  type        = string
  default     = ""
}

# =============================================================================
# Provider Configuration
# =============================================================================

provider "aws" {
  region = var.aws_region
}

# Get EKS cluster info
data "aws_eks_cluster" "existing" {
  name = var.eks_cluster_name
}

data "aws_eks_cluster_auth" "existing" {
  name = var.eks_cluster_name
}

provider "kubernetes" {
  host                   = data.aws_eks_cluster.existing.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.existing.certificate_authority[0].data)
  token                  = data.aws_eks_cluster_auth.existing.token
}

# =============================================================================
# Data Sources
# =============================================================================

data "aws_caller_identity" "current" {}

# Get VPC from EKS cluster
data "aws_vpc" "eks_vpc" {
  id = data.aws_eks_cluster.existing.vpc_config[0].vpc_id
}

# Get private subnets
data "aws_subnets" "private" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.eks_vpc.id]
  }

  filter {
    name   = "tag:kubernetes.io/role/internal-elb"
    values = ["1"]
  }
}

# Get EKS security group
data "aws_security_group" "eks_cluster" {
  id = data.aws_eks_cluster.existing.vpc_config[0].cluster_security_group_id
}

# =============================================================================
# Locals
# =============================================================================

locals {
  name       = "demo-app-${var.environment}"
  account_id = data.aws_caller_identity.current.account_id

  common_tags = {
    Environment = var.environment
    Project     = "ProactiveMonitorDemo"
    ManagedBy   = "Terraform"
  }
}

# =============================================================================
# Security Group for RDS
# =============================================================================

resource "aws_security_group" "rds" {
  name        = "${local.name}-rds-sg"
  description = "Security group for demo RDS PostgreSQL"
  vpc_id      = data.aws_vpc.eks_vpc.id

  ingress {
    description     = "PostgreSQL from EKS"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [data.aws_security_group.eks_cluster.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${local.name}-rds-sg"
  })
}

# =============================================================================
# RDS Subnet Group
# =============================================================================

resource "aws_db_subnet_group" "demo" {
  name       = "${local.name}-subnet-group"
  subnet_ids = data.aws_subnets.private.ids

  tags = merge(local.common_tags, {
    Name = "${local.name}-subnet-group"
  })
}

# =============================================================================
# RDS PostgreSQL Instance
# =============================================================================

resource "aws_db_instance" "demo" {
  identifier = "${local.name}-postgres"

  engine               = "postgres"
  engine_version       = "15.4"
  instance_class       = "db.t3.micro"
  allocated_storage    = 20
  max_allocated_storage = 50
  storage_type         = "gp3"

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.demo.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  publicly_accessible = false
  skip_final_snapshot = true

  # Enhanced monitoring
  monitoring_interval = 60
  monitoring_role_arn = aws_iam_role.rds_monitoring.arn

  # Performance insights
  performance_insights_enabled = true
  performance_insights_retention_period = 7

  # Backup
  backup_retention_period = 1
  backup_window          = "03:00-04:00"
  maintenance_window     = "Mon:04:00-Mon:05:00"

  tags = merge(local.common_tags, {
    Name = "${local.name}-postgres"
  })
}

# =============================================================================
# IAM Role for RDS Enhanced Monitoring
# =============================================================================

resource "aws_iam_role" "rds_monitoring" {
  name = "${local.name}-rds-monitoring-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "monitoring.rds.amazonaws.com"
        }
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# =============================================================================
# ECR Repository for Demo App
# =============================================================================

resource "aws_ecr_repository" "demo_app" {
  name                 = "${local.name}-inventory"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = local.common_tags
}

# =============================================================================
# SNS Topic for Alarms
# =============================================================================

resource "aws_sns_topic" "alarms" {
  name = "${local.name}-alarms"
  tags = local.common_tags
}

resource "aws_sns_topic_subscription" "alarm_email" {
  count     = var.notification_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.notification_email
}

# =============================================================================
# CloudWatch Alarms - RDS
# =============================================================================

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${local.name}-rds-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "RDS CPU utilization is above 80%"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.demo.identifier
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "rds_connections" {
  alarm_name          = "${local.name}-rds-connections-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "DatabaseConnections"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 50
  alarm_description   = "RDS database connections exceed 50"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.demo.identifier
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "rds_freeable_memory" {
  alarm_name          = "${local.name}-rds-memory-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "FreeableMemory"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 100000000  # 100MB
  alarm_description   = "RDS freeable memory is below 100MB"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.demo.identifier
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "rds_read_latency" {
  alarm_name          = "${local.name}-rds-read-latency-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "ReadLatency"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 0.02  # 20ms
  alarm_description   = "RDS read latency exceeds 20ms"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.demo.identifier
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "rds_write_latency" {
  alarm_name          = "${local.name}-rds-write-latency-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "WriteLatency"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 0.05  # 50ms
  alarm_description   = "RDS write latency exceeds 50ms"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.demo.identifier
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "rds_free_storage" {
  alarm_name          = "${local.name}-rds-storage-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 5000000000  # 5GB
  alarm_description   = "RDS free storage space is below 5GB"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.demo.identifier
  }

  tags = local.common_tags
}

# =============================================================================
# CloudWatch Log Group for Application
# =============================================================================

resource "aws_cloudwatch_log_group" "demo_app" {
  name              = "/eks/${var.eks_cluster_name}/demo-app"
  retention_in_days = 7
  tags              = local.common_tags
}

# =============================================================================
# CloudWatch Metric Filter - Application Errors
# =============================================================================

resource "aws_cloudwatch_log_metric_filter" "app_errors" {
  name           = "${local.name}-error-filter"
  pattern        = "[timestamp, level=ERROR, ...]"
  log_group_name = aws_cloudwatch_log_group.demo_app.name

  metric_transformation {
    name      = "ApplicationErrors"
    namespace = "DemoApp"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "app_errors" {
  alarm_name          = "${local.name}-application-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApplicationErrors"
  namespace           = "DemoApp"
  period              = 300
  statistic           = "Sum"
  threshold           = 10
  alarm_description   = "Application error count exceeds 10 in 5 minutes"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  treat_missing_data  = "notBreaching"

  tags = local.common_tags
}

# =============================================================================
# Kubernetes Namespace
# =============================================================================

resource "kubernetes_namespace" "demo" {
  metadata {
    name = "demo-app"
    labels = {
      app         = "demo-inventory"
      environment = var.environment
    }
  }
}

# =============================================================================
# Kubernetes Secret for DB credentials
# =============================================================================

resource "kubernetes_secret" "db_credentials" {
  metadata {
    name      = "db-credentials"
    namespace = kubernetes_namespace.demo.metadata[0].name
  }

  data = {
    DB_HOST     = aws_db_instance.demo.address
    DB_PORT     = tostring(aws_db_instance.demo.port)
    DB_NAME     = var.db_name
    DB_USER     = var.db_username
    DB_PASSWORD = var.db_password
  }

  type = "Opaque"
}

# =============================================================================
# Kubernetes Deployment
# =============================================================================

resource "kubernetes_deployment" "demo_app" {
  metadata {
    name      = "demo-inventory"
    namespace = kubernetes_namespace.demo.metadata[0].name
    labels = {
      app = "demo-inventory"
    }
  }

  spec {
    replicas = 2

    selector {
      match_labels = {
        app = "demo-inventory"
      }
    }

    template {
      metadata {
        labels = {
          app = "demo-inventory"
        }
      }

      spec {
        container {
          name  = "demo-app"
          image = "${aws_ecr_repository.demo_app.repository_url}:latest"

          port {
            container_port = 8080
          }

          env_from {
            secret_ref {
              name = kubernetes_secret.db_credentials.metadata[0].name
            }
          }

          resources {
            limits = {
              cpu    = "500m"
              memory = "512Mi"
            }
            requests = {
              cpu    = "100m"
              memory = "128Mi"
            }
          }

          liveness_probe {
            http_get {
              path = "/health"
              port = 8080
            }
            initial_delay_seconds = 30
            period_seconds        = 10
          }

          readiness_probe {
            http_get {
              path = "/health"
              port = 8080
            }
            initial_delay_seconds = 5
            period_seconds        = 5
          }
        }
      }
    }
  }

  depends_on = [aws_db_instance.demo]
}

# =============================================================================
# Kubernetes Service
# =============================================================================

resource "kubernetes_service" "demo_app" {
  metadata {
    name      = "demo-inventory"
    namespace = kubernetes_namespace.demo.metadata[0].name
  }

  spec {
    selector = {
      app = "demo-inventory"
    }

    port {
      port        = 80
      target_port = 8080
    }

    type = "LoadBalancer"
  }
}

# =============================================================================
# Outputs
# =============================================================================

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint"
  value       = aws_db_instance.demo.endpoint
}

output "rds_address" {
  description = "RDS PostgreSQL address (without port)"
  value       = aws_db_instance.demo.address
}

output "ecr_repository_url" {
  description = "ECR repository URL for demo app"
  value       = aws_ecr_repository.demo_app.repository_url
}

output "sns_topic_arn" {
  description = "SNS topic ARN for alarms"
  value       = aws_sns_topic.alarms.arn
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group for demo app"
  value       = aws_cloudwatch_log_group.demo_app.name
}

output "kubernetes_namespace" {
  description = "Kubernetes namespace for demo app"
  value       = kubernetes_namespace.demo.metadata[0].name
}

output "app_service_hostname" {
  description = "Demo app load balancer hostname"
  value       = kubernetes_service.demo_app.status[0].load_balancer[0].ingress[0].hostname
}
