import dataclasses
import json
import os
import subprocess
import traceback

import lightgbm as lgb
import numpy as np
import pandas as pd
import requests
# from dotenv import load_dotenv
from google.cloud import bigquery
from google.cloud import scheduler_v1 as schdlr
from google.cloud import secretmanager
from google.cloud import storage as gcs
from sklearn.preprocessing import OrdinalEncoder
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# load_dotenv()
PROJECT_ID = os.environ.get('PROJECT_ID')
MODEL_BUCKET = os.environ.get('MODEL_BUCKET')
CSV_BUCKET = os.environ.get('CSV_BUCKET')
MODEL_NAME_PREFIX = os.environ.get('MODEL_NAME_PREFIX')
DOWNLOAD_FOLDER = os.environ.get('DOWNLOAD_FOLDER')
# SECRET_ID_LINE = os.environ.get('SECRET_ID_LINE')
SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN')
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")
BQ_DATASET = os.environ.get('BQ_DATASET')

@dataclasses.dataclass(frozen=True)
class UrlPaths:
    # 出馬表ページ
    RACE_CARD_URL: str = 'https://race.netkeiba.com/race/shutuba.html'

def get_race_card(race_id, race_date):

    command = [
        'python',
        'scraper.py',
        race_id,
        race_date,
        UrlPaths.RACE_CARD_URL,
        DOWNLOAD_FOLDER,
    ]

    # ウェブスクレイピング実行
    try:
        result = subprocess.run(command, capture_output=True, text=True)
        print(result.stdout)
        print(result.stderr)
    except Exception as e:
        print(e)
        return

    # スクレイピング結果取得
    race_card = pd.read_csv(f'{DOWNLOAD_FOLDER}/race_card.csv')

    return race_card


# データ前処理関数の定義
def preprocess_race_results(df):

    print(df["odds"])
    # df["odds"] = df["odds"].replace("---", np.nan).astype(float)
    df['odds'] = pd.to_numeric(df['odds'], errors='coerce')
    df_sex = df['sex_age'].str.extract(r'([牝牡セ])(\d+)', expand=True)
    df['sex'] = df_sex[0]
    df['age'] = df_sex[1].astype(int)
    df = df.drop(['sex_age'], axis=1)
    df_weight = df['horse_weight'].str.extract(r'(\d{3}).([+-0]\d*)', expand=True)
    df['馬体重'] = df_weight[0].fillna(0).astype(int)
    df['体重増減'] = df_weight[1].str.replace(r'\+', '', regex=True).fillna(0).astype(int)
    df = df.drop(['horse_weight'], axis=1)
    df = df.drop(['jockey'], axis=1)
    df[['year', 'month', 'day']] = df['event_date'].str.split('-', expand=True).astype(int)
    df_trainner = df['trainer'].str.extract(r'\[(.)\] (.+)', expand=True)
    df['trainer_region'] = df_trainner[0]
    df['trainer_name'] = df_trainner[1]
    df = df.drop(['trainer', 'event_date'], axis=1)

    return df

def get_model_lgb():
    gcs_client = gcs.Client()
    blobs = gcs_client.list_blobs(MODEL_BUCKET, prefix=MODEL_NAME_PREFIX)
    blob_list = list(blobs)

    if len(blob_list) == 1:
        blob = blob_list[0]
        print(f'Model file: {blob.name}')

        # モデルImport
        model_lgb_path = f'../tmp/{blob.name}'
        blob.download_to_filename(model_lgb_path)
        model_lgb = lgb.Booster(model_file=model_lgb_path)
    else:
        # エラー処理: ファイル数が1つではない場合
        if len(blob_list) == 0:
            print("Error: No blobs found with the specified prefix.")
        else:
            print("Error: Multiple blobs found with the specified prefix. Expecting only one.")
        return

    return model_lgb

