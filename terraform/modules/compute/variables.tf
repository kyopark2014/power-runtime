variable "project_name" {
  type = string
}

variable "region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "ecs_security_group_id" {
  type = string
}

variable "app_port" {
  type = number
}

variable "app_data_mount_path" {
  type = string
}

variable "target_group_arn" {
  type = string
}

variable "s3_bucket_arn" {
  type = string
}

variable "s3_files_file_system_id" {
  type = string
}

variable "s3_files_file_system_arn" {
  type = string
}

variable "s3_files_access_point_arn" {
  type = string
}

variable "agent_runtime_role_arn" {
  type = string
}

variable "session_signing_key_secret_arn" {
  type = string
}

variable "cloudfront_signing_key_secret_arn" {
  type = string
}

variable "cloudfront_public_key_id" {
  type = string
}

variable "app_config" {
  type = any
}

variable "skip_docker_build" {
  type = bool
}

variable "web_image_uri" {
  type = string
}

variable "repo_root" {
  type = string
}
