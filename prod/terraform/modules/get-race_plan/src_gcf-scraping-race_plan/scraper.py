import ast
import asyncio
import logging
import sys

from pyppeteer import launch

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s - %(levelname)s - %(message)s"
)


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

        race_info_list = []
        for kaisai_date in kaisai_date_list:
            page = None
            try:
                query = ["kaisai_date=" + str(kaisai_date)]
                url = RACE_LIST_URL + "?" + "&".join(query)
                print(f"scraping: {url}")

                page = await browser.newPage()
                await page.goto(url, {"timeout": 180000})
                await page.waitForSelector(".RaceList_Box", {"visible": True})

                race_data_list = await page.evaluate(
                    """() => {
                    const raceItems = document.querySelectorAll('.RaceList_DataItem a[href*="shutuba.html"]');
                    const data = [];
                    raceItems.forEach(aTag => {
                        const raceIdMatch = aTag.href.match(/race_id=(\d+)/);
                        const raceId = raceIdMatch ? raceIdMatch[1] : null;
                        const raceTimeElement = aTag.querySelector('.RaceList_Itemtime');
                        const raceTime = raceTimeElement ? raceTimeElement.textContent.trim() : null;
                        data.push({ raceId, raceTime });
                    });
                    return data;
                }"""
                )

                for race_data in race_data_list:
                    race_info_list.append(
                        {
                            "race_id": race_data["raceId"],
                            "race_date": kaisai_date,
                            "race_time": race_data["raceTime"],
                        }
                    )
            except asyncio.TimeoutError:
                logger.error(f"Timeout error while scraping {url}")
            except Exception as e:
                logger.error(f"Error while scraping {url}: {str(e)}")
            finally:
                # ページを閉じる
                if "page" in locals():  # pageが定義されている場合のみcloseする
                    await page.close()

        await browser.close()
        logger.info("Race information scraping completed.")

        # race_idリスト出力
        print(race_info_list)
        return

    except Exception as e:
        logger.error(f"Unexpected error in scraping_race_info: {str(e)}")
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
        logger.error(f"Unexpected error in main: {str(e)}")
