output "ecs_cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "ecs_service_name" {
  value = aws_ecs_service.app.name
}

output "web_image_uri" {
  value = local.image_uri
}

output "app_config_json" {
  value = jsonencode(var.app_config)
}

output "task_role_arn" {
  value = aws_iam_role.task.arn
}
