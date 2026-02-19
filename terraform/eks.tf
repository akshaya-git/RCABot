# =============================================================================
# EKS Cluster Configuration for Proactive Monitoring Bot
# =============================================================================

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = local.cluster_name
  cluster_version = var.cluster_version

  # Networking
  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Cluster endpoint access
  cluster_endpoint_public_access  = true
  cluster_endpoint_private_access = true

  # Cluster addons
  cluster_addons = {
    coredns = {
      most_recent = true
    }
    kube-proxy = {
      most_recent = true
    }
    vpc-cni = {
      most_recent = true
    }
    aws-ebs-csi-driver = {
      most_recent              = true
      service_account_role_arn = module.ebs_csi_irsa_role.iam_role_arn
    }
  }

  # Node groups
  eks_managed_node_groups = {
    monitoring = {
      name           = "monitoring-nodes"
      instance_types = var.node_instance_types

      min_size     = var.node_min_size
      max_size     = var.node_max_size
      desired_size = var.node_desired_size

      # Use latest Amazon Linux 2023 AMI
      ami_type = "AL2023_x86_64_STANDARD"

      # Node labels
      labels = {
        role = "monitoring"
      }

      # Taints (optional - uncomment to dedicate nodes)
      # taints = [
      #   {
      #     key    = "dedicated"
      #     value  = "monitoring"
      #     effect = "NO_SCHEDULE"
      #   }
      # ]

      tags = local.common_tags
    }
  }

  # Enable IRSA
  enable_irsa = true

  # Cluster access
  enable_cluster_creator_admin_permissions = true

  tags = local.common_tags
}

# =============================================================================
# IRSA Role for EBS CSI Driver
# =============================================================================

module "ebs_csi_irsa_role" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name             = "${local.name}-ebs-csi-role"
  attach_ebs_csi_policy = true

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:ebs-csi-controller-sa"]
    }
  }

  tags = local.common_tags
}

# =============================================================================
# IRSA Role for Monitoring Agent
# =============================================================================

module "monitoring_agent_irsa_role" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.0"

  role_name = "${local.name}-agent-role"

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["monitoring:monitoring-agent-sa"]
    }
  }

  role_policy_arns = {
    cloudwatch     = aws_iam_policy.monitoring_agent_cloudwatch.arn
    bedrock        = aws_iam_policy.monitoring_agent_bedrock.arn
    opensearch     = aws_iam_policy.monitoring_agent_opensearch.arn
    secrets        = aws_iam_policy.monitoring_agent_secrets.arn
    sns            = aws_iam_policy.monitoring_agent_sns.arn
  }

  tags = local.common_tags
}

# =============================================================================
# Kubernetes Namespace and Service Account
# =============================================================================

resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = "monitoring"

    labels = {
      name        = "monitoring"
      environment = var.environment
    }
  }

  depends_on = [module.eks]
}

resource "kubernetes_service_account" "monitoring_agent" {
  metadata {
    name      = "monitoring-agent-sa"
    namespace = kubernetes_namespace.monitoring.metadata[0].name

    annotations = {
      "eks.amazonaws.com/role-arn" = module.monitoring_agent_irsa_role.iam_role_arn
    }

    labels = {
      app = "monitoring-agent"
    }
  }
}

# =============================================================================
# ConfigMap for Agent Configuration
# =============================================================================

resource "kubernetes_config_map" "monitoring_agent" {
  metadata {
    name      = "monitoring-agent-config"
    namespace = kubernetes_namespace.monitoring.metadata[0].name
  }

  data = {
    AWS_REGION            = var.aws_region
    JIRA_PROJECT          = var.jira_project
    OPENSEARCH_ENDPOINT   = aws_opensearch_domain.main.endpoint
    SNS_TOPIC_ARN         = aws_sns_topic.alerts.arn
    COLLECTION_INTERVAL   = tostring(var.collection_interval)
    BEDROCK_MODEL_ID      = "anthropic.claude-3-sonnet-20240229-v1:0"
    CLOUDWATCH_NAMESPACES = join(",", var.cloudwatch_namespaces)
    SECRETS_ARN           = aws_secretsmanager_secret.jira_credentials.arn
  }

  depends_on = [kubernetes_namespace.monitoring]
}
