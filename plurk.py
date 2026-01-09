import requests
import re
import os
import json
import datetime
import time
import html
import xml.etree.ElementTree as ET

no_send_tg = 0
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BotTokenWM = os.environ.get("BOT_TOKEN_WM")
API_BASE_URL = os.environ.get("API_BASE_URL", "https://api.telegram.org")

def get_plurk_data(user):
    url = f'https://www.plurk.com/u/{user}'
    response = requests.get(url)
    html = response.text
    data = "[" + html.split("PUBLIC_PLURKS = [")[1].split("}];")[0] + "}]"
    data = re.sub(r'new Date\("([^"]+)"\)', r'"\1"', data)
    # print(data)
    with open('data.json', 'w', encoding='utf-8') as f:
        f.write(data)
    j = json.loads(data)
    return j

def get_plurk_data_from_rss(user, uid):
    """
    透過 RSS feed 取得 Plurk 資料，並進行內容清理
    """
    url = f'https://www.plurk.com/u/{user}.xml'
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"抓取 {user} 的 RSS feed 時發生錯誤: {e}")
        return []

    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    
    try:
        root = ET.fromstring(response.content)
        data = []
        for entry in root.findall('atom:entry', ns):
            link_tag = entry.find('atom:link', ns)
            if link_tag is not None and 'href' in link_tag.attrib:
                href = link_tag.attrib['href']
                base36_id = href.split('/')[-1]
                plurk_id = int(base36_id, 36)
            else:
                continue

            content_tag = entry.find('atom:content', ns)
            content_html = content_tag.text.strip() if content_tag is not None else ""

            # 1. 移除開頭的用戶名
            if content_html.startswith(user + " "):
                content_html = content_html[len(user) + 1:].lstrip()

            # 2. 提取圖片連結並從內容中移除
            # Plurk 圖片通常是 <a href="..."><img ...></a> 的形式
            image_pattern = r'<a[^>]*?href="([^"]+?\.(?:jpg|jpeg|png|gif))"[^>]*?>.*?</a>'
            image_urls = re.findall(image_pattern, content_html)
            content_html = re.sub(image_pattern, '', content_html).strip()

            # 3. 處理 YouTube 連結
            # 將整個 <a>...</a> 區塊替換成純 YouTube 連結
            youtube_pattern = r'(<a[^>]*?(?:i\.ytimg\.com|youtube\.com|youtu\.be)[^>]*?>.*?</a>)'
            youtube_blocks = re.findall(youtube_pattern, content_html)
            for block in youtube_blocks:
                video_id_match = re.search(r'i\.ytimg\.com/vi/([\w-]+)/', block)
                if video_id_match:
                    video_id = video_id_match.group(1)
                    youtube_url = f"https://www.youtube.com/watch?v={video_id}"
                    # 將整個 HTML 區塊替換為純粹的 URL
                    content_html = content_html.replace(block, youtube_url)

            # 4. 將 <br /> 標籤轉換為換行符 \n
            # 使用 re.sub 處理 <br>, <br/>, <br /> 等各種形式
            processed_content = re.sub(r'\s*<br\s*/?>\s*', '\n', content_html)
            
            # 5. 移除所有剩餘的 HTML 標籤 (例如 Plurk 轉噗的 <a> 標籤)
            # 因為我們已經處理完圖片和影片，剩下的標籤可以直接移除
            processed_content = re.sub(r'<[^>]+>', '', processed_content)

            # 6. 解碼 HTML 實體 (例如 &amp; -> &, &lt; -> <)
            processed_content = html.unescape(processed_content)

            # 7. 清理每行的頭尾空白，並移除處理後可能產生的空行
            lines = [line.strip() for line in processed_content.strip().split('\n')]
            content_raw = '\n'.join(filter(None, lines))

            published_tag = entry.find('atom:published', ns)
            posted = published_tag.text if published_tag is not None else ""

            plurk_entry = {
                'user_id': uid,
                'owner_id': uid,
                'plurk_id': plurk_id,
                'content_raw': content_raw,
                'posted': posted,
                'image_urls': image_urls  # 將提取的圖片列表加入
            }
            data.append(plurk_entry)
        
        return data

    except ET.ParseError as e:
        print(f"解析 {user} 的 XML 時發生錯誤: {e}")
        return []

# 10進位轉36進位
def plurk_id_convert(n):
    if n == 0:
        return "0"
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    result = []
    while n > 0:
        remainder = n % 36
        result.append(chars[remainder])
        n //= 36
    return "".join(result[::-1])

def send_tg_msg_thread_retry(chatid, thread_id, text, parse_mode="HTML", retry=0):
    # print("send msg")
    if no_send_tg:
        return 1
    url = f"{API_BASE_URL}/bot{BotTokenWM}/sendMessage"
    data = {
        "chat_id": chatid,
        "message_thread_id": thread_id,
        "text": text,
        "parse_mode": parse_mode,
        "link_preview_options": json.dumps({"is_disabled": True}),
        "disable_web_page_preview": 1,
    }
    if thread_id == 0:
        data.pop("message_thread_id")
    # print(data)
    try:
        a = requests.post(url, data=data)
        # print(a.text)
        if '{"ok":true' not in a.text and '{"ok": true' not in a.text:
            if "retry " in a.text:
                time.sleep(30)
            if retry > 3:
                return 0
            return send_tg_msg_thread_retry(chatid, thread_id, text, parse_mode, retry + 1)
        else:
            return 1
    except:
        time.sleep(30)
        return send_tg_msg_thread_retry(chatid, thread_id, text, parse_mode, retry + 1)

