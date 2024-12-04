locals {
  service_account_email = "terraform@test-441303.iam.gserviceaccount.com"
}

# Cloud Functions https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloudfunctions_function
### GCFソースコードをzip化 https://registry.terraform.io/providers/hashicorp/archive/2.1.0/docs/data-sources/archive_file
data "archive_file" "src_gcf-scraping-race_plan" {
  type        = "zip"
  source_dir  = "./modules/get-race_plan/src_gcf-scraping-race_plan"
  output_path = "./modules/tmp/src_gcf-scraping-race_plan.zip"
  excludes    = []
}
### GCFソースコードUpload https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/storage_bucket_object
resource "google_storage_bucket_object" "src_gcf-scraping-race_plan" {
  name   = "src_gcf-scraping-race_plan"
  source = data.archive_file.src_gcf-scraping-race_plan.output_path
  bucket = var.gcf_source_bucket
}
### Cloud Pub/Sub
resource "google_pubsub_topic" "race_plan" {
  name    = "race_plan-prod"
  project = var.project_id
}
### Function Config
resource "google_cloudfunctions_function" "functions-scraping-race_plan" {
  name        = "scraping-race_plan-prod"
  description = "週末レース情報取得"
  runtime     = "python312"
  project     = var.project_id
  region      = var.region

  available_memory_mb   = 2048
  source_archive_bucket = var.gcf_source_bucket
  source_archive_object = google_storage_bucket_object.src_gcf-scraping-race_plan.name
  event_trigger {
    event_type = "providers/cloud.pubsub/eventTypes/topic.publish"
    resource   = google_pubsub_topic.race_plan.name
    failure_policy {
      retry = false
    }
  }
  timeout               = 540
  entry_point           = "main"
  service_account_email = local.service_account_email
  docker_registry       = "ARTIFACT_REGISTRY"
  max_instances         = 1
  environment_variables = {
    PROJECT_ID       = var.project_id
    LOCATION_ID      = var.region
    PUBSUB_TARGET    = "race_prediction-prod"
    MODEL_RUN_OFFSET = "10"
  }
}

### Cloud Scheduler
resource "google_cloud_scheduler_job" "invoke-functions-scraping-race_plan" {
  name        = "invoker-gcf-scraping-race_plan-prod"
  description = "Function「scraping-race_plan」を週次実行（土曜00:00 at JST）"
  schedule    = "0 0 * * SAT"
  time_zone   = "Asia/Tokyo"
  project     = var.project_id
  region      = var.region
  pubsub_target {
    topic_name = google_pubsub_topic.race_plan.id
    data       = base64encode(" ")
  }
  retry_config {
    retry_count = 0
  }
}

# ログベースのアラート通知設定
resource "google_monitoring_alert_policy" "alert_policy-race_plan" {
  project      = var.project_id
  display_name = "'race_plan'取得エラー"
  documentation {
    content = "週末競馬レース情報のスクレイピングエラー"
  }
  combiner = "OR"
  conditions {
    display_name = "Log match condition"
    condition_matched_log {
      filter = <<EOF
resource.type="cloud_function"
resource.labels.function_name="${google_cloudfunctions_function.functions-scraping-race_plan.name}"
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
