output "vpc_id" {
  value = aws_vpc.this.id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "alb_security_group_id" {
  value = aws_security_group.alb.id
}

output "ecs_security_group_id" {
  value = aws_security_group.ecs.id
}

output "agent_runtime_security_group_id" {
  value = aws_security_group.agent_runtime.id
}

output "s3files_mount_security_group_id" {
  value = aws_security_group.s3files_mount.id
}
