# =============================================================================
# IAM Policies for Proactive Monitoring Bot
# =============================================================================

# =============================================================================
# CloudWatch Access Policy
# =============================================================================

resource "aws_iam_policy" "monitoring_agent_cloudwatch" {
  name        = "${local.name}-cloudwatch-policy"
  description = "Allow monitoring agent to read CloudWatch data"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudWatchReadAccess"
        Effect = "Allow"
        Action = [
          "cloudwatch:DescribeAlarms",
          "cloudwatch:DescribeAlarmsForMetric",
          "cloudwatch:GetMetricData",
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:ListMetrics",
          "cloudwatch:DescribeAnomalyDetectors",
          "cloudwatch:GetInsightRuleReport"
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchLogsReadAccess"
        Effect = "Allow"
        Action = [
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
          "logs:GetLogEvents",
          "logs:FilterLogEvents",
          "logs:StartQuery",
          "logs:StopQuery",
          "logs:GetQueryResults",
          "logs:DescribeQueries"
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchLogsInsights"
        Effect = "Allow"
        Action = [
          "logs:GetLogGroupFields",
          "logs:GetLogRecord",
          "logs:StartLiveTail",
          "logs:StopLiveTail"
        ]
        Resource = "*"
      },
      {
        Sid    = "EC2DescribeForMetrics"
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstances",
          "ec2:DescribeVolumes",
          "ec2:DescribeTags"
        ]
        Resource = "*"
      },
      {
        Sid    = "ResourceGroupsTagging"
        Effect = "Allow"
        Action = [
          "tag:GetResources",
          "tag:GetTagKeys",
          "tag:GetTagValues"
        ]
        Resource = "*"
      }
    ]
  })

  tags = local.common_tags
}

# =============================================================================
# Bedrock Access Policy
# =============================================================================

resource "aws_iam_policy" "monitoring_agent_bedrock" {
  name        = "${local.name}-bedrock-policy"
  description = "Allow monitoring agent to use Bedrock"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockInvoke"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-*",
          "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-*"
        ]
      },
      {
        Sid    = "BedrockList"
        Effect = "Allow"
        Action = [
          "bedrock:ListFoundationModels",
          "bedrock:GetFoundationModel"
        ]
        Resource = "*"
      }
    ]
  })

  tags = local.common_tags
}

# =============================================================================
# OpenSearch Access Policy
# =============================================================================

resource "aws_iam_policy" "monitoring_agent_opensearch" {
  name        = "${local.name}-opensearch-policy"
  description = "Allow monitoring agent to access OpenSearch"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "OpenSearchAccess"
        Effect = "Allow"
        Action = [
          "es:ESHttpGet",
          "es:ESHttpPost",
          "es:ESHttpPut",
          "es:ESHttpDelete",
          "es:ESHttpHead"
        ]
        Resource = [
          "${aws_opensearch_domain.main.arn}",
          "${aws_opensearch_domain.main.arn}/*"
        ]
      }
    ]
  })

  tags = local.common_tags
}

# =============================================================================
# Secrets Manager Access Policy
# =============================================================================

resource "aws_iam_policy" "monitoring_agent_secrets" {
  name        = "${local.name}-secrets-policy"
  description = "Allow monitoring agent to read secrets"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SecretsManagerRead"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = [
          aws_secretsmanager_secret.servicenow_credentials.arn
        ]
      }
    ]
  })

  tags = local.common_tags
}

# =============================================================================
# S3 RAG Data Access Policy
# =============================================================================

resource "aws_iam_policy" "monitoring_agent_s3_rag" {
  name        = "${local.name}-s3-rag-policy"
  description = "Allow monitoring agent to access RAG data in S3"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3RAGDataRead"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = [
          aws_s3_bucket.rag_data.arn,
          "${aws_s3_bucket.rag_data.arn}/*"
        ]
      },
      {
        Sid    = "S3RAGDataWrite"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = [
          "${aws_s3_bucket.rag_data.arn}/case-history/*",
          "${aws_s3_bucket.rag_data.arn}/exports/*"
        ]
      }
    ]
  })

  tags = local.common_tags
}

# =============================================================================
# SNS Publish Policy
# =============================================================================

resource "aws_iam_policy" "monitoring_agent_sns" {
  name        = "${local.name}-sns-policy"
  description = "Allow monitoring agent to publish to SNS"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SNSPublish"
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = [
          aws_sns_topic.alerts.arn
        ]
      }
    ]
  })

  tags = local.common_tags
}