def send_tg_media_thread_retry(chatid, thread_id, files1, files2, text, parse_mode="HTML", retry=0):
    if no_send_tg:
        return 1
    url = f"{API_BASE_URL}/bot{BotTokenWM}/sendMediaGroup"
    j = []
    files = files1
    if len(files) == 0:
        files.append(files2[0])
    for i in range(0, len(files)):
        if retry >= 2:
            this_img = files[i].replace("http://","https://")
            this_type = "document"
        if files[i].endswith(".gif"):
            this_img = files[i].replace("http://","https://")
            this_type = "video"
        else:
            this_img = files[i].replace("http://","https://")
            this_type = "photo"
        if i == len(files)-1:
            j.append({"type":this_type,"media":this_img,"caption":text,"parse_mode":parse_mode,"link_preview_options": json.dumps({"is_disabled": True})})
        else:
            j.append({"type":this_type,"media":this_img})
    ms = json.dumps(j)
    data = {
        "chat_id": chatid,
        "message_thread_id": thread_id,
        "media": ms,
        # "caption": text,
        # "parse_mode": parse_mode,
        "link_preview_options": json.dumps({"is_disabled": True}),
    }
    if thread_id == 0:
        data.pop("message_thread_id")
    # print(url)
    # print(data)
    try:
        a = requests.post(url, data=data)
        # print(a.text)
        if '{"ok":true' not in a.text and '{"ok": true' not in a.text:
            if "retry " in a.text:
                time.sleep(30)
            if retry > 3:
                print("go send msg")
                return send_tg_msg_thread_retry(chatid, thread_id, text, parse_mode, 0)
                print("go send msg done")
            else:
                time.sleep(3)
                return send_tg_media_thread_retry(chatid, thread_id, files1, files2, text, parse_mode, retry + 1)
        else:
            return 1
    except:
        time.sleep(30)
        return send_tg_media_thread_retry(chatid, thread_id, files1, files2, text, parse_mode, retry + 1)

def main(user, username, tag, uid, thread_id=0):
    # data = get_plurk_data(user)    
    data = get_plurk_data_from_rss(user, uid)
    path = os.path.join(ROOT_DIR, f"plurk_{uid}.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            old = f.read().split("\n")
    except:
        with open(path, "w", encoding="utf-8") as f:
            f.write("")
            old = []
    for j in reversed(data):
        user_id = j['user_id']
        owner_id = j['owner_id']
        if user_id != uid or owner_id != uid:
            continue
        plurk_id = j['plurk_id']
        if str(plurk_id) in old:
            continue
        # 直接從處理好的資料中取得內容和圖片連結
        content_raw = j['content_raw']
        image_urls = j['image_urls']
        posted = j['posted']
        # 轉換時間格式
        # date_obj = datetime.datetime.strptime(posted, '%a, %d %b %Y %H:%M:%S %Z')
        # 新的 RSS 時間格式 (ISO 8601) 解析
        if not posted:
            continue
        date_obj = datetime.datetime.fromisoformat(posted.replace("Z", "+00:00"))
        # 統一轉換為 GMT+8 時區
        date_obj_gmt8 = date_obj + datetime.timedelta(hours=8)
        formatted_date = date_obj_gmt8.strftime('%Y-%m-%d %H:%M:%S')
        # 輸出文字
        send_data = f"<blockquote>{content_raw}</blockquote>\n——————————\n#{tag} #Plurk\n<blockquote>時間： {formatted_date}\n頻道： <a href=\"https://www.plurk.com/u/{user}\">{username}</a>\n貼文： https://www.plurk.com/p/{plurk_id_convert(plurk_id)}"
        
        # 提取所有符合的圖片網址
        # image_urls = re.findall(r'https?://[\w.-]+/[^\s]+?\.(?:jpg|jpeg|png|gif)(?=\s|$)', content_raw)
        if len(image_urls) > 0:
            send_data += "\n圖片： "
            for i in range(0, len(image_urls)):
                send_data += f"<a href=\"{image_urls[i]}\">[{i+1}]</a> "
        send_data += "</blockquote>"
        # print(send_data)
        # print("----------------------------------")
        # 發送telegram
        if thread_id == 0:
            chat_id = -1002291115765
        else:
            chat_id = -1002258100525
        send_ok = 0
        if len(image_urls) > 0:
            send_ok = send_tg_media_thread_retry(chat_id, thread_id, image_urls, [], send_data)
        else:
            send_ok = send_tg_msg_thread_retry(chat_id, thread_id, send_data)
        if send_ok:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{plurk_id}\n")

main("GJO_Ling", "傑歐", "傑歐", 7058957, 261244)
main("TAMMEDIA", "提恩傳媒", "提恩", 15581901, 15546)

