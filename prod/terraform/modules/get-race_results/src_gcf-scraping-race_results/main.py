import ast
import dataclasses
import datetime
import io
import json
import logging
import os
import re
import ssl
import subprocess
import time
import traceback
import urllib.request

import certifi
import functions_framework
import numpy as np
import pandas as pd
import pytz
import requests
from bs4 import BeautifulSoup

# from dotenv import load_dotenv
from google.cloud import storage as gcs
from tqdm import tqdm

# ロギングの設定
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 環境変数取得
# load_dotenv()
EMAIL = os.environ.get("EMAIL")
PASSWORD = os.environ.get("PASSWORD")
PROJECT_ID = os.environ.get("PROJECT_ID")
DST_BUCKET = os.environ.get("DST_BUCKET")
DOWNLOAD_FOLDER = os.environ.get("DOWNLOAD_FOLDER")


# 文字列をリストに変換
def ensure_list(input_data):
    try:
        if isinstance(input_data, str):
            # 文字列をリストに変換
            return ast.literal_eval(input_data)
        elif isinstance(input_data, list):
            # すでにリストの場合はそのまま返す
            return input_data
        else:
            raise TypeError("入力データは文字列またはリストである必要があります。")
    except (ValueError, SyntaxError) as e:
        logger.error(f"入力された文字列がリスト形式ではありません: {e}")
        raise ValueError("入力された文字列がリスト形式ではありません。")


@dataclasses.dataclass(frozen=True)
class UrlPaths:
    DB_DOMAIN: str = "https://db.netkeiba.com/"
    # レース結果テーブル、レース情報テーブル、払い戻しテーブルが含まれるページ
    RACE_URL: str = DB_DOMAIN + "race/"
    # 馬の過去成績テーブルが含まれるページ
    HORSE_URL: str = DB_DOMAIN + "horse/"

    TOP_URL: str = "https://race.netkeiba.com/top/"
    # 開催日程ページ
    CALENDAR_URL: str = TOP_URL + "calendar.html"
    # レース一覧ページ
    RACE_LIST_URL: str = TOP_URL + "race_list.html"

    # 出馬表ページ
    SHUTUBA_TABLE: str = "https://race.netkeiba.com/race/shutuba.html"


class Results:
    @staticmethod
    def scrape(race_id_list):
        """
        レース結果データをスクレイピングする関数
        Parameters:
        ----------
        race_id_list : list
            レースIDのリスト
        Returns:
        ----------
        race_results_df : pandas.DataFrame
            全レース結果データをまとめてDataFrame型にしたもの
        """
        # race_idをkeyにしてDataFrame型を格納
        race_results = {}
        for race_id in tqdm(race_id_list):
            time.sleep(1)
            logger.info(f"Retrieving race results... (race_id: {race_id})")
            try:
                url = "https://db.netkeiba.com/race/" + race_id
                html = requests.get(url)
                html.encoding = "EUC-JP"
                soup = BeautifulSoup(html.content, "html.parser")
                table = soup.find("table", class_="race_table_01")
                df = pd.read_html(io.StringIO(str(table)))[0]

                # 列名に半角スペースがあれば除去する
                df = df.rename(columns=lambda x: x.replace(" ", ""))
                # レース情報の取得
                df["race_title"] = [
                    soup.find(class_="racedata fc").find("h1").text
                ] * len(df)
                race_info = soup.find(class_="racedata fc").find("span").contents[0]
                df["race_type"] = [race_info[0]] * len(df)
                df["race_turn"] = [race_info[1]] * len(df)
                df["course_len"] = [re.findall(r"\d{4}", race_info)[0]] * len(df)
                df["weather"] = [
                    re.findall(r"天候\s*:\s*([^\/]+)", race_info.replace("\xa0", ""))[0]
                ] * len(df)
                df["ground_condition"] = [
                    re.findall(r"良|稍重|重|不良", race_info)[0]
                ] * len(df)
                df["year"] = [
                    re.findall(r"(\d{4})", soup.find(class_="smalltxt").contents[0])[0]
                ] * len(df)
                df["date"] = [
                    re.findall(
                        r"(\d{1,2}月\d{1,2}日)",
                        soup.find(class_="smalltxt").contents[0],
                    )[0]
                ] * len(df)
                df["location"] = [
                    re.findall(r"\d+回(..)", soup.find(class_="smalltxt").contents[0])[
                        0
                    ]
                ] * len(df)
                # 馬ID、騎手IDをスクレイピング
                horse_id_list = []
                horse_a_list = soup.find(
                    "table", attrs={"summary": "レース結果"}
                ).find_all("a", attrs={"href": re.compile("^/horse")})
                for a in horse_a_list:
                    horse_id = re.findall(r"\d+", a["href"])
                    horse_id_list.append(horse_id[0])
                jockey_id_list = []
                jockey_a_list = soup.find(
                    "table", attrs={"summary": "レース結果"}
                ).find_all("a", attrs={"href": re.compile("^/jockey")})
                for a in jockey_a_list:
                    jockey_id = re.findall(r"\d+", a["href"])
                    jockey_id_list.append(jockey_id[0])
                df["horse_id"] = horse_id_list
                df["jockey_id"] = jockey_id_list
                # インデックスをrace_idにする
                df["race_id"] = [race_id] * len(df)
                race_results[race_id] = df
            except IndexError:
                logger.warning(f"IndexError occurred for race_id: {race_id}")
                print(traceback.format_exc())
                continue
            except AttributeError:
                logger.warning(f"AttributeError occurred for race_id: {race_id}")
                print(traceback.format_exc())
                continue
            except Exception as e:
                logger.error(f"An error occurred while scraping race_id {race_id}: {e}")
                logger.debug(traceback.format_exc())
                break
        # pd.DataFrame型にして一つのデータにまとめる
        race_results_df = pd.concat([race_results[key] for key in race_results])
        return race_results_df


