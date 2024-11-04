import ast
import asyncio
import json
import logging
import os
import re
import sys

# from dotenv import load_dotenv
from pyppeteer import launch
from pyppeteer.errors import NetworkError, TimeoutError

# 環境変数取得
# load_dotenv()
DOWNLOAD_FOLDER = os.environ.get("DOWNLOAD_FOLDER")


# ロギングの設定
logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def scraping_race_info(kaisai_date_list, RACE_LIST_URL):
    browser = None
    try:
        # ブラウザ起動
        browser = await launch(
            headless=True,
            args=[
                # '--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
                # "--start-maximized",
            ],
        )
        logger.info("Launched browser.")

        race_id_list = []
        for kaisai_date in kaisai_date_list:
            try:
                query = ["kaisai_date=" + str(kaisai_date)]
                url = RACE_LIST_URL + "?" + "&".join(query)
                print(f"scraping: {url}")

                page = await browser.newPage()
                await page.goto(url, {"timeout": 180000})
                await page.waitForSelector(".RaceList_Box", {"visible": True})

                hrefs = await page.evaluate(
                    """() => {
                    const raceItems = document.querySelectorAll('.RaceList_DataItem a[href*="result.html"]');
                    const hrefs = [];
                    raceItems.forEach(aTag => {
                        hrefs.push(aTag.href);
                    });
                    return hrefs;
                }"""
                )

                # hrefsからrace_idを抽出
                pattern = r"race_id=(\d+)"
                for href in hrefs:
                    match = re.search(pattern, href)
                    if match:
                        race_id_list.append(match.group(1))
            except TimeoutError:
                logger.error(f"Timeout error while scraping {url}")
            except NetworkError as e:
                logger.error(f"Network error while scraping {url}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error while scraping {url}: {e}")
            finally:
                if page:
                    await page.close()

        await browser.close()

        # /tmp/ に race_id_list.json を保存
        filepath = os.path.join(DOWNLOAD_FOLDER, "race_id_list.json")
        with open(filepath, "w") as f:
            json.dump(race_id_list, f)

        logger.info(f"Saved race_id_list to {filepath}")
        logger.info(f"Total race IDs scraped: {len(race_id_list)}")

        # race_idリスト出力
        logger.info(race_id_list)
        return

    except Exception as e:
        logger.error(f"An error occurred during scraping: {e}")
        return []

    finally:
        if browser:
            await browser.close()
            logger.info("Closed browser.")


if __name__ == "__main__":
    try:
        # コマンドライン引数から変数を取得
        kaisai_date_list = ast.literal_eval(sys.argv[1])
        RACE_LIST_URL = sys.argv[2]
        logger.info(f"RACE_LIST_URL: {RACE_LIST_URL}")

        asyncio.run(scraping_race_info(kaisai_date_list, RACE_LIST_URL))

    except IndexError:
        logger.error("Not enough command line arguments provided.")
    except ValueError:
        logger.error("Invalid kaisai_date_list format provided.")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
