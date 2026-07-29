# Secrets + CloudFront signing (CDK SecretsStack). No Cognito — power-runtime
# Web UI uses a plain user_id session cookie, unlike cde-pilot.

resource "random_password" "origin_header" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "origin_header" {
  name                    = var.alb_origin_header_secret_name
  description             = "CloudFront to ALB origin verification header for ${var.project_name}"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "origin_header" {
  secret_id     = aws_secretsmanager_secret.origin_header.id
  secret_string = random_password.origin_header.result
}

resource "random_password" "session_signing" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "session_signing" {
  name                    = var.session_signing_key_secret_name
  description             = "HMAC session signing key for ${var.project_name}"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "session_signing" {
  secret_id     = aws_secretsmanager_secret.session_signing.id
  secret_string = random_password.session_signing.result
}

resource "tls_private_key" "cloudfront" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "aws_cloudfront_public_key" "this" {
  name        = "${var.project_name}-cf-public-key"
  encoded_key = tls_private_key.cloudfront.public_key_pem
  comment     = "Signing public key for ${var.project_name}"
}

resource "aws_cloudfront_key_group" "this" {
  name  = "${var.project_name}-cf-key-group"
  items = [aws_cloudfront_public_key.this.id]
}

resource "aws_secretsmanager_secret" "cloudfront_signing" {
  name                    = var.cloudfront_signing_key_secret_name
  description             = "CloudFront signing key material for ${var.project_name}"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "cloudfront_signing" {
  secret_id = aws_secretsmanager_secret.cloudfront_signing.id
  secret_string = jsonencode({
    private_key_pem = tls_private_key.cloudfront.private_key_pem
    public_key_pem  = tls_private_key.cloudfront.public_key_pem
    public_key_id   = aws_cloudfront_public_key.this.id
    key_group_id    = aws_cloudfront_key_group.this.id
  })
}