class RaceScraper:
    @staticmethod
    def login_and_get_session(mail, password):
        """
        ログインしてセッションを取得する関数

        Parameters:
        ----------
        mail : str
            ログイン用のメールアドレス
        password : str
            ログイン用のパスワード

        Returns:
        ----------
        session : requests.Session
            ログイン済みのセッション
        """
        try:
            session = requests.Session()
            login_data = {"login_id": mail, "pswd": password}
            login_url = "https://regist.netkeiba.com/account/?pid=login&action=auth"
            response = session.post(login_url, data=login_data)

            if response.url != login_url:
                logger.info("ログイン成功")
                return session
            else:
                logger.error("ログイン失敗")
                raise Exception("ログインに失敗しました")

        except requests.RequestException as e:
            logger.error(f"ログイン中にネットワークエラーが発生しました: {e}")
            raise
        except Exception as e:
            logger.error(f"ログイン中に予期しないエラーが発生しました: {e}")
            raise

    @staticmethod
    def scrape(horse_id_list, session):
        """
        馬の過去成績データをスクレイピングする関数

        Parameters:
        ----------
        horse_id_list : list
            馬IDのリスト
        session : requests.Session
            ログイン済みのセッション

        Returns:
        ----------
        horse_results_df : pandas.DataFrame
            全馬の過去成績データをまとめてDataFrame型にしたもの
        """

        horse_results = {}
        for horse_id in tqdm(horse_id_list):
            time.sleep(1)
            try:
                url = f"https://db.netkeiba.com/horse/{horse_id}"
                response = session.get(url)
                if response.status_code == 200:
                    df_list = pd.read_html(response.content, encoding="euc-jp")
                    df = df_list[3]
                    if df.columns[0] == "受賞歴":
                        df = df_list[4]
                    df["horse_id"] = [horse_id] * len(df)
                    horse_results[horse_id] = df
                else:
                    logger.warning(
                        f"Failed to retrieve data for horse_id: {horse_id}. Status code: {response.status_code}"
                    )
            except IndexError:
                logger.warning(f"IndexError occurred for horse_id: {horse_id}")
                continue
            except requests.RequestException as e:
                logger.error(f"Network error occurred for horse_id {horse_id}: {e}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error occurred for horse_id {horse_id}: {e}")
                continue

        if horse_results:
            horse_results_df = pd.concat([horse_results[key] for key in horse_results])
        else:
            logger.warning("No horse results were successfully scraped.")
            horse_results_df = pd.DataFrame()

        return horse_results_df


