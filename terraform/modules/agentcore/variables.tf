variable "project_name" {
  type = string
}

variable "agent_runtime_name" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "agent_runtime_security_group_id" {
  type = string
}

variable "s3_files_file_system_arn" {
  type = string
}

variable "s3_files_access_point_arn" {
  type = string
}

variable "s3_bucket_arn" {
  type = string
}

variable "session_storage_mount_path" {
  type = string
}

variable "knowledge_base_id" {
  type = string
}

variable "skip_docker_build" {
  type = bool
}

variable "runtime_image_uri" {
  type = string
}

variable "repo_root" {
  type = string
}

variable "region" {
  type = string
}
