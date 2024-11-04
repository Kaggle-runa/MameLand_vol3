import ast
import dataclasses
import datetime
import logging
import os
import re
import ssl
import subprocess
import time
import urllib.request
from urllib.request import urlopen

import certifi
import pandas as pd
import pytz
from bs4 import BeautifulSoup
from google.cloud import scheduler_v1 as schdlr
from tqdm import tqdm

# from dotenv import load_dotenv

# ロギングの設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# load_dotenv()
PROJECT_ID = os.environ.get("PROJECT_ID")
LOCATION_ID = os.environ.get("LOCATION_ID")
PUBSUB_TARGET = os.environ.get("PUBSUB_TARGET")
MODEL_RUN_OFFSET = int(os.environ.get("MODEL_RUN_OFFSET"))

# Create a client
try:
    schdlr_client = schdlr.CloudSchedulerClient()
except Exception as e:
    logger.error(f"Failed to initialize CloudSchedulerClient: {e}")
    raise


@dataclasses.dataclass(frozen=True)
class UrlPaths:
    TOP_URL: str = "https://race.netkeiba.com/top/"
    # 開催日程ページ
    CALENDAR_URL: str = TOP_URL + "calendar.html"
    # レース一覧ページ
    RACE_LIST_URL: str = TOP_URL + "race_list.html"


# 関数を定義して文字列をリストに変換
def ensure_list(input_data):
    try:
        if isinstance(input_data, str):
            return ast.literal_eval(input_data)
        elif isinstance(input_data, list):
            return input_data
        else:
            raise TypeError("入力データは文字列またはリストである必要があります。")
    except (ValueError, SyntaxError) as e:
        logger.error(f"Failed to convert input to list: {e}")
        raise ValueError("入力された文字列がリスト形式ではありません。")


def get_kaisai_date(from_: str, to_: str):
    """
    yyyy-mm-ddの形式でfrom_とto_を指定すると、間の開催日程一覧が返ってくる関数。
    """
    try:
        # 日付範囲を生成
        date_range = pd.date_range(start=from_, end=to_, freq="D")
        kaisai_date_list = []
        seen_year_month = set()

        for date in tqdm(date_range, total=len(date_range)):
            year_month = (date.year, date.month)
            if year_month not in seen_year_month:
                seen_year_month.add(year_month)
                query = [
                    "year=" + str(date.year),
                    "month=" + str(date.month),
                ]
                url = UrlPaths.CALENDAR_URL + "?" + "&".join(query)
                ctx = ssl.create_default_context(cafile=certifi.where())
                try:
                    with urllib.request.urlopen(url, context=ctx) as response:
                        html = response.read()
                    time.sleep(1)
                    soup = BeautifulSoup(html, "html.parser")
                    a_list = soup.find("table", class_="Calendar_Table").find_all("a")
                    for a in a_list:
                        kaisai_date = re.findall(r"(?<=kaisai_date=)\d+", a["href"])[0]
                        kaisai_date_list.append(kaisai_date)
                except urllib.error.URLError as e:
                    logger.error(f"Failed to fetch URL {url}: {e}")
                except AttributeError as e:
                    logger.error(f"Failed to parse HTML from {url}: {e}")

        # 取得した開催日をフィルタリングして指定範囲に含まれる日付のみを返す
        from_date = from_.replace("-", "")
        to_date = to_.replace("-", "")
        kaisai_date_list = [d for d in kaisai_date_list if from_date <= d <= to_date]

        return kaisai_date_list
    except Exception as e:
        logger.error(f"Unexpected error in get_kaisai_date: {e}")
        raise


def get_race_id_list(kaisai_date_list):
    try:
        # ウェブスクレイピング実行
        command = [
            "python",
            "scraper.py",
            str(kaisai_date_list),
            UrlPaths.RACE_LIST_URL,
        ]
        result = subprocess.run(command, capture_output=True, text=True)

        # スクレイピング結果からrace_id_listを抽出
        lines = result.stdout.splitlines()
        logger.info("\n".join(lines[:-1]))
        logger.error(result.stderr)

        race_info_list = ensure_list(lines[-1])
        logger.info(f"Total number of race_ids: {len(race_info_list)}")
        logger.info(f"race_id_list: {race_info_list}")

        return race_info_list

    except subprocess.CalledProcessError as e:
        logger.error(f"Subprocess failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_race_id_list: {e}")
        raise


def create_schdlr_job(race_id, race_date, race_time):
    try:
        # 出走時刻n分前をcron形式で取得
        race_datetime_obj = datetime.datetime.strptime(race_date, "%Y%m%d")
        race_time_obj = datetime.datetime.strptime(race_time, "%H:%M").time()
        race_datetime = race_datetime_obj.replace(
            hour=race_time_obj.hour, minute=race_time_obj.minute
        )
        target_datetime = race_datetime - datetime.timedelta(minutes=MODEL_RUN_OFFSET)
        cron_string = f"{target_datetime.minute} {target_datetime.hour} {target_datetime.day} {target_datetime.month} *"

        # Initialize request argument(s)
        parent = f"projects/{PROJECT_ID}/locations/{LOCATION_ID}"
        scheduler_job_id = (
            f"{parent}/jobs/invoker-gcf-scraping-race_prediction-{race_date}-{race_id}"
        )
        job = schdlr.Job(
            name=scheduler_job_id,
            description=f"競馬予測モデル実行（レース日時: {race_datetime}）",
            pubsub_target=schdlr.types.PubsubTarget(
                topic_name=f"projects/{PROJECT_ID}/topics/{PUBSUB_TARGET}",
                attributes={
                    "scheduler_job_id": scheduler_job_id,
                    "race_id": race_id,
                    "race_date": race_datetime.strftime("%Y-%m-%d"),
                },
            ),
            schedule=cron_string,
            time_zone="Asia/Tokyo",
            attempt_deadline="1800s",
        )
        request = schdlr.CreateJobRequest(
            parent=parent,
            job=job,
        )

        response = schdlr_client.create_job(request=request)
        logger.info(
            f"A scheduled job was successfully created. (JobID: {scheduler_job_id})"
        )
    except Exception as e:
        logger.error(
            f"Creation of scheduled job failed. (race_id: {race_id}, race_time: {race_datetime})"
        )
        logger.error(f"Error: {e}")


# Entry point
def main(event, context):
    try:
        logger.info("Function execution started.")

        # データ取得対象日付Range設定; 今日〜6日後
        tokyo_tz = pytz.timezone("Asia/Tokyo")
        today = datetime.datetime.now(tokyo_tz).date()
        six_days_later = today + datetime.timedelta(days=6)
        today_str = today.strftime("%Y-%m-%d")
        six_days_later_str = six_days_later.strftime("%Y-%m-%d")

        # スクレイピング: レース開催日 及び レースID取得
        logger.info(f"Coverage period is from {today} to {six_days_later}.")
        kaisai_date_list = get_kaisai_date(today_str, six_days_later_str)
        race_info_list = get_race_id_list(kaisai_date_list)

        # race_idごとにLGBM予測実行用のCloud Schedulerジョブ登録
        for race_info in race_info_list:
            race_id = race_info["race_id"]
            race_date = race_info["race_date"]
            race_time = race_info["race_time"]
            create_schdlr_job(race_id, race_date, race_time)

        logger.info("Function execution finished.")
    except Exception as e:
        logger.error(f"An unexpected error occurred in main function: {e}")
        raise


# event = {
#   "attributes": {},
#   "data": ""
# }
# context = {}
# main(event, context)