class Return:
    @staticmethod
    def scrape(race_id_list):
        """
        払い戻し表データをスクレイピングする関数

        Parameters:
        ----------
        race_id_list : list
            レースIDのリスト

        Returns:
        ----------
        return_tables_df : pandas.DataFrame
            全払い戻し表データをまとめてDataFrame型にしたもの
        """

        return_tables = {}
        for race_id in tqdm(race_id_list):
            time.sleep(1)
            try:
                url = "https://db.netkeiba.com/race/" + race_id
                html = requests.get(url)
                html.encoding = "EUC-JP"
                soup = BeautifulSoup(html.text.replace("<br />", "br"), "html.parser")

                dfs = [
                    pd.read_html(io.StringIO(str(table)))[0]
                    for table in soup.find_all("table", class_="pay_table_01")
                ]
                df = pd.concat(dfs, ignore_index=True)
                df["race_id"] = [race_id] * len(df)
                return_tables[race_id] = df
            except IndexError:
                logger.warning(f"IndexError occurred for race_id: {race_id}")
                print(traceback.format_exc())
                continue
            except AttributeError:
                logger.warning(f"AttributeError occurred for race_id: {race_id}")
                print(traceback.format_exc())
                continue
            except urllib.error.URLError as e:
                logger.error(f"Network error occurred for race_id {race_id}: {e}")
                print(traceback.format_exc())
                continue
            except Exception as e:
                logger.error(f"Unexpected error occurred for race_id {race_id}: {e}")
                print(traceback.format_exc())
                continue

        # pd.DataFrame型にして一つのデータにまとめる
        if return_tables:
            return_tables_df = pd.concat([return_tables[key] for key in return_tables])
        else:
            logger.warning("No return tables were successfully scraped.")
            return_tables_df = pd.DataFrame()

        return return_tables_df


class SpeedScraper:
    @staticmethod
    def get_index(original_race_id_list):
        """
        指定された複数のレースIDのレース結果データをスクレイピングしてDataFrameとして返すメソッド

        Parameters:
        ----------
        original_race_id_list : list
            レースIDのリスト

        Returns:
        ----------
        all_race_df : pandas.DataFrame
            すべてのレース結果データをまとめたDataFrame
        """
        # ID変換の対応を保持
        id_mapping = {int(str(id)[2:]): id for id in original_race_id_list}
        converted_race_id_list = list(id_mapping.keys())

        all_index_list = []

        for race_id in tqdm(converted_race_id_list):
            time.sleep(1)
            try:

                url = "https://jiro8.sakura.ne.jp/index2.php?code=" + str(race_id)
                url_html = requests.get(url)
                url_html.raise_for_status()
                html = BeautifulSoup(url_html.content, "html.parser")
                RaceTable01 = html.findAll("table", {"class": "c1"})[0]

                index_list = []
                for i, RaceTable01_tr in enumerate(RaceTable01.findAll("tr")):
                    if i >= 1 and len(RaceTable01_tr.findAll("td")) > 7:
                        uma_ban = int(RaceTable01_tr.findAll("td")[1].get_text())
                        zensou = RaceTable01_tr.findAll("td")[8]

                        speed_index = 0
                        rasing_index = 0
                        pace_index = 0
                        leading_index = 0

                        if len(zensou.findAll("span", {"class": "sn22"})) != 0:
                            speed_index = zensou.findAll("span", {"class": "sn22"})[
                                0
                            ].get_text()
                            speed_index = float(speed_index)

                            rasing_index = zensou.findAll("span", {"class": "sn22"})[
                                1
                            ].get_text()
                            rasing_index = float(rasing_index)

                            pace_index = zensou.findAll("span", {"class": "sn22"})[
                                2
                            ].get_text()
                            pace_index = float(pace_index)

                            leading_index = zensou.findAll("span", {"class": "sn22"})[
                                3
                            ].get_text()
                            leading_index = float(leading_index)

                        temp_list = [
                            id_mapping[race_id],
                            uma_ban,
                            speed_index,
                            rasing_index,
                            pace_index,
                            leading_index,
                        ]
                        index_list.append(temp_list)

                df_index = pd.DataFrame(
                    index_list,
                    columns=[
                        "race_id",
                        "uma_ban",
                        "speed_index",
                        "rasing_index",
                        "pace_index",
                        "leading_index",
                    ],
                )
                all_index_list.append(df_index)

            except requests.RequestException as e:
                logger.error(f"Network error occurred for race_id {race_id}: {e}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error occurred for race_id {race_id}: {e}")
                continue

        if all_index_list:
            all_race_df = pd.concat(all_index_list, ignore_index=True)
        else:
            logger.warning("No speed results were successfully scraped.")
            all_race_df = pd.DataFrame()

        return all_race_df


def get_kaisai_date(from_: str, to_: str):
    """
    yyyy-mm-ddの形式でfrom_とto_を指定すると、間の開催日程一覧が返ってくる関数。
    """
    # 日付範囲を生成
    logger.info(f"Fetching race dates from {from_} to {to_}")
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
            with urllib.request.urlopen(url, context=ctx) as response:
                html = response.read()
            time.sleep(1)
            soup = BeautifulSoup(html, "html.parser")
            a_list = soup.find("table", class_="Calendar_Table").find_all("a")
            for a in a_list:
                kaisai_date = re.findall(r"(?<=kaisai_date=)\d+", a["href"])[0]
                kaisai_date_list.append(kaisai_date)

    # 取得した開催日をフィルタリングして指定範囲に含まれる日付のみを返す
    from_date = from_.replace("-", "")
    to_date = to_.replace("-", "")
    kaisai_date_list = [d for d in kaisai_date_list if from_date <= d <= to_date]
    logger.info(f"Found {len(kaisai_date_list)} race dates")

    return kaisai_date_list


