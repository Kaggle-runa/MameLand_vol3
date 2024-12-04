# Project情報取得 https://registry.terraform.io/providers/hashicorp/google/latest/docs/data-sources/project
data "google_project" "project" {
  project_id = var.project_id
}

# locals {
#   service_account_email = sa_iam_config[0].sa_name
# }
# output "name" {
#   value = service_account_email
# }

# Cloud Storgeバケット作成 https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/storage_bucket
resource "google_storage_bucket" "tf_backend" {
  force_destroy               = true
  location                    = var.region
  name                        = "terraform-backends-prod-${data.google_project.project.number}"
  project                     = var.project_id
  public_access_prevention    = "inherited"
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
}

# # データパイプライン起動用サービスアカウント作成 https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/google_service_account
# resource "google_service_account" "service_account_bq-data-pipeline" {
#   project      = module.project_services.project_id
#   account_id   = "bq-data-pipeline"
#   display_name = "bq-data-pipeline"
#   description  = "データパイプライン用（GCS-BigQuery-BigQueryDTS）"
# }
# resource "google_service_account" "service_account_gcs-uploader" {
#   project      = module.project_services.project_id
#   account_id   = "gcs-uploader"
#   display_name = "gcs-uploader"
#   description  = "データパイプライン用（Local Machine - GCS）"
# }


## GCFソースコードUpload先バケット https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/storage_bucket
resource "google_storage_bucket" "gcf_source" {
  project                     = var.project_id
  location                    = var.region
  name                        = "gcf_source-terraform-prod-${data.google_project.project.number}"
  public_access_prevention    = "inherited"
  storage_class               = "STANDARD"
  force_destroy               = false
  uniform_bucket_level_access = true
}

# 通知チャンネル
resource "google_monitoring_notification_channel" "email_notification" {
  project      = var.project_id
  display_name = "Email Notification Channel"
  type         = "email"
  labels = {
    email_address = var.notification_email
  }
}

module "get-race_results" {
  source                  = "./modules/get-race_results"
  project_id              = var.project_id
  project_number          = data.google_project.project.number
  region                  = var.region
  netkeiba_login_id       = var.netkeiba_login_id
  netkeiba_login_password = var.netkeiba_login_password
  gcf_source_bucket       = google_storage_bucket.gcf_source.name
  notification_channel_id = google_monitoring_notification_channel.email_notification.id
}

module "get-race_plan" {
  source                  = "./modules/get-race_plan"
  project_id              = var.project_id
  project_number          = data.google_project.project.number
  region                  = var.region
  gcf_source_bucket       = google_storage_bucket.gcf_source.name
  notification_channel_id = google_monitoring_notification_channel.email_notification.id
}

module "get-race_prediction" {
  source                  = "./modules/get-race_prediction"
  project_id              = var.project_id
  project_number          = data.google_project.project.number
  region                  = var.region
  gcf_source_bucket       = google_storage_bucket.gcf_source.name
  notification_channel_id = google_monitoring_notification_channel.email_notification.id
}

