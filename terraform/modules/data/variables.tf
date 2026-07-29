variable "project_name" {
  type = string
}

variable "vector_index_name" {
  type = string
}

variable "embedding_model_arn" {
  type = string
}

variable "embedding_dimensions" {
  type    = number
  default = 1024
}

variable "embedding_data_type" {
  type    = string
  default = "float32"
}

variable "distance_metric" {
  type    = string
  default = "cosine"
}

variable "non_filterable_metadata_keys" {
  type = list(string)
  default = [
    "AMAZON_BEDROCK_TEXT",
    "AMAZON_BEDROCK_METADATA",
  ]
}
