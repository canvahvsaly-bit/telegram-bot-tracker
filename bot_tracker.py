import os
import time
import csv
import io
import urllib.parse
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import schedule
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ==================== CẤU HÌNH THÔNG TIN ====================
TOKEN = "8998865332:AAGAKEQ94VibKBMeYFZOyjieX7k8m6E8m0k"
MY_CHAT_ID = 5693795211
SHEET_ID = "1IlNNxjZaqPzGObPXgkB6UQ7VAC9aBiDr5qDV_3yxksE"
DEFAULT_TAB = "Tracker 2"
# ============================================================

bot = telebot.TeleBot(TOKEN)

# Máy chủ web giả lập để Render giữ bot luôn sống
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Telegram Tracker is running 24/7!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

def get_content_from_sheet(tab_name):
    encoded_tab = urllib.parse.quote(tab_name)
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={encoded_tab}"
    try:
        response = requests.get(url, timeout=15)
        response.encoding = 'utf-8'
        if response.status_code != 200:
            return None
        
        reader = csv.reader(io.StringIO(response.text))
        rows = list(reader)
        data = []
        for row in rows[1:]:
            if len(row) >= 1 and row[0].strip():
                content = row[0].strip()
                btn_label = row[1].strip() if len(row) > 1 and row[1].strip() else None
                data.append((content, btn_label))
        return data
    except Exception as e:
        print(f"Lỗi: {e}")
        return None

def safe_send_message(chat_id, text, reply_markup=None):
    MAX_LENGTH = 3800
    if len(text) <= MAX_LENGTH:
        try:
            bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception:
            bot.send_message(chat_id, text, reply_markup=reply_markup)
    else:
        parts = [text[i:i+MAX_LENGTH] for i in range(0, len(text), MAX_LENGTH)]
        for idx, part in enumerate(parts):
            markup = reply_markup if idx == len(parts) - 1 else None
            try:
                bot.send_message(chat_id, part, reply_markup=markup, parse_mode="Markdown")
            except Exception:
                bot.send_message(chat_id, part, reply_markup=markup)

def send_sheet_step(chat_id, tab_name, step_index):
    data = get_content_from_sheet(tab_name)
    if not data or step_index >= len(data):
        safe_send_message(chat_id, f"❌ Không tìm thấy nội dung trong tab *{tab_name}*!")
        return

    content, btn_label = data[step_index]
    total_steps = len(data)
    markup = InlineKeyboardMarkup()
    
    if step_index < total_steps - 1:
        btn_text = btn_label if btn_label else f"Đọc tiếp Chặng {step_index + 2} ➡️"
        callback_data = f"read:{tab_name}:{step_index + 1}"
        markup.add(InlineKeyboardButton(btn_text, callback_data=callback_data))
    else:
        content += "\n\n━━━━━━━━━━━━━━━\n🎉 *BẠN ĐÃ HOÀN THÀNH BÀI ĐỌC!*\n⏰ *Hẹn gặp lại lúc 21h00 tối mai.*"

    safe_send_message(chat_id, content, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("read:"))
def handle_next_step(call):
    _, tab_name, next_step = call.data.split(":", 2)
    send_sheet_step(call.message.chat.id, tab_name, int(next_step))
    bot.answer_callback_query(call.id)

@bot.message_handler(commands=['start'])
def cmd_start(message):
    safe_send_message(message.chat.id, f"📖 *BẮT ĐẦU BÀI ĐỌC: {DEFAULT_TAB}*")
    send_sheet_step(message.chat.id, DEFAULT_TAB, 0)

@bot.message_handler(commands=['doc'])
def cmd_doc(message):
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        tab_name = args[1].strip()
        safe_send_message(message.chat.id, f"📖 *BẮT ĐẦU BÀI ĐỌC: {tab_name}*")
        send_sheet_step(message.chat.id, tab_name, 0)
    else:
        safe_send_message(message.chat.id, "💡 Gõ `/doc <Tên_Tab>` để mở bài.")

@bot.message_handler(func=lambda msg: True)
def echo_all(message):
    bot.reply_to(message, "Gõ /start để đọc bài nhé!")

def daily_job():
    safe_send_message(MY_CHAT_ID, f"⏰ *21h00 rồi! Dành 3 phút nạp bài học tối nay nhé:*")
    send_sheet_step(MY_CHAT_ID, DEFAULT_TAB, 0)

def run_scheduler():
    schedule.every().day.at("21:00").do(daily_job)
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    print(f"✅ Bot '{DEFAULT_TAB}' đang chạy...")
    bot.remove_webhook()
    
    # 1. Chạy Web Server giữ kết nối cho Render
    t_web = threading.Thread(target=run_dummy_server)
    t_web.daemon = True
    t_web.start()

    # 2. Chạy bộ hẹn giờ 21h00
    t_sched = threading.Thread(target=run_scheduler)
    t_sched.daemon = True
    t_sched.start()
    
    # 3. Lắng nghe tin nhắn từ Telegram
    bot.infinity_polling()