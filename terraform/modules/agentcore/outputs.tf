output "agent_runtime_arn" {
  value = aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn
}

output "agent_runtime_id" {
  value = aws_bedrockagentcore_agent_runtime.this.agent_runtime_id
}

output "agent_runtime_role_arn" {
  value = aws_iam_role.runtime.arn
}

output "guardrail_id" {
  value = aws_bedrock_guardrail.this.guardrail_id
}

output "guardrail_arn" {
  value = aws_bedrock_guardrail.this.guardrail_arn
}

output "runtime_image_uri" {
  value = local.container_uri
}

output "ecr_repository_url" {
  value = aws_ecr_repository.runtime.repository_url
}