def get_race_id_list(kaisai_date_list):
    logger.info("Executing web scraping for race IDs")
    # ウェブスクレイピング実行
    command = [
        "python",
        "scraper.py",
        str(kaisai_date_list),
        UrlPaths.RACE_LIST_URL,
    ]
    result = subprocess.run(command, capture_output=True, text=True)

    # スクレイピング結果を出力
    print("stdout: ", result.stdout)
    print("stderr: ", result.stderr)

    # スクレイピングで書き出したrace_id_list.json を読み込む
    filepath = os.path.join(DOWNLOAD_FOLDER, "race_id_list.json")
    with open(filepath, "r") as f:
        race_id_list = json.load(f)

    logger.info(f"Total number of race_ids: {len(race_id_list)}")
    logger.debug(f"race_id_list: {race_id_list}")
    return race_id_list


def get_race_results(race_id_list, today_str):

    logger.info("Fetching race results")

    # レース結果を取得
    race_results = Results.scrape(race_id_list)

    # データ加工
    ## 日付列を結合して新しい列を作成し、不要な列を削除
    race_results["event_date"] = pd.to_datetime(
        race_results["year"].astype(str) + "年" + race_results["date"],
        format="%Y年%m月%d日",
    ).dt.strftime("%Y-%m-%d")
    race_results = race_results.drop(["year", "date"], axis=1)

    # 列名の修正と並び替えを同時に実行
    new_order = [
        "race_id",
        "event_date",
        "location",
        "race_title",
        "race_type",
        "race_turn",
        "course_len",
        "weather",
        "ground_condition",
        "finish_position",
        "frame_number",
        "horse_number",
        "horse_id",
        "horse_name",
        "sex_age",
        "carried_weight",
        "jockey_id",
        "jockey",
        "time",
        "difference",
        "odds",
        "popularity",
        "horse_weight",
        "trainer",
    ]
    race_results.columns = [
        "finish_position",
        "frame_number",
        "horse_number",
        "horse_name",
        "sex_age",
        "carried_weight",
        "jockey",
        "time",
        "difference",
        "odds",
        "popularity",
        "horse_weight",
        "trainer",
        "race_title",
        "race_type",
        "race_turn",
        "course_len",
        "weather",
        "ground_condition",
        "location",
        "horse_id",
        "jockey_id",
        "race_id",
        "event_date",
    ]
    # 列を並び替え
    race_results = race_results[new_order]

    ## odds に含まれる文字列処理
    race_results["odds"] = race_results["odds"].replace("---", np.nan).astype(float)

    # csv出力
    race_results.to_csv(f"{DOWNLOAD_FOLDER}/race_results_{today_str}.csv", index=None)
    logger.info(f"Race results saved to {DOWNLOAD_FOLDER}/race_results_{today_str}.csv")

    return race_results


def get_returns(race_id_list, today_str):
    try:

        # 払い戻し表データを取得
        returns = Return.scrape(race_id_list)

        # 列名を指定された名前に変更
        returns.columns = [
            "baken_types",
            "horse_number",
            "refund",
            "popularity",
            "race_id",
        ]

        # race_id列を最初の列に移動
        returns = returns[
            ["race_id", "baken_types", "horse_number", "refund", "popularity"]
        ]

        # csv出力
        returns.to_csv(
            f"{DOWNLOAD_FOLDER}/race_return_all_{today_str}.csv",
            index=None,
            encoding="utf-8",
        )
        logger.info(
            f"Returns data saved to {DOWNLOAD_FOLDER}/race_return_all_{today_str}.csv"
        )

        return
    except Exception as e:
        logger.error(f"Error occurred while processing returns data: {e}")
        raise


