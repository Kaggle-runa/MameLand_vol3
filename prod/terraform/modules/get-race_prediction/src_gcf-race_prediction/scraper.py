import sys
import asyncio
from pyppeteer import launch
import re
import pandas as pd

async def extract_horse_jockey_trainer_data(page):
    rows = await page.querySelectorAll('.HorseList')
    data = []

    for row in rows:
        columns = await row.querySelectorAll('td')
        row_data = []

        for column in columns:
            class_name = await page.evaluate('(element) => element.getAttribute("class")', column)
            if class_name in ['HorseInfo']:
                href = await column.querySelectorEval('a', '(element) => element.getAttribute("href")')
                row_data.append(re.findall(r'horse/(\d*)', href)[0])
            elif class_name in ['Jockey']:
                href = await column.querySelectorEval('a', '(element) => element.getAttribute("href")')
                row_data.append(re.findall(r'jockey/result/recent/(\w*)', href)[0])
            elif class_name in ['Trainer']:
                href = await column.querySelectorEval('a', '(element) => element.getAttribute("href")')
                row_data.append(re.findall(r'trainer/result/recent/(\w*)', href)[0])
            row_data.append(await page.evaluate('(element) => element.textContent', column))
        data.append(row_data)
    return data


async def extract_race_info(page):
    race_data = await page.querySelector('.RaceList_Item02')
    race_text = await page.evaluate('(element) => element.textContent', race_data)
    texts = re.findall(r'\w+', race_text)

    text_patterns = {
        '0m': ('course_length', lambda x: int(re.findall(r'\d+', x)[-1])),
        '晴': ('weather', '晴'),
        '曇': ('weather', '曇'),
        '雨': ('weather', '雨'),
        '良': ('ground_condition', '良'),
        '稍重': ('ground_condition', '稍重'),
        '重': ('ground_condition', '重'),
        '不良': ('ground_condition', '不良'),
        '芝': ('race_type', '芝'),
        'ダ': ('race_type', 'ダート'),
        '障': ('race_type', '障害'),
        '右': ('race_turn', '右'),
        '左': ('race_turn', '左'),
        '直線': ('race_turn', '直線'),
        '札幌': ('location', '札幌'),
        '函館': ('location', '函館'),
        '福島': ('location', '福島'),
        '新潟': ('location', '新潟'),
        '東京': ('location', '東京'),
        '中山': ('location', '中山'),
        '中京': ('location', '中京'),
        '京都': ('location', '京都'),
        '阪神': ('location', '阪神'),
        '小倉': ('location', '小倉'),
    }

    race_info = {}
    race_title = texts[0]
    hurdle_race_flg = False

    for text in texts:
        for pattern, (key, value) in text_patterns.items():
            if pattern in text:
                if callable(value):
                    race_info[key] = [value(text)]
                else:
                    race_info[key] = [value]
                if pattern == '障':
                    hurdle_race_flg = True

    return race_info, race_title, hurdle_race_flg


def process_horse_jockey_trainer_data(data):
    df = pd.DataFrame(data)
    df = df[[0, 1, 4, 5, 6, 12, 13, 11, 3, 7, 8, 9, 10]]
    df.columns = ['frame_number', 'horse_number', 'horse_name', 'sex_age', 'carried_weight', 'odds', 'popularity', 'horse_weight', 'horse_id', 'jockey_id', 'jockey', 'trainer_id', 'trainer']
    return df

async def scraping_race_card(race_id, race_date, RACE_CARD_URL):

    # ブラウザ起動
    browser = await launch(
        headless=True,
        args = [
            # '--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
            # "--start-maximized",
        ],
    )
    print('Launched browser.')

    try:
        query = [
            'race_id=' + str(race_id)
        ]
        url = RACE_CARD_URL + '?' + '&'.join(query)
        print(f'scraping: {url}')

        # 出走表Webページへアクセス
        page = await browser.newPage()
        await page.goto(url, {'timeout': 180000})
        await page.waitForSelector('.HorseList', {'visible': True}) 

        data = await extract_horse_jockey_trainer_data(page)
        race_info, race_title, hurdle_race_flg = await extract_race_info(page)
        print(f'race_info: {race_info}')
        print(f'race_title: {race_title}')
        print(f'hurdle_race_flg: {hurdle_race_flg}')
    except asyncio.TimeoutError:
        print("Timeout error!")
        return None
    except Exception as e:
        print(e)
    finally:
        # ページを閉じる
        if 'page' in locals():  # pageが定義されている場合のみcloseする
            await page.close()

    await browser.close()
    print('Closed browser.')

    return data, race_info, race_title, hurdle_race_flg

if __name__ == "__main__":
  
    # コマンドライン引数から変数を取得
    race_id = sys.argv[1]
    race_date = sys.argv[2]
    RACE_CARD_URL = sys.argv[3]
    DOWNLOAD_FOLDER = sys.argv[4]

    # race_id = '202410030801'
    # race_date = '2024-07-21'
    # RACE_CARD_URL = 'https://race.netkeiba.com/race/shutuba.html'

    data, race_info, race_title, hurdle_race_flg = asyncio.run(scraping_race_card(race_id, race_date, RACE_CARD_URL))

    # tableデータ作成
    df = process_horse_jockey_trainer_data(data)
    df['race_id'] = race_id
    df['race_title'] = race_title
    df['event_date'] = [race_date] * len(df)

    for key, value in race_info.items():
        df[key] = value * len(df)
    if hurdle_race_flg:
        df["race_turn"] = ['障害'] * len(df)

    # 列の並び替え
    new_order = [
        'race_id', 'event_date', 'location', 'race_title', 'race_type', 'race_turn', 
        'course_length', 'weather', 'ground_condition', 'frame_number', 
        'horse_number', 'horse_id', 'horse_name', 'sex_age', 'carried_weight', 
        'jockey_id', 'jockey', 'odds', 'popularity', 
        'horse_weight', 'trainer'
    ]
    df = df[new_order]

    # 改行タグを削除
    df['horse_name'] = df['horse_name'].str.replace(r'[\n\t]', '', regex=True)
    df['jockey'] = df['jockey'].str.replace(r'[\n\t]', '', regex=True)
    df['popularity'] = df['popularity'].str.replace(r'[\n\t]', '', regex=True)
    df['horse_weight'] = df['horse_weight'].str.replace(r'[\n\t]', '', regex=True)

    df.to_csv(f'{DOWNLOAD_FOLDER}/race_card.csv', index=False)