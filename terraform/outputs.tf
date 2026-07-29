output "sharing_url" {
  description = "CloudFront URL for the Web UI"
  value       = module.edge.sharing_url
}

output "knowledge_base_id" {
  value = module.data.knowledge_base_id
}

output "data_source_id" {
  value = module.data.data_source_id
}

output "s3_bucket" {
  value = module.data.s3_bucket_name
}

output "vector_bucket_name" {
  value = module.data.vector_bucket_name
}

output "vector_index_arn" {
  value = module.data.vector_index_arn
}

output "agent_runtime_arn" {
  value = module.agentcore.agent_runtime_arn
}

output "web_image_uri" {
  value = module.compute.web_image_uri
}

output "runtime_image_uri" {
  value = module.agentcore.runtime_image_uri
}

output "ecs_cluster_name" {
  value = module.compute.ecs_cluster_name
}

output "ecs_service_name" {
  value = module.compute.ecs_service_name
}

output "app_config" {
  description = "Normalized config map (same keys as application/config.json)"
  value       = local.app_config
  sensitive   = true
}

output "config_for_write" {
  description = "Flat outputs for scripts/write_config.py"
  value = merge(local.app_config, {
    knowledge_base_role = module.data.knowledge_base_role_arn
    s3_arn              = module.data.s3_bucket_arn
    agent_runtime_role  = module.agentcore.agent_runtime_role_arn
    latest_image_tag = (
      length(split(":", module.compute.web_image_uri)) > 1
      ? element(split(":", module.compute.web_image_uri), length(split(":", module.compute.web_image_uri)) - 1)
      : ""
    )
    build_number = (
      length(split(":", module.compute.web_image_uri)) > 1
      ? element(split(":", module.compute.web_image_uri), length(split(":", module.compute.web_image_uri)) - 1)
      : ""
    )
  })
  sensitive = true
}
