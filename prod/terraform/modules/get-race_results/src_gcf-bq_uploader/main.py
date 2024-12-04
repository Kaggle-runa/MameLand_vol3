import os
import traceback

from google.cloud import bigquery
from google.cloud import storage as gcs

# from dotenv import load_dotenv

# 定数定義
# load_dotenv()
PROJECT_ID = os.environ.get("PROJECT_ID")
DATASET_NAME = os.environ.get("DATASET_NAME")
ARCHIVE_BUCKET = os.environ.get("ARCHIVE_BUCKET")
SUPPORTED_CONTENT_TYPE = "text/csv"
FILE_TABLE_MAPPING = {
    "horse_results": {
        "table_name": "raw_horse_results",
        "write_disposition": "WRITE_APPEND",
    },
    "race_results": {
        "table_name": "raw_race_results",
        "write_disposition": "WRITE_APPEND",
    },
    "race_return_all": {
        "table_name": "raw_race_return_all",
        "write_disposition": "WRITE_APPEND",
    },
    "speed_results": {
        "table_name": "raw_speed_results",
        "write_disposition": "WRITE_APPEND",
    },
}


# BigQuery Client, GCS Clientの初期化
bq_client = bigquery.Client()
gcs_client = gcs.Client()


def _get_dst_table_info(filename):

    for key, value in FILE_TABLE_MAPPING.items():
        if filename.startswith(key):
            return value["table_name"], value["write_disposition"]
    return None, None


def _upload_to_bigquery(uri, filename, table_name, write_disposition):

    try:
        # BigQueryロードジョブ設定
        table_id = f"{PROJECT_ID}.{DATASET_NAME}.{table_name}"
        schema = bq_client.get_table(
            table_id
        ).schema  # ref: https://cloud.google.com/python/docs/reference/bigquery/latest/google.cloud.bigquery.client.Client#google_cloud_bigquery_client_Client_get_table
        job_config = bigquery.LoadJobConfig(
            # Properties: https://cloud.google.com/python/docs/reference/bigquery/latest/google.cloud.bigquery.job.LoadJobConfig
            source_format=bigquery.SourceFormat.CSV,
            skip_leading_rows=1,
            max_bad_records=0,
            write_disposition=write_disposition,
            schema=schema,
        )

        # BigQueryへのデータアップロード実行
        load_job = bq_client.load_table_from_uri(
            uri, table_id, job_config=job_config
        )  # ref: https://cloud.google.com/python/docs/reference/bigquery/latest/google.cloud.bigquery.client.Client#google_cloud_bigquery_client_Client_load_table_from_uri
        load_job.result()
        print(
            f"File name: '{filename}' was successfully uploaded to BigQuery. (job_id: '{load_job.job_id}')"
        )
        return True
    except Exception as e:
        print(
            f"Exception raised during data upload to BigQuery. (File name: '{filename}'): {e}"
        )
        print(traceback.format_exc())
        return False


def _archive_src_obeject(filename, src_bucket_name):

    src_bucket = gcs_client.bucket(src_bucket_name)
    dst_bucket = gcs_client.bucket(ARCHIVE_BUCKET)

    # ソースファイルを別バケットへアーカイブ, ソースバケットから削除
    src_blob = src_bucket.blob(filename)
    src_bucket.copy_blob(src_blob, dst_bucket, filename)
    src_blob.delete()
    print(
        f"File name: '{filename}' was successfully moved from 'gs://{src_bucket_name}' to 'gs://{ARCHIVE_BUCKET}'."
    )


# Entry Point
def bq_uploader(event, context):

    # 変数定義
    src_bucket_name = event["bucket"]
    filename = event["name"]
    content_type = event["contentType"]
    uri = f"gs://{src_bucket_name}/{filename}"
    print(f"Source URI: '{uri}'")

    # ファイル形式判定
    if content_type != SUPPORTED_CONTENT_TYPE:
        print(f"'{content_type}' is not supported file type. (File name: '{filename}')")
        return

    # BigQueryテーブル情報取得
    table_name, write_disposition = _get_dst_table_info(filename)
    if not table_name:
        print(f"Undefined file name: '{filename}'")
        return

    # BigQuery宛先テーブルデータアップロード
    upload_success = _upload_to_bigquery(uri, filename, table_name, write_disposition)

    # Cloud Storge ソースファイルのアーカイブと削除
    if upload_success:
        _archive_src_obeject(filename, src_bucket_name)


# data = {
#   "name": "race_result.csv",
#   "bucket": "213231389792_scraping_jra_landing",
#   "contentType": "text/csv",
#   "metageneration": "1",
#   "timeCreated": "2024-06-23T07:38:57.230Z",
# }
# context = {}
# bq_uploader(data, context)
