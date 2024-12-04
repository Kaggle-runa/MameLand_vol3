# data "google_storage_bucket" "gcf_source" {
#   name = "gcf_source-terraform-prod-${var.number}"
# }

# # ローカル環境変数
# locals {
#   sql_files_raw = toset(fileset(path.module, var.path_sql_raw))
#   sql_files_int = toset(fileset(path.module, var.path_sql_int))
# }
locals {
  service_account_email = "terraform@test-441303.iam.gserviceaccount.com"
}

# Cloud Storage
resource "google_storage_bucket" "race_results-landing" {
  force_destroy               = true
  location                    = var.region
  name                        = "scraping-race_results-landing-prod-${var.project_number}"
  project                     = var.project_id
  public_access_prevention    = "inherited"
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
}
resource "google_storage_bucket" "race_results-archive" {
  force_destroy               = true
  location                    = var.region
  name                        = "scraping-race_results-archive-prod-${var.project_number}"
  project                     = var.project_id
  public_access_prevention    = "inherited"
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
}

# BigQuery
resource "google_bigquery_dataset" "race_results_raw_prod" {
  dataset_id                 = "race_results_raw_prod"
  delete_contents_on_destroy = true
  description                = "競馬レース結果（生データ）"
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
resource "google_bigquery_table" "raw_horse_results" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.race_results_raw_prod.dataset_id
  table_id            = "raw_horse_results"
  schema              = file("${path.module}/bq_schema/raw_horse_results.json")
  description         = "馬ごとのレース結果詳細（データソース: netkeiba ネットケイバ）"
  deletion_protection = true
}
resource "google_bigquery_table" "raw_race_results" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.race_results_raw_prod.dataset_id
  table_id            = "raw_race_results"
  schema              = file("${path.module}/bq_schema/raw_race_results.json")
  description         = "レース結果（データソース: netkeiba ネットケイバ）"
  deletion_protection = true
}
resource "google_bigquery_table" "raw_race_return_all" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.race_results_raw_prod.dataset_id
  table_id            = "raw_race_return_all"
  schema              = file("${path.module}/bq_schema/raw_race_return_all.json")
  description         = "払戻金情報（データソース: netkeiba ネットケイバ）"
  deletion_protection = true
}
resource "google_bigquery_table" "raw_speed_results" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.race_results_raw_prod.dataset_id
  table_id            = "raw_speed_results"
  schema              = file("${path.module}/bq_schema/raw_speed_results.json")
  description         = "スピード指数（データソース: 個人Webサイト「競馬新聞&スピード指数」）"
  deletion_protection = true
}


# Cloud Functions https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloudfunctions_function
## scraping-race_results
### GCFソースコードをzip化 https://registry.terraform.io/providers/hashicorp/archive/2.1.0/docs/data-sources/archive_file
data "archive_file" "src_gcf-scraping-race_results" {
  type        = "zip"
  source_dir  = "./modules/get-race_results/src_gcf-scraping-race_results"
  output_path = "./modules/tmp/src_gcf-scraping-race_results.zip"
  excludes    = []
}
### GCFソースコードUpload https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/storage_bucket_object
resource "google_storage_bucket_object" "src_gcf-scraping-race_results" {
  name   = "src_gcf-scraping-race_results"
  source = data.archive_file.src_gcf-scraping-race_results.output_path
  bucket = var.gcf_source_bucket
}
### Function Config
resource "google_cloudfunctions2_function" "functions-scraping-race_results" {
  name        = "scraping-race_results-prod"
  description = "race_resultsのスクレイピング"
  project     = var.project_id
  location    = var.region
  build_config {
    runtime     = "python311"
    entry_point = "main"
    source {
      storage_source {
        bucket = var.gcf_source_bucket
        object = google_storage_bucket_object.src_gcf-scraping-race_results.name
      }
    }
  }

  service_config {
    max_instance_count               = 1
    min_instance_count               = 0
    available_memory                 = "2Gi"
    timeout_seconds                  = 3600
    max_instance_request_concurrency = 1
    environment_variables = {
      EMAIL            = var.netkeiba_login_id
      PASSWORD         = var.netkeiba_login_password
      PROJECT_ID       = var.project_id
      DST_BUCKET       = google_storage_bucket.race_results-landing.name
      DOWNLOAD_FOLDER  = "/tmp"
      LOG_EXECUTION_ID = "true"
    }
    service_account_email = local.service_account_email
  }
}
### Cloud Scheduler
resource "google_cloud_scheduler_job" "invoke-functions-scraping-race_results" {
  name             = "invoker-gcf-scraping-race_results-prod"
  description      = "Function「scraping-race_results」を週次実行（火曜00:00 at JST）"
  schedule         = "0 0 * * TUE"
  time_zone        = "Asia/Tokyo"
  project          = var.project_id
  region           = var.region
  attempt_deadline = "1800s"
  retry_config {
    retry_count = 0
  }
  http_target {
    uri         = google_cloudfunctions2_function.functions-scraping-race_results.service_config[0].uri
    http_method = "GET"
    headers = {
      "User-Agent" = "Google-Cloud-Scheduler"
    }
    oidc_token {
      audience              = "${google_cloudfunctions2_function.functions-scraping-race_results.service_config[0].uri}/"
      service_account_email = local.service_account_email
    }
  }
}


