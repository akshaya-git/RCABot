# =============================================================================
# OpenSearch Domain for Proactive Monitoring Bot
# Used for RAG (runbooks, case history) and incident storage
# =============================================================================

resource "aws_opensearch_domain" "main" {
  domain_name    = "${local.name}-search"
  engine_version = "OpenSearch_2.11"

  cluster_config {
    instance_type            = var.opensearch_instance_type
    instance_count           = var.opensearch_instance_count
    zone_awareness_enabled   = var.opensearch_instance_count > 1
    dedicated_master_enabled = false

    dynamic "zone_awareness_config" {
      for_each = var.opensearch_instance_count > 1 ? [1] : []
      content {
        availability_zone_count = min(var.opensearch_instance_count, 3)
      }
    }
  }

  ebs_options {
    ebs_enabled = true
    volume_size = var.opensearch_volume_size
    volume_type = "gp3"
  }

  vpc_options {
    subnet_ids         = slice(module.vpc.private_subnets, 0, min(var.opensearch_instance_count, 3))
    security_group_ids = [aws_security_group.opensearch.id]
  }

  encrypt_at_rest {
    enabled = true
  }

  node_to_node_encryption {
    enabled = true
  }

  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-2019-07"
  }

  advanced_security_options {
    enabled                        = true
    internal_user_database_enabled = true
    master_user_options {
      master_user_name     = "admin"
      master_user_password = random_password.opensearch_admin.result
    }
  }

  access_policies = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = module.monitoring_agent_irsa_role.iam_role_arn
        }
        Action   = "es:*"
        Resource = "arn:aws:es:${var.aws_region}:${local.account_id}:domain/${local.name}-search/*"
      }
    ]
  })

  log_publishing_options {
    cloudwatch_log_group_arn = aws_cloudwatch_log_group.opensearch.arn
    log_type                 = "INDEX_SLOW_LOGS"
  }

  log_publishing_options {
    cloudwatch_log_group_arn = aws_cloudwatch_log_group.opensearch.arn
    log_type                 = "SEARCH_SLOW_LOGS"
  }

  tags = local.common_tags
}

# =============================================================================
# Random Password for OpenSearch Admin
# =============================================================================

resource "random_password" "opensearch_admin" {
  length           = 16
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

# Store OpenSearch credentials in Secrets Manager
resource "aws_secretsmanager_secret" "opensearch_credentials" {
  name        = "${local.name}/opensearch-credentials"
  description = "OpenSearch admin credentials"

  tags = local.common_tags
}

resource "aws_secretsmanager_secret_version" "opensearch_credentials" {
  secret_id = aws_secretsmanager_secret.opensearch_credentials.id
  secret_string = jsonencode({
    username = "admin"
    password = random_password.opensearch_admin.result
    endpoint = aws_opensearch_domain.main.endpoint
  })
}

# =============================================================================
# Security Group for OpenSearch
# =============================================================================

resource "aws_security_group" "opensearch" {
  name        = "${local.name}-opensearch-sg"
  description = "Security group for OpenSearch domain"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
    description     = "Allow HTTPS from EKS nodes"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${local.name}-opensearch-sg"
  })
}

# =============================================================================
# CloudWatch Log Group for OpenSearch
# =============================================================================

resource "aws_cloudwatch_log_group" "opensearch" {
  name              = "/aws/opensearch/${local.name}"
  retention_in_days = 30

  tags = local.common_tags
}

resource "aws_cloudwatch_log_resource_policy" "opensearch" {
  policy_name = "${local.name}-opensearch-logs"

  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "es.amazonaws.com"
        }
        Action = [
          "logs:PutLogEvents",
          "logs:PutLogEventsBatch",
          "logs:CreateLogStream"
        ]
        Resource = "${aws_cloudwatch_log_group.opensearch.arn}:*"
      }
    ]
  })
}
