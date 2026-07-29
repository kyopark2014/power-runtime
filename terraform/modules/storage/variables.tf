variable "project_name" {
  type = string
}

variable "s3_bucket_arn" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "s3files_mount_security_group_id" {
  type = string
}

variable "s3_files_session_prefix" {
  type = string
}

variable "agent_runtime_security_group_id" {
  type = string
}