# def gcs_uploader(filename):
#     src_file_path = os.path.join(DOWNLOAD_FOLDER, filename)
#     try:
#         gcs_client = gcs.Client()
#         bucket = gcs_client.bucket(CSV_BUCKET)
#         blob = bucket.blob(filename)
#         blob.upload_from_filename(src_file_path, content_type='text/csv')
#         print(f"'File name: {filename}' was successfully uploaded to Cloud Storage.")
#     except Exception as e:
#         print(f"'File name: {filename}' failed to upload to Cloud Storage.: {e}")
#         print(traceback.format_exc())
#     return

def bq_uploader(df, race_info):

    try:
        # upload仕様
        table_id = f"{PROJECT_ID}.{BQ_DATASET}.raw_race_prediction"
        bq_client = bigquery.Client()
        job_config = bigquery.LoadJobConfig()
        job_config.write_disposition = 'WRITE_APPEND'
        job_config.schema = bq_client.get_table(table_id).schema

        # データ登録実行
        load_job = bq_client.load_table_from_dataframe(df, table_id, job_config=job_config)
        load_job.result()
        print(f"Race prediction ({race_info}) was successfully uploaded to BigQuery. (job_id: '{load_job.job_id}')")
    except Exception as e:
        print(f"Race prediction ({race_info}) failed to upload to BigQuery.: {e}")
    return

# def get_secret(SECRET_ID_LINE):
#     client = secretmanager.SecretManagerServiceClient()
#     secret_name = f'projects/{PROJECT_ID}/secrets/{SECRET_ID_LINE}/versions/latest'
#     response = client.access_secret_version(request={"name": secret_name})
#     payload = response.payload.data.decode("UTF-8")
#     return payload

# def send_line(race_location, race_name, race_card_prep):

#     message_lines_with_number = [
#         f"競馬場：{race_location}",
#         f"レース名：{race_name}",
#         "",
#         "馬番, 馬名, 3着内率, 購入フラグ"
#     ]
#     # 競走馬ごとに3着内率と購入フラグを作成
#     for _, row in race_card_prep.iterrows():
#         line = f"{row['horse_number']}, {row['horse_name']}, {str(round(row['y_pred_loaded'] * 100, 2)) + '%'}, \t{row['pred_labels']}"
#         message_lines_with_number.append(line)
#     line_notification_message = "\n".join(message_lines_with_number)

#     # LINEトークン取得
#     line_notify_token = get_secret(SECRET_ID_LINE)

#     # header
#     headers = {
#         'Content-Type': 'application/json',
#         'Authorization': f'Bearer ' + line_notify_token
#     }

#     # message
#     message = {
#         'messages':[
#             {
#                 'type': 'text',
#                 'text': message
#             }
#         ]
#     }

#     # LINEへメッセージ通知
#     try:
#         response = requests.post('https://api.line.me/v2/bot/message/broadcast', headers=headers, data=json.dumps(message))

#         # ステータスコード処理: https://developers.line.biz/ja/reference/line-login/#status-codes
#         if response.status_code == 200:
#             print(f'A message was successfully sent to Line.')
#         else:
#             error_message = response.json()['message']
#             print(f'Failed to send a message to Line. Status code: {response.status_code}, Error: {error_message}')
#     except Exception as e:
#         print(e)
#         print(traceback.format_exc())
#     return


def send_slack(race_id, race_location='Unknown', race_name='Unknown', race_card_prep=None):

    client = WebClient(token=SLACK_BOT_TOKEN)

    # 予測内容をテキスト化
    pred_content_list = []
    print(race_card_prep)
    if race_card_prep is not None:
        for _, row in race_card_prep.iterrows():
            line = f"| {row['horse_number']} | {row['horse_name']} | {str(round(row['y_pred_loaded'] * 100, 2)) + '%'} | {row['pred_labels']} |"
            pred_content_list.append(line)
    else:
        line = 'Webスクレイピングエラー'
        pred_content_list.append(line)
    pred_content = '\n'.join(pred_content_list)

    # メッセージ本文: https://api.slack.com/reference/surfaces/formatting#basic-formatting
    text = f"""
*{race_location}競馬場: <https://race.netkeiba.com/race/shutuba.html?race_id={race_id}|{race_name}>*
```
| 馬番 | 馬名 | 3着内率 | 購入フラグ |
| :---: | :---: | :---: | :---: |
{pred_content}
```
"""

    try:
        # https://api.slack.com/methods/chat.postMessage
        response = client.chat_postMessage(channel=SLACK_CHANNEL_ID, text=text)
        print("A message was successfully sent to Slack")
    except SlackApiError as e:
        print(f"Error sending message: {e}")
        print(response)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")  # 予期しないエラーをキャッチ
        print(traceback.format_exc())  # スタックトレースを出力
    return


