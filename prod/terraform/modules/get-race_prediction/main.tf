locals {
  service_account_email = "terraform@test-441303.iam.gserviceaccount.com"
}

# Cloud Storage
resource "google_storage_bucket" "model_registry-prod" {
  project                     = var.project_id
  location                    = var.region
  name                        = "model_registry-prod-${var.project_number}"
  public_access_prevention    = "inherited"
  storage_class               = "STANDARD"
  force_destroy               = false
  uniform_bucket_level_access = true
}

# BigQuery
resource "google_bigquery_dataset" "race_prediction_raw_prod" {
  dataset_id                 = "race_prediction_raw_prod"
  delete_contents_on_destroy = true
  description                = "競馬レース予測（生データ）"
  location                   = var.region
  max_time_travel_hours      = "168"
  project                    = var.project_id

  access {
    role          = "OWNER"
    special_group = "projectOwners"
  }
  access {
    role          = "READER"
    special_group = "projectReaders"
  }
  access {
    role          = "WRITER"
    special_group = "projectWriters"
  }
}
resource "google_bigquery_table" "raw_race_prediction" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.race_prediction_raw_prod.dataset_id
  table_id            = "raw_race_prediction"
  schema              = file("${path.module}/bq_schema/raw_race_prediction.json")
  description         = "ML予測結果"
  deletion_protection = true
  # labels              = {}
}

# Cloud Functions https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloudfunctions_function
### GCFソースコードをzip化 https://registry.terraform.io/providers/hashicorp/archive/2.1.0/docs/data-sources/archive_file
data "archive_file" "src_gcf-race_prediction" {
  type        = "zip"
  source_dir  = "./modules/get-race_prediction/src_gcf-race_prediction"
  output_path = "./modules/tmp/src_gcf-race_prediction.zip"
  excludes    = []
}
### GCFソースコードUpload https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/storage_bucket_object
resource "google_storage_bucket_object" "src_gcf-race_prediction" {
  name   = "src_gcf-race_prediction"
  source = data.archive_file.src_gcf-race_prediction.output_path
  bucket = var.gcf_source_bucket
}
### Cloud Pub/Sub
resource "google_pubsub_topic" "race_prediction" {
  name    = "race_prediction-prod"
  project = var.project_id
}
### Function Config
resource "google_cloudfunctions_function" "functions-race_prediction" {
  name        = "race_prediction-prod"
  description = "出走n分前のMLモデルによるレース予測実行"
  runtime     = "python312"
  project     = var.project_id
  region      = var.region

  available_memory_mb   = 2048
  source_archive_bucket = var.gcf_source_bucket
  source_archive_object = google_storage_bucket_object.src_gcf-race_prediction.name
  event_trigger {
    event_type = "providers/cloud.pubsub/eventTypes/topic.publish"
    resource   = google_pubsub_topic.race_prediction.name
    failure_policy {
      retry = false
    }
  }
  timeout               = 540
  entry_point           = "main"
  service_account_email = local.service_account_email
  docker_registry       = "ARTIFACT_REGISTRY"
  max_instances         = 3
  environment_variables = {
    PROJECT_ID        = var.project_id
    MODEL_BUCKET      = google_storage_bucket.model_registry-prod.name
    MODEL_NAME_PREFIX = "lgb_model_"
    DOWNLOAD_FOLDER   = "/tmp"
    BQ_DATASET        = google_bigquery_dataset.race_prediction_raw_prod.dataset_id
    SLACK_CHANNEL_ID  = "C07J5JY17U6"
  }
  secret_environment_variables {
    key        = "SLACK_BOT_TOKEN"
    project_id = var.project_id
    secret     = "SLACK_BOT_TOKEN"
    version    = "latest"
  }
}

# ログベースのアラート通知設定
resource "google_monitoring_alert_policy" "alert_policy-race_prediction" {
  project      = var.project_id
  display_name = "'race_prediction'実行エラー"
  documentation {
    content = "レース予測サービス実行エラー"
  }
  combiner = "OR"
  conditions {
    display_name = "Log match condition"
    condition_matched_log {
      filter = <<EOF
resource.type="cloud_function"
resource.labels.function_name="${google_cloudfunctions_function.functions-race_prediction.name}"
severity>=ERROR
EOF
    }
  }
  notification_channels = [var.notification_channel_id]
  alert_strategy {
    auto_close = "604800s"
    notification_rate_limit {
      period = "300s"
    }
  }
  enabled = true
}
