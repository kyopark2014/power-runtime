locals {
  agent_runtime_name = replace(var.project_name, "-", "_")
  vector_index_name  = var.project_name
  embedding_model_arn = (
    "arn:aws:bedrock:${var.region}::foundation-model/amazon.titan-embed-text-v2:0"
  )
  alb_origin_header_secret_name      = "${var.project_name}/cloudfront-alb-origin-header"
  session_signing_key_secret_name    = "${var.project_name}/session-signing-key"
  cloudfront_signing_key_secret_name = "${var.project_name}/cloudfront-signing-key"
  repo_root                          = abspath("${path.module}/..")
}