def delete_schdlr_job(scheduler_job_id):
    # Create a client
    schdlr_client = schdlr.CloudSchedulerClient()

    # Make the request
    request = schdlr.DeleteJobRequest(name=scheduler_job_id)
    try:
        schdlr_client.delete_job(request=request)
        print(f'A scheduled job was sucessfully deleted. (JobID: {scheduler_job_id})')
    except Exception as e:
        print(f'deletion scheduled job was failed.  (JobID: {scheduler_job_id})')
        print(e)
        print(traceback.format_exc())
    return


# エントリポイント
def main(event, context):

    scheduler_job_id = event['attributes']['scheduler_job_id']
    race_id = event['attributes']['race_id']
    race_date = event['attributes']['race_date']
    print(f'race_id: {race_id}')

    try:
        # 出走表を取得
        race_card = get_race_card(race_id, race_date)

        # データ前処理
        race_card_prep = preprocess_race_results(race_card)

        # 特徴量のみ取得
        race_card_feature = race_card_prep.drop(['race_id', 'race_title', 'location', 'race_turn', 'year', 'month', 'day', 'horse_name'], axis=1)

        # カテゴリカル変数のエンコーディング
        categorical_columns = race_card_feature.select_dtypes(include='object').columns
        race_card_feature[categorical_columns] = race_card_feature[categorical_columns].astype(str)
        ordinal_encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
        race_card_feature[categorical_columns] = ordinal_encoder.fit_transform(race_card_feature[categorical_columns])

        # 予測モデル実行
        model_lgb = get_model_lgb()
        y_pred_loaded = model_lgb.predict(race_card_feature, num_iteration=model_lgb.best_iteration)
        # 予測結果を二値クラスに変換
        pred_labels = (y_pred_loaded >= np.sort(y_pred_loaded)[-3]).astype(int)
        race_card_prep['y_pred_loaded'] = y_pred_loaded
        race_card_prep['pred_labels'] = pred_labels

        # 予測結果の保存
        race_info = f'{race_date.replace('-', '')}-{race_id}'
        race_card_prep = race_card_prep.rename(columns={'馬体重': 'horse_weight', '体重増減': 'weight_gain_loss'})
        bq_uploader(race_card_prep, race_info)

        # レース場とレース名を抽出
        unique_race_info = race_card_prep[['location', 'race_title']].drop_duplicates().iloc[0]
        race_location = unique_race_info['location']
        race_name = unique_race_info['race_title']

        # 予測結果通知
        # ## LINE ver.
        # send_line(race_location, race_name, race_card_prep)
        ## Slack ver.
        send_slack(race_id, race_location, race_name, race_card_prep)

    except Exception as e:
        print(e)
        print(traceback.format_exc())
        send_slack(race_id)
    finally:
        # GCF関数の起動元Scheduler Jobを削除
        delete_schdlr_job(scheduler_job_id)
    return


# LOCATION_ID = 'us-west1'
# race_id = '202410030801'
# race_date = '2024-07-21'
# parent = f'projects/{PROJECT_ID}/locations/{LOCATION_ID}'
# scheduler_job_id = f'{parent}/jobs/invoker-gcf-scraping-race_prediction-{race_date}-{race_id}'
# # projects/focal-acronym-381707/locations/us-west1/topics/race_prediction_dev

# event = {
#     "attributes": {
#         'scheduler_job_id': scheduler_job_id,
#         'race_id': race_id,
#         'race_date': race_date
#     },
#     "data": ""
# }
# context = {}
# main(event, context)
