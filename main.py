import os
import sys
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
# 1. 全域設定
# ==========================================
app = Flask(__name__)

# 從環境變數讀取 Token
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('ruNCmLnmh/ngHJfv4ZtPdATOISHG9kA4hoUkjlrr2+k1wftKHZp9ol7Oirr2L60gLSDEAT1vtJwCphJVYB0v4R2KtYQNChgNAiqb6N4TGVxUYphajdcWmiiY4WcHsj7kFSECb5hSKRAskZTWk+WodAdB04t89/1O/w1cDnyilFU=')
LINE_CHANNEL_SECRET = os.environ.get('7b10d2873a104f96431c43cfd66d0bc2')

if LINE_CHANNEL_ACCESS_TOKEN is None or LINE_CHANNEL_SECRET is None:
    print("⚠️ 警告：未設定 LINE Token")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# 全域資料庫
CAMP_DATABASE = []

# ==========================================
# 2. 國高中營隊爬蟲 (KKTIX + BeClass)
# ==========================================
class HighSchoolCampScraper:
    def __init__(self):
        self.data_list = []

    def fetch_all(self):
        print("🚀 開始搜尋國高中營隊...")
        self.data_list = [] 
        
        # 1. 搜尋 KKTIX (鎖定「大學營隊」因為這是給高中生參加的)
        self.scrape_kktix(keyword="大學營隊")
        self.scrape_kktix(keyword="高中體驗營")
        
        # 2. 搜尋 BeClass (許多學術講座、志工營隊)
        self.scrape_beclass(keyword="高中營隊")
        
        # 去除重複 (因為不同關鍵字可能找到同一個活動)
        unique_data = []
        seen_urls = set()
        for item in self.data_list:
            if item['url'] not in seen_urls:
                unique_data.append(item)
                seen_urls.add(item['url'])
        
        # 隨機打亂，讓結果看起來比較豐富
        random.shuffle(unique_data)
        self.data_list = unique_data
        print(f"✅ 爬蟲結束，共找到 {len(self.data_list)} 筆適合國高中的活動")
        return self.data_list

    def scrape_kktix(self, keyword):
        """KKTIX 爬蟲"""
        print(f"正在 KKTIX 搜尋: {keyword} ...")
        # KKTIX 的搜尋網址結構
        url = f"https://kktix.com/events?search={keyword}&start_at=2024-01-01&end_at=2026-12-31"
        
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            events = soup.select('ul.event-list > li')
            
            for event in events:
                try:
                    title_tag = event.select_one('h2')
                    if not title_tag: continue
                    title = title_tag.get_text(strip=True)
                    
                    link_tag = event.select_one('a')
                    link = link_tag['href']
                    if not link.startswith('http'): link = "https://kktix.com" + link
                        
                    time_tag = event.select_one('.date')
                    date_str = time_tag.get_text(strip=True) if time_tag else "近期活動"
                    
                    # 圖片處理
                    img_tag = event.select_one('img')
                    image = img_tag['src'] if img_tag else ""
                    if not image: image = "https://images.unsplash.com/photo-1523580494863-6f3031224c94?auto=format&fit=crop&w=600&q=80"

                    self.data_list.append({
                        "title": title,
                        "date": date_str,
                        "source": "KKTIX",
                        "price": "詳見簡章",
                        "url": link,
                        "image": image
                    })
                except: continue
        except Exception as e:
            print(f"KKTIX 錯誤: {e}")

    def scrape_beclass(self, keyword):
        """BeClass 爬蟲 (需要特殊處理編碼)"""
        print(f"正在 BeClass 搜尋: {keyword} ...")
        # BeClass 的搜尋網址
        encoded_keyword = urllib.parse.quote(keyword)
        url = f"https://www.beclass.com/p/search.php?keyword={encoded_keyword}"
        
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            response.encoding = 'utf-8' # BeClass 主要是 UTF-8，但有時候會亂碼，強制設定
            
            soup = BeautifulSoup(response.text, 'html.parser')
            # BeClass 的列表通常在 div.search_result_item 或是直接是連結列表
            # 這裡使用比較通用的抓法
            links = soup.find_all('a', href=True)
            
            count = 0
            for link in links:
                href = link['href']
                text = link.get_text(strip=True)
                
                # 過濾條件：連結必須包含 rid (報名ID) 且標題夠長
                if 'rid=' in href and len(text) > 5 and '營' in text:
                    if not href.startswith('http'):
                        href = "https://www.beclass.com/" + href.lstrip('/')
                    
                    self.data_list.append({
                        "title": text,
                        "date": "詳見內文",
                        "source": "BeClass",
                        "price": "報名系統",
                        "url": href,
                        "image": "https://images.unsplash.com/photo-1517486808906-6ca8b3f04846?auto=format&fit=crop&w=600&q=80" # BeClass 很難抓圖，統一用預設圖
                    })
                    count += 1
                    if count >= 8: break # BeClass 雜訊多，抓前 8 筆就好
        except Exception as e:
            print(f"BeClass 錯誤: {e}")

# ==========================================
# 3. LINE Flex Message
# ==========================================
def create_camp_flex_message(camps):
    bubbles = []
    for camp in camps[:10]:
        # 根據來源設定不同顏色
        source_color = "#E64A19" if camp['source'] == "KKTIX" else "#1976D2"
        
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
                    { "type": "text", "text": camp['source'], "size": "xs", "color": source_color, "weight": "bold" },
                    { "type": "text", "text": camp['title'], "weight": "bold", "size": "md", "wrap": True, "margin": "xs" },
                    {
                        "type": "box", "layout": "baseline", "margin": "md",
                        "contents": [
                            { "type": "text", "text": camp['date'], "size": "xs", "color": "#999999", "flex": 1 }
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
    
    return FlexSendMessage(alt_text="國高中營隊資訊", contents={"type": "carousel", "contents": bubbles}) if bubbles else None

# ==========================================
# 4. Flask Server
# ==========================================
@app.route("/", methods=['GET'])
def home():
    return "High School Camp Bot is Running!"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text.strip()
    global CAMP_DATABASE
    
    # 只要資料庫是空的，或是使用者輸入特定指令，就觸發爬蟲
    if not CAMP_DATABASE or msg in ["更新", "營隊", "寒假", "高中"]:
        scraper = HighSchoolCampScraper()
        CAMP_DATABASE = scraper.fetch_all()
        
        if msg == "更新":
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"資料更新完畢！共 {len(CAMP_DATABASE)} 筆國高中營隊。"))
            return

    # 搜尋過濾
    found_camps = []
    keywords = msg.split()
    
    # 如果使用者輸入很籠統的詞，回傳全部
    if msg in ["營隊", "寒假", "高中", "推薦"]:
        found_camps = CAMP_DATABASE
    else:
        for camp in CAMP_DATABASE:
            if any(k in camp['title'] for k in keywords):
                found_camps.append(camp)

    if found_camps:
        line_bot_api.reply_message(event.reply_token, create_camp_flex_message(found_camps))
    else:
        # 找不到時，除了
