import os
import sys
import threading
import time
import requests
import urllib.parse
import random
from bs4 import BeautifulSoup
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
)

# ==========================================
# 1. 系統設定區
# ==========================================
app = Flask(__name__)

# 讀取環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')

# 若本地測試沒有設定環境變數，防止報錯
if LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
    handler = WebhookHandler(LINE_CHANNEL_SECRET)
else:
    print("⚠️ 警告：未設定 LINE Token，Bot 無法運作。")

# 偽裝成瀏覽器，避免被網站阻擋
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# 全域資料庫 (存在記憶體中)
# 結構: [{"title": "...", "url": "...", ...}]
CAMP_DATABASE = []
IS_UPDATING = False  # 鎖定標記，避免同時多人按更新導致當機

# ==========================================
# 2. 爬蟲核心邏輯
# ==========================================
class CampScraper:
    def __init__(self):
        self.data_list = []

    def fetch_all_in_background(self):
        """背景執行爬蟲，不卡住 LINE 回覆"""
        global CAMP_DATABASE, IS_UPDATING
        if IS_UPDATING:
            print("⏳ 爬蟲正在執行中，跳過本次請求...")
            return

        IS_UPDATING = True
        print("🚀 開始背景更新資料庫...")
        
        try:
            self.data_list = [] # 清空暫存
            
            # 1. 抓取 KKTIX (針對高中/大學營隊)
            self.scrape_kktix(keyword="大學營隊")
            self.scrape_kktix(keyword="高中體驗營")
            self.scrape_kktix(keyword="高中營隊")
            
            # 2. 抓取 BeClass (針對學術/志工)
            self.scrape_beclass(keyword="高中營隊")
            self.scrape_beclass(keyword="大學體驗")

            # 去除重複網址
            unique_data = []
            seen_urls = set()
            for item in self.data_list:
                if item['url'] not in seen_urls:
                    unique_data.append(item)
                    seen_urls.add(item['url'])
            
            # 更新全域資料庫
            if unique_data:
                random.shuffle(unique_data)
                CAMP_DATABASE = unique_data
                print(f"✅ 更新完成！目前共有 {len(CAMP_DATABASE)} 筆資料。")
            else:
                print("⚠️ 警告：本次沒有抓到任何資料。")
                
        except Exception as e:
            print(f"❌ 爬蟲發生致命錯誤: {e}")
        finally:
            IS_UPDATING = False

    def scrape_kktix(self, keyword):
        print(f"🔍 搜尋 KKTIX: {keyword}...")
        url = f"https://kktix.com/events?search={keyword}&start_at=2024-01-01&end_at=2026-12-31"
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            events = soup.select('ul.event-list > li')
            
            for event in events:
                try:
                    title = event.select_one('h2').get_text(strip=True)
                    link = event.select_one('a')['href']
                    if not link.startswith('http'): link = "https://kktix.com" + link
                    
                    time_tag = event.select_one('.date')
                    date_str = time_tag.get_text(strip=True) if time_tag else "詳見官網"
                    
                    # 圖片處理：嘗試抓取，若無則給隨機圖
                    img_tag = event.select_one('img')
                    img_url = img_tag['src'] if img_tag else self.get_random_image()
                    
                    self.data_list.append({
                        "title": title,
                        "date": date_str,
                        "source": "KKTIX",
                        "url": link,
                        "image": img_url
                    })
                except: continue
        except Exception as e:
            print(f"KKTIX 錯誤: {e}")

    def scrape_beclass(self, keyword):
        print(f"🔍 搜尋 BeClass: {keyword}...")
        # BeClass 搜尋連結
        encoded = urllib.parse.quote(keyword)
        url = f"https://www.beclass.com/p/search.php?keyword={encoded}"
        
        try:
            res = requests.get(url, headers=HEADERS, timeout=15)
            # BeClass 容易有編碼問題，先嘗試自動偵測
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # BeClass 列表項目通常在 div.search_result_item_content 或直接 a
            links = soup.find_all('a', href=True)
            
            count = 0
            for link in links:
                href = link['href']
                text = link.get_text(strip=True)
                
                # 過濾條件：一定要包含 'rid=' (這是報名頁特徵) 且標題要包含關鍵字
                if 'rid=' in href and len(text) > 5 and ('營' in text or '體驗' in text):
                    if not href.startswith('http'): href = "https://www.beclass.com/" + href.lstrip('/')
                    
                    self.data_list.append({
                        "title": text,
                        "date": "詳見簡章",
                        "source": "BeClass",
                        "url": href,
                        "image": self.get_random_image() # BeClass 沒圖，直接給美圖
                    })
                    count += 1
                    if count >= 10: break # 限制數量以免太多雜訊
        except Exception as e:
            print(f"BeClass 錯誤: {e}")

    def get_random_image(self):
        """提供高品質的隨機營隊圖片"""
        images = [
            "https://images.unsplash.com/photo-1523580494863-6f3031224c94?w=600&q=80", # 大學
            "https://images.unsplash.com/photo-1517486808906-6ca8b3f04846?w=600&q=80", # 讀書
            "https://images.unsplash.com/photo-1503676260728-1c00da094a0b?w=600&q=80", # 學習
            "https://images.unsplash.com/photo-1531482615713-2afd69097998?w=600&q=80", # 團隊
            "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?w=600&q=80"  # 討論
        ]
        return random.choice(images)

