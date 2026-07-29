variable "project_name" {
  description = "Project name prefix (parity with CDE_PROJECT_NAME / CDK PROJECT_NAME)"
  type        = string
  default     = "power-runtime"
}

variable "region" {
  description = "Primary AWS region"
  type        = string
  default     = "us-west-2"
}

variable "skip_docker_build" {
  description = "Skip local Docker build/push; requires runtime_image_uri and web_image_uri"
  type        = bool
  default     = false
}

variable "runtime_image_uri" {
  description = "Pre-built AgentCore Runtime image URI (required when skip_docker_build=true)"
  type        = string
  default     = ""
}

variable "web_image_uri" {
  description = "Pre-built Web UI image URI (required when skip_docker_build=true)"
  type        = string
  default     = ""
}

variable "app_port" {
  type    = number
  default = 8501
}

variable "sse_origin_read_timeout_seconds" {
  type    = number
  default = 60 # CloudFront OriginReadTimeout (account max typically 60–120s)
}

variable "alb_idle_timeout_seconds" {
  type    = number
  default = 600
}

variable "custom_header_name" {
  type    = string
  default = "X-Custom-Header"
}

variable "s3_files_session_prefix" {
  type    = string
  default = "agentcore-sessions/"
}

variable "session_storage_mount_path" {
  type    = string
  default = "/mnt/workspace"
}

variable "app_data_mount_path" {
  type    = string
  default = "/mnt/app-data"
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}
