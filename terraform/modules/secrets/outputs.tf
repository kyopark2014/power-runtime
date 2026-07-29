output "alb_origin_header_secret_arn" {
  value = aws_secretsmanager_secret.origin_header.arn
}

output "alb_origin_header_value" {
  value     = random_password.origin_header.result
  sensitive = true
}

output "session_signing_key_secret_arn" {
  value = aws_secretsmanager_secret.session_signing.arn
}

output "cloudfront_signing_key_secret_arn" {
  value = aws_secretsmanager_secret.cloudfront_signing.arn
}

output "cloudfront_public_key_id" {
  value = aws_cloudfront_public_key.this.id
}

output "cloudfront_key_group_id" {
  value = aws_cloudfront_key_group.this.id
}