# ==========================================
# 3. LINE Flex Message
# ==========================================
def create_flex_message(camps):
    bubbles = []
    # 取前 12 筆顯示
    for camp in camps[:12]:
        color = "#E64A19" if camp['source'] == "KKTIX" else "#1976D2"
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
                    { "type": "text", "text": camp['source'], "color": color, "weight": "bold", "size": "xs" },
                    { "type": "text", "text": camp['title'], "weight": "bold", "size": "sm", "wrap": True, "margin": "xs" },
                    { "type": "text", "text": camp['date'], "size": "xxs", "color": "#aaaaaa", "margin": "md" }
                ]
            },
            "footer": {
                "type": "box", "layout": "vertical",
                "contents": [
                    { "type": "button", "style": "primary", "height": "sm", "action": { "type": "uri", "label": "查看內容", "uri": camp['url'] } }
                ]
            }
        }
        bubbles.append(bubble)
    return FlexSendMessage(alt_text="營隊搜尋結果", contents={"type": "carousel", "contents": bubbles})

# ==========================================
# 4. 伺服器入口
# ==========================================
@app.route("/", methods=['GET'])
def home():
    return f"Bot Running. Database size: {len(CAMP_DATABASE)}"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 啟動時自動跑一次爬蟲 (使用執行緒以免卡住啟動)
def initial_scrape():
    scraper = CampScraper()
    scraper.fetch_all_in_background()

# 啟動背景執行緒
threading.Thread(target=initial_scrape).start()

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text.strip()
    
    # 指令：強制更新
    if msg == "更新":
        if IS_UPDATING:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🔄 系統正在更新中，請稍後再試..."))
        else:
            # 開一個新執行緒去跑，馬上回覆使用者，避免 LINE Timeout
            scraper = CampScraper()
            thread = threading.Thread(target=scraper.fetch_all_in_background)
            thread.start()
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚡ 收到指令！正在後台搜索最新營隊資訊...\n請約 30 秒後輸入「寒假」查看結果。"))
        return

    # 搜尋邏輯
    found = []
    
    # 模糊關鍵字
    if msg in ["寒假", "營隊", "高中", "推薦", "活動"]:
        found = CAMP_DATABASE
    else:
        # 精確搜尋
        for camp in CAMP_DATABASE:
            if msg in camp['title']:
                found.append(camp)

    if found:
        # 隨機打亂結果，讓使用者每次看到不一樣的
        random.shuffle(found)
        line_bot_api.reply_message(event.reply_token, create_flex_message(found))
    else:
        # 找不到資料時的回覆
        reply_txt = f"找不到「{msg}」相關營隊。\n目前資料庫有 {len(CAMP_DATABASE)} 筆資料。\n\n💡 建議：\n1. 輸入「更新」抓取最新資料\n2. 輸入「寒假」或「高中」查看熱門活動"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_txt))

if __name__ == "__main__":
    app.run(port=5000)
