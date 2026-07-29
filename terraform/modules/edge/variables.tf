variable "project_name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "alb_security_group_id" {
  type = string
}

variable "app_port" {
  type = number
}

variable "alb_idle_timeout_seconds" {
  type = number
}

variable "sse_origin_read_timeout_seconds" {
  type = number
}

variable "custom_header_name" {
  type = string
}

variable "origin_header_value" {
  type      = string
  sensitive = true
}

variable "cloudfront_key_group_id" {
  type = string
}

variable "s3_bucket_id" {
  type = string
}

variable "s3_bucket_arn" {
  type = string
}

variable "s3_bucket_regional_domain_name" {
  type    = string
  default = ""
}
