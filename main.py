import os
import sys
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
)

# ==========================================
# 1. 全域設定區 (改用環境變數)
# ==========================================

app = Flask(__name__)

# 從環境變數讀取 Token (等等會在 Render 設定)
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')

if LINE_CHANNEL_ACCESS_TOKEN is None or LINE_CHANNEL_SECRET is None:
    print("錯誤：未設定 LINE Token 環境變數")
    sys.exit(1)

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 目標網址
TARGET_URL = "https://summercamp.luckertw.com/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# 全域資料庫
CAMP_DATABASE = []

# ==========================================
# 2. 爬蟲邏輯
# ==========================================
# 修改後的 CampScraper (通用型：專抓「有圖片的連結」)
class CampScraper:
    def __init__(self, url):
        self.url = url
        self.data_list = []

    def fetch_page(self):
        print(f"正在連線至: {self.url} ...")
        try:
            # 這裡增加 verify=False 避免 SSL 憑證報錯
            response = requests.get(self.url, headers=HEADERS, timeout=15)
            response.encoding = 'utf-8'
            return response.text if response.status_code == 200 else None
        except Exception as e:
            print(f"連線錯誤: {e}")
            return None

    def parse_html(self, html_content):
        if not html_content: return
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 策略改變：直接尋找所有「包含 img 標籤的 a 連結」
        # 因為營隊列表通常都是一張大圖配上一個連結
        links = soup.find_all('a')
        
        print(f"掃描到 {len(links)} 個連結，正在過濾營隊...")

        for link in links:
            try:
                # 1. 必須要有圖片 (img)
                img_tag = link.find('img')
                if not img_tag: continue
                
                # 2. 抓取標題 (嘗試從圖片 alt 或連結文字抓)
                title = link.get_text(strip=True)
                if not title and 'alt' in img_tag.attrs:
                    title = img_tag['alt']
                
                # 如果標題太短，可能是 logo 或 icon，跳過
                if len(title) < 5: continue
                
                # 3. 處理連結網址
                href = link['href']
                if not href.startswith('http'):
                    href = "https://summercamp.luckertw.com" + href.lstrip('/')

                # 4. 處理圖片網址
                image_url = img_tag['src']
                if not image_url.startswith('http'):
                    image_url = "https://summercamp.luckertw.com" + image_url.lstrip('/')

                # 5. 成功抓取
                self.data_list.append({
                    "title": title,
                    "date": "詳見官網",
                    "price": "點擊查看",
                    "region": "全台",
                    "url": href,
                    "image": image_url,
                    "tags": ["精選營隊"]
                })
            except:
                continue
                
        # 去除重複資料
        unique_data = []
        seen_urls = set()
        for item in self.data_list:
            if item['url'] not in seen_urls:
                unique_data.append(item)
                seen_urls.add(item['url'])
        
        self.data_list = unique_data
        print(f"過濾完成，共抓到 {len(self.data_list)} 筆有效資料")
# ==========================================
# 3. LINE Flex Message
# ==========================================
def create_camp_flex_message(camps):
    bubbles = []
    for camp in camps[:10]:
        bubble = {
            "type": "bubble",
            "hero": {
                "type": "image", "url": camp['image'], "size": "full",
                "aspectRatio": "20:13", "aspectMode": "cover",
                "action": { "type": "uri", "uri": camp['url'] }
            },
            "body": {
                "type": "box", "layout": "vertical",
                "contents": [
                    { "type": "text", "text": camp['title'], "weight": "bold", "size": "xl", "wrap": True },
                    {
                        "type": "box", "layout": "baseline", "margin": "md",
                        "contents": [
                            { "type": "text", "text": camp['price'], "weight": "bold", "size": "lg", "color": "#1DB446", "flex": 0 },
                            { "type": "text", "text": f" | {camp['date']}", "size": "sm", "color": "#999999", "flex": 1, "align": "end" }
                        ]
                    }
                ]
            },
            "footer": {
                "type": "box", "layout": "vertical", "spacing": "sm",
                "contents": [
                    { "type": "button", "style": "primary", "height": "sm", "action": { "type": "uri", "label": "查看詳情", "uri": camp['url'] } }
                ]
            }
        }
        bubbles.append(bubble)
    return FlexSendMessage(alt_text="營隊搜尋結果", contents={"type": "carousel", "contents": bubbles}) if bubbles else None

# ==========================================
# 4. Flask Server 邏輯
# ==========================================
def update_camp_database():
    global CAMP_DATABASE
    scraper = CampScraper(TARGET_URL)
    html = scraper.fetch_page()
    if html:
        scraper.parse_html(html)
        CAMP_DATABASE = scraper.data_list
        print(f"資料庫更新完成，共 {len(CAMP_DATABASE)} 筆")

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@app.route("/", methods=['GET']) # 增加一個根目錄檢查，避免 Render 報錯
def home():
    return "LINE Bot is Running!"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text.strip()
    
    if msg == "更新資料":
        update_camp_database()
        reply_text = f"資料庫已更新！目前有 {len(CAMP_DATABASE)} 筆營隊資訊。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    if not CAMP_DATABASE:
        update_camp_database()

    found_camps = []
    keywords = msg.split()
    for camp in CAMP_DATABASE:
        if any(k in camp['title'] for k in keywords) or any(k in camp['date'] for k in keywords):
            found_camps.append(camp)

    if found_camps:
        line_bot_api.reply_message(event.reply_token, create_camp_flex_message(found_camps))
    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"找不到「{msg}」。(目前資料庫: {len(CAMP_DATABASE)}筆)"))

if __name__ == "__main__":
    # 本機測試用，雲端不會執行這行
    app.run(port=5000, debug=True)