def get_horse_results(horse_id_list, today_str):
    try:
        # ログインしてセッションを取得
        session = RaceScraper.login_and_get_session(EMAIL, PASSWORD)

        # 過去成績データをスクレイピング
        horse_results = RaceScraper.scrape(horse_id_list, session)

        # 不要な列を削除
        horse_results = horse_results.drop(["映 像", "厩舎 ｺﾒﾝﾄ", "備考"], axis=1)

        # 列名の変更
        horse_results.columns = [
            "date",
            "venue",
            "weather",
            "race_number",
            "race_name",
            "num_horses",
            "frame_number",
            "horse_number",
            "odds",
            "popularity",
            "finish_position",
            "jockey",
            "carried_weight",
            "distance",
            "track_condition",
            "track_index",
            "time",
            "difference",
            "time_index",
            "passing_order",
            "pace",
            "last_3f",
            "horse_weight",
            "winner_or_2nd",
            "prize_money",
            "horse_id",
        ]

        # 日付の変換(yyyy-mm-dd)に
        horse_results["date"] = pd.to_datetime(horse_results["date"], format="%Y/%m/%d")
        # yyyy-mm-dd形式に変換
        horse_results["date"] = horse_results["date"].dt.strftime("%Y-%m-%d")

        # データ加工
        horse_results["race_number"] = horse_results["race_number"].astype("Int64")
        horse_results["frame_number"] = horse_results["frame_number"].astype("Int64")
        horse_results["popularity"] = horse_results["popularity"].astype("Int64")

        # csv出力
        horse_results.to_csv(
            f"{DOWNLOAD_FOLDER}/horse_results_{today_str}.csv",
            index=None,
            encoding="utf-8",
        )
        logger.info(
            f"Horse results saved to {DOWNLOAD_FOLDER}/horse_results_{today_str}.csv"
        )
        return

    except Exception as e:
        logger.error(f"Error occurred while processing horse results: {e}")
        raise


def get_speed_results(race_id_list, today_str):
    try:
        speed_results = SpeedScraper.get_index(race_id_list)

        # csv出力
        speed_results.to_csv(
            f"{DOWNLOAD_FOLDER}/speed_results_{today_str}.csv",
            index=None,
            encoding="utf-8",
        )
        logger.info(
            f"Speed results saved to {DOWNLOAD_FOLDER}/speed_results_{today_str}.csv"
        )
        return

    except Exception as e:
        logger.error(f"Error occurred while processing horse results: {e}")
        raise


def gcs_uploader(src_file):
    src_file_path = os.path.join(DOWNLOAD_FOLDER, src_file)
    try:
        gcs_client = gcs.Client()
        bucket = gcs_client.bucket(DST_BUCKET)
        blob = bucket.blob(src_file)
        blob.upload_from_filename(src_file_path, content_type="text/csv")
        logger.info(f"File '{src_file}' was successfully uploaded to Cloud Storage.")
    except Exception as e:
        logger.error(f"Failed to upload '{src_file}' to Cloud Storage: {e}")
        logger.debug(traceback.format_exc())
    return


@functions_framework.http
def main(request):

    logger.info("Function execution started")

    try:
        # データ取得対象日付Range設定
        tokyo_tz = pytz.timezone("Asia/Tokyo")
        today = datetime.datetime.now(tokyo_tz).date()
        yesterday = today - datetime.timedelta(days=1)
        one_week_ago = today - datetime.timedelta(days=7)
        today_str = today.strftime("%Y%m%d")
        yesterday_str = yesterday.strftime("%Y-%m-%d")
        one_week_ago_str = one_week_ago.strftime("%Y-%m-%d")

        # スクレイピング: レース開催日 及び レースID取得
        logger.info(f"Coverage period is from {one_week_ago} to {yesterday}.")
        kaisai_date_list = get_kaisai_date(one_week_ago_str, yesterday_str)
        race_id_list = get_race_id_list(kaisai_date_list)
        print("race_id_list: ", race_id_list)

        # スクレイピング: レース結果取得
        logger.info("Race data scraping started")
        try:
            race_results = get_race_results(race_id_list, today_str)
        except Exception as e:
            print(f"An error occurred in race_results: {e}")
            print(traceback.format_exc())
            race_results = None

        try:
            get_returns(race_id_list, today_str)
        except Exception as e:
            print(f"An error occurred in get_returns: {e}")

        if race_results is not None:
            try:
                horse_id_list = race_results["horse_id"].unique()
                get_horse_results(horse_id_list, today_str)
            except Exception as e:
                print(f"An error occurred in get_horse_results: {e}")
                print(traceback.format_exc())

        try:
            get_speed_results(race_id_list, today_str)
        except Exception as e:
            print(f"An error occurred in get_speed_results: {e}")

        logger.info("Race data scraping finished")

        # Cloud Storage バケットへCSVファイル転送
        csv_files = [
            file for file in os.listdir(path=DOWNLOAD_FOLDER) if file.endswith(".csv")
        ]
        logger.info("CSV file upload to Cloud Storage started.")
        for src_file in csv_files:
            gcs_uploader(src_file)
        logger.info("CSV file upload to Cloud Storage finished.")
        return "OK"
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        logger.debug(traceback.format_exc())
        return "Error", 500


# request = {}
# main(request)