## bq_uploader-race_results
### GCFソースコードをzip化 https://registry.terraform.io/providers/hashicorp/archive/2.1.0/docs/data-sources/archive_file
data "archive_file" "src_gcf-bq_uploader" {
  type        = "zip"
  source_dir  = "./modules/get-race_results/src_gcf-bq_uploader"
  output_path = "./modules/tmp/src_gcf-bq_uploader.zip"
  excludes    = []
}
### GCFソースコードUpload https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/storage_bucket_object
resource "google_storage_bucket_object" "src_gcf-bq_uploader" {
  name   = "src_gcf-bq_uploader"
  source = data.archive_file.src_gcf-bq_uploader.output_path
  bucket = var.gcf_source_bucket
}
### Function Config
resource "google_cloudfunctions_function" "functions-bq_uploader" {
  name                  = "bq_uploader-race_results-prod"
  description           = "race_resultsに関するスクレイピング結果のBigQuery登録"
  runtime               = "python312"
  project               = var.project_id
  region                = var.region
  available_memory_mb   = 256
  source_archive_bucket = var.gcf_source_bucket
  source_archive_object = google_storage_bucket_object.src_gcf-bq_uploader.name
  event_trigger {
    event_type = "google.storage.object.finalize"
    resource   = google_storage_bucket.race_results-landing.name
    failure_policy {
      retry = false
    }
  }
  timeout               = 540
  entry_point           = "bq_uploader"
  service_account_email = local.service_account_email
  docker_registry       = "ARTIFACT_REGISTRY"
  max_instances         = 5
  environment_variables = {
    PROJECT_ID     = var.project_id
    DATASET_NAME   = google_bigquery_dataset.race_results_raw_prod.dataset_id
    ARCHIVE_BUCKET = google_storage_bucket.race_results-archive.name
  }
}


# ログベースのアラート通知設定
resource "google_monitoring_alert_policy" "alert_policy_gcs_to_bq" {
  project      = var.project_id
  display_name = "'race_results'データ転送エラー (Cloud Storage to BigQuery)"
  documentation {
    content = "Cloud Storage バケット「${google_storage_bucket.race_results-landing.name}」からBigQueryテーブルへのデータ転送ジョブエラー"
  }
  combiner = "OR"
  conditions {
    display_name = "Log match condition"
    condition_matched_log {
      filter = <<EOF
resource.type="cloud_function"
resource.labels.function_name="${google_cloudfunctions_function.functions-bq_uploader.name}"
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


# ログベースのアラート通知設定
resource "google_monitoring_alert_policy" "alert_policy-scraping-race_results" {
  project      = var.project_id
  display_name = "'race_results'スクレイピングエラー"
  documentation {
    content = "レース結果スクレイピングジョブエラー"
  }
  combiner = "OR"
  conditions {
    display_name = "Log match condition"
    condition_matched_log {
      filter = <<EOF
resource.type="cloud_function"
resource.labels.function_name="${google_cloudfunctions2_function.functions-scraping-race_results.name}"
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