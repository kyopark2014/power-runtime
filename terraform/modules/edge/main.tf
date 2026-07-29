data "aws_s3_bucket" "storage" {
  bucket = var.s3_bucket_id
}

resource "aws_lb" "alb" {
  name               = "alb-for-${var.project_name}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.alb_security_group_id]
  subnets            = var.public_subnet_ids
  idle_timeout       = var.alb_idle_timeout_seconds

  tags = { Name = "alb-for-${var.project_name}" }
}

resource "aws_lb_target_group" "ecs" {
  name        = substr("tg-ecs-for-${var.project_name}", 0, 32)
  port        = var.app_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/api/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  stickiness {
    type            = "lb_cookie"
    cookie_duration = 86400
    enabled         = true
  }

  tags = { Name = "tg-ecs-for-${var.project_name}" }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.alb.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "Forbidden"
      status_code  = "403"
    }
  }
}

resource "aws_lb_listener_rule" "origin_header" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ecs.arn
  }

  condition {
    http_header {
      http_header_name = var.custom_header_name
      values           = [var.origin_header_value]
    }
  }
}

resource "aws_cloudfront_origin_access_identity" "s3" {
  comment = "OAI for ${var.project_name}"
}

data "aws_iam_policy_document" "s3_oai" {
  statement {
    sid       = "AllowCloudFrontOAI"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${var.s3_bucket_arn}/*"]

    principals {
      type        = "AWS"
      identifiers = [aws_cloudfront_origin_access_identity.s3.iam_arn]
    }
  }
}

resource "aws_s3_bucket_policy" "oai" {
  bucket = var.s3_bucket_id
  policy = data.aws_iam_policy_document.s3_oai.json
}

resource "aws_cloudfront_distribution" "this" {
  enabled             = true
  comment             = "Distribution for ${var.project_name}"
  price_class         = "PriceClass_200"
  default_root_object = ""
  is_ipv6_enabled     = true

  origin {
    domain_name = aws_lb.alb.dns_name
    origin_id   = "alb"

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "http-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = var.sse_origin_read_timeout_seconds
      origin_keepalive_timeout = 60
    }

    custom_header {
      name  = var.custom_header_name
      value = var.origin_header_value
    }
  }

  origin {
    domain_name = data.aws_s3_bucket.storage.bucket_regional_domain_name
    origin_id   = "s3"

    s3_origin_config {
      origin_access_identity = aws_cloudfront_origin_access_identity.s3.cloudfront_access_identity_path
    }
  }

  default_cache_behavior {
    target_origin_id       = "alb"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # CachingDisabled
    origin_request_policy_id = "216adef6-5c7f-47e4-b989-5492eafa07d3" # AllViewer
  }

  dynamic "ordered_cache_behavior" {
    for_each = toset(["/images/*", "/docs/*", "/artifacts/*"])
    content {
      path_pattern           = ordered_cache_behavior.value
      target_origin_id       = "s3"
      viewer_protocol_policy = "redirect-to-https"
      allowed_methods        = ["GET", "HEAD"]
      cached_methods         = ["GET", "HEAD"]
      compress               = true
      cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6" # CachingOptimized
      trusted_key_groups     = [var.cloudfront_key_group_id]
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  depends_on = [aws_s3_bucket_policy.oai]
}
