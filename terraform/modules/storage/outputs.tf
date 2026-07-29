output "file_system_id" {
  value = aws_s3files_file_system.this.id
}

output "file_system_arn" {
  value = aws_s3files_file_system.this.arn
}

output "access_point_arn" {
  value = aws_s3files_access_point.this.arn
}

output "agent_runtime_vpc_subnets" {
  value = var.private_subnet_ids
}

output "agent_runtime_security_groups" {
  value = [var.agent_runtime_security_group_id]
}
