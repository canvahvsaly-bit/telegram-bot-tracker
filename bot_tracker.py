import os
import re
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
from collections import defaultdict, deque

# ==================== CẤU HÌNH THÔNG TIN BẢO MẬT ====================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8998865332:AAGAKEQ94VibKBMeYFZOyjieX7k8m6E8m0k").strip()
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID", "-1004381678817").strip()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()

MY_CHAT_ID = 5693795211
SHEET_ID = "1IlNNxjZaqPzGObPXgkB6UQ7VAC9aBiDr5qDV_3yxksE"
DEFAULT_TAB = "Tracker 2"
# ====================================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN)
group_history = defaultdict(lambda: deque(maxlen=100))
BOT_USERNAME = ""

# ----------------- 1. BỘ NÃO CLAUDE (ƯU TIÊN SỐ 1) -----------------
def ask_claude(prompt):
    if not ANTHROPIC_API_KEY:
        return None, "Chưa có ANTHROPIC_API_KEY"
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": "claude-3-5-haiku-20241022",
        "max_tokens": 1500,
        "messages": [{"role": "user", "content": prompt}]
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=35)
        if res.status_code == 200:
            return res.json()["content"][0]["text"].strip(), None
        else:
            err = res.json().get("error", {}).get("message", res.text)
            return None, f"Claude HTTP {res.status_code}: {err}"
    except Exception as e:
        return None, f"Claude lỗi: {e}"

# ----------------- 2. BỘ NÃO CHATGPT (DỰ PHÒNG SỐ 2) -----------------
def ask_chatgpt(prompt):
    if not OPENAI_API_KEY:
        return None, "Chưa có OPENAI_API_KEY"
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "Bạn là trợ lý thông minh, hỗ trợ nhiệt tình bằng tiếng Việt súc tích, thực tế, định dạng đẹp."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        if res.status_code == 200:
            return res.json()["choices"][0]["message"]["content"].strip(), None
        else:
            err = res.json().get("error", {}).get("message", res.text)
            return None, f"ChatGPT HTTP {res.status_code}: {err}"
    except Exception as e:
        return None, f"ChatGPT lỗi: {e}"

# ----------------- 3. BỘ NÃO GEMINI (CỨU CÁNH CUỐI CÙNG) -----------------
def ask_gemini_backup(prompt):
    raw_keys = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GEMINI_API_KEYS", "")
    api_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
    if not api_keys:
        return "❌ Tất cả các dịch vụ AI đều đang bận, vui lòng thử lại sau chốc lát!"

    models = ["gemini-3.6-flash", "gemini-3.8-flash"]
    for current_key in api_keys:
        for model_name in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={current_key}"
            headers = {"Content-Type": "application/json", "x-goog-api-key": current_key}
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=30)
                if res.status_code == 200:
                    data = res.json()
                    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    texts = [p.get("text", "") for p in parts if not p.get("thought", False)]
                    ans = "".join(texts).strip()
                    if ans:
                        return ans
            except Exception:
                continue
    return "⚠️ Cả Claude, ChatGPT và Gemini đều đang bận, bạn vui lòng gửi lại sau 10 giây nhé!"

# ----------------- HÀM TỔNG HỢP GỌI AI (HIỂN THỊ CHI TIẾT LỖI TỪNG BÊN) -----------------
def ask_ai(prompt):
    error_reports = []

    # 1. Thử gọi Claude
    if ANTHROPIC_API_KEY:
        ans, err = ask_claude(prompt)
        if ans:
            return ans
        error_reports.append(f"• Claude: {err}")
    else:
        error_reports.append("• Claude: Chưa cấu hình ANTHROPIC_API_KEY trên Render")

    # 2. Thử gọi ChatGPT (gpt-4o-mini)
    if OPENAI_API_KEY:
        ans, err = ask_chatgpt(prompt)
        if ans:
            return ans
        error_reports.append(f"• ChatGPT: {err}")
    else:
        error_reports.append("• ChatGPT: Chưa cấu hình OPENAI_API_KEY trên Render")

    # 3. Thử gọi Gemini (4 Key dự phòng)
    ans = ask_gemini_backup(prompt)
    if not ans.startswith("⚠️"):
        return ans
    error_reports.append("• Gemini: Cả 4 Key đều quá tải 503 hoặc hết hạn mức")

    return "❌ Báo cáo trạng thái các hệ thống AI:\n\n" + "\n".join(error_reports)

# ----------------- BỘ GIẢI MÃ TÀI LIỆU (EXCEL, PDF, WORD, TXT) -----------------
def extract_text_from_file(file_name, file_bytes):
    ext = os.path.splitext(file_name)[1].lower()
    text = ""
    try:
        if ext == '.xlsx':
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            rows_text = []
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                rows_text.append(f"--- Sheet: {sheet} ---")
                for row in ws.iter_rows(values_only=True):
                    non_empty = [str(cell) for cell in row if cell is not None]
                    if non_empty:
                        rows_text.append(" | ".join(non_empty))
                    if len(rows_text) > 400:
                        break
            text = "\n".join(rows_text)

        elif ext == '.pdf':
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            pages_text = []
            for page in reader.pages[:20]:
                p_text = page.extract_text()
                if p_text:
                    pages_text.append(p_text)
            text = "\n".join(pages_text)

        elif ext == '.docx':
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

        elif ext in ['.txt', '.csv']:
            text = file_bytes.decode('utf-8', errors='ignore')

        else:
            return None, f"Định dạng {ext} chưa được hỗ trợ."

    except Exception as e:
        return None, f"Lỗi đọc file: {e}"

    if not text.strip():
        return None, "File không có nội dung chữ hoặc không trích xuất được."

    if len(text) > 15000:
        text = text[:15000] + "\n...(Đã cắt bớt vì tài liệu quá dài)..."
    return text, None

# ----------------- BỘ ĐỌC LINK (DOCS, SHEETS, BÁO CHÍ) -----------------
def extract_text_from_url(url):
    try:
        if "docs.google.com/document/d/" in url:
            doc_id = url.split("/document/d/")[1].split("/")[0]
            res = requests.get(f"https://docs.google.com/document/d/{doc_id}/export?format=txt", timeout=15)
            if res.status_code == 200:
                return res.text[:15000]

        elif "docs.google.com/spreadsheets/d/" in url:
            sheet_id = url.split("/spreadsheets/d/")[1].split("/")[0]
            res = requests.get(f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv", timeout=15)
            if res.status_code == 200:
                return res.text[:15000]

        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(res.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.extract()
            text = soup.get_text(separator="\n")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            return "\n".join(lines)[:15000]
    except Exception as e:
        print(f"Lỗi đọc link: {e}")
    return None

# ----------------- GỬI TIN NHẮN AN TOÀN -----------------
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

# Máy chủ web Render giữ kết nối 24/7
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot 3-in-1 is running 24/7!")

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

# LỆNH /START
@bot.message_handler(commands=['start'])
def cmd_start(message):
    safe_send_message(message.chat.id, f"📖 *BẮT ĐẦU BÀI ĐỌC: {DEFAULT_TAB}*")
    send_sheet_step(message.chat.id, DEFAULT_TAB, 0)

# LỆNH /DOC
@bot.message_handler(commands=['doc'])
def cmd_doc(message):
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        tab_name = args[1].strip()
        safe_send_message(message.chat.id, f"📖 *BẮT ĐẦU BÀI ĐỌC: {tab_name}*")
        send_sheet_step(message.chat.id, tab_name, 0)
    else:
        safe_send_message(message.chat.id, "💡 Gõ `/doc <Tên_Tab>` để mở bài.")

# LỆNH TÓM TẮT THẢO LUẬN NHÓM
@bot.message_handler(commands=['tomtat'])
def cmd_tomtat(message):
    chat_id = message.chat.id
    history = group_history.get(chat_id)
    if not history or len(history) < 2:
        safe_send_message(chat_id, "⚠️ Nhóm chưa có đủ tin nhắn trao đổi để tóm tắt.")
        return

    bot.send_chat_action(chat_id, 'typing')
    conversation_text = "\n".join(history)
    prompt = (
        "Dưới đây là các tin nhắn gần nhất trong nhóm Telegram:\n\n"
        f"{conversation_text}\n\n"
        "Hãy đóng vai trò thư ký thông minh, tóm tắt lại bằng tiếng Việt:\n"
        "1. Các chủ đề/vấn đề chính đã trao đổi.\n"
        "2. Các quyết định/thống nhất quan trọng (nếu có).\n"
        "3. Các đầu việc cần làm (action items) kèm người phụ trách (nếu có nhắc đến)."
    )
    summary = ask_ai(prompt)
    safe_send_message(chat_id, f"📝 *BẢN TÓM TẮT THẢO LUẬN NHÓM:*\n\n{summary}")

# XỬ LÝ FILE ĐÍNH KÈM (EXCEL, PDF, WORD, TXT)
@bot.message_handler(content_types=['document'])
def handle_document_upload(message):
    chat_id = message.chat.id
    file_name = message.document.file_name
    caption = message.caption or ""

    is_in_group = message.chat.type in ['group', 'supergroup']
    is_mentioned = BOT_USERNAME and f"@{BOT_USERNAME}" in caption

    if is_in_group and not is_mentioned:
        return

    if message.document.file_size > 20 * 1024 * 1024:
        safe_send_message(chat_id, "⚠️ File quá lớn (giới hạn tối đa 20MB).")
        return

    bot.send_chat_action(chat_id, 'typing')
    safe_send_message(chat_id, f"📥 Đang tải và phân tích tài liệu *{file_name}*...")

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        content_text, err = extract_text_from_file(file_name, downloaded)

        if err:
            safe_send_message(chat_id, f"❌ {err}")
            return

        user_req = caption.replace(f"@{BOT_USERNAME}", "").strip() if caption else "Hãy tóm tắt và phân tích các ý chính quan trọng nhất trong tài liệu này."
        prompt = (
            f"Dưới đây là nội dung trích xuất từ tài liệu '{file_name}':\n\n"
            f"{content_text}\n\n"
            f"Yêu cầu của người dùng: {user_req}\n"
            "Hãy trả lời bằng tiếng Việt, rõ ràng, định dạng đẹp mắt."
        )
        ai_reply = ask_ai(prompt)
        safe_send_message(chat_id, ai_reply)

    except Exception as e:
        safe_send_message(chat_id, f"❌ Có lỗi khi đọc tài liệu: {e}")

# XỬ LÝ TIN NHẮN CHỮ & LINK
@bot.message_handler(func=lambda msg: True)
def handle_all_messages(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    text = message.text.strip() if message.text else ""
    sender = message.from_user.first_name or "Thành viên"
    username = f"@{message.from_user.username}" if message.from_user.username else "Không có"

    # Ghi nhật ký vào nhóm riêng tư
    if user_id != MY_CHAT_ID and text and LOG_CHANNEL_ID:
        if str(chat_id) != str(LOG_CHANNEL_ID):
            chat_type = "Nhóm" if message.chat.type in ['group', 'supergroup'] else "Chat riêng"
            admin_alert = (
                f"🔔 *NGƯỜI DÙNG TƯƠNG TÁC:*\n\n"
                f"• *Người gửi:* {sender} ({username})\n"
                f"• *User ID:* `{user_id}`\n"
                f"• *Nơi gửi:* {chat_type}\n"
                f"• *Nội dung:* \"_{text}_\""
            )
            try:
                bot.send_message(LOG_CHANNEL_ID, admin_alert, parse_mode="Markdown")
            except Exception as e:
                print(f"Lỗi gửi log: {e}")

    # Xử lý trong nhóm
    if message.chat.type in ['group', 'supergroup']:
        group_history[chat_id].append(f"{sender}: {text}")
        is_mentioned = BOT_USERNAME and f"@{BOT_USERNAME}" in text
        is_reply_to_bot = (
            message.reply_to_message and 
            message.reply_to_message.from_user and
            message.reply_to_message.from_user.username == BOT_USERNAME
        )
        if not (is_mentioned or is_reply_to_bot):
            return
        clean_question = text.replace(f"@{BOT_USERNAME}", "").strip() if BOT_USERNAME else text
    else:
        clean_question = text

    bot.send_chat_action(chat_id, 'typing')

    # Nhận diện nếu gửi Link
    urls = re.findall(r'(https?://[^\s]+)', clean_question)
    if urls:
        target_url = urls[0]
        url_content = extract_text_from_url(target_url)
        if url_content:
            prompt = (
                f"Người dùng gửi liên kết: {target_url}\n"
                f"Nội dung thu thập được từ liên kết này:\n\n{url_content}\n\n"
                f"Yêu cầu của người dùng: {clean_question}\n"
                "Hãy phân tích và trả lời theo yêu cầu bằng tiếng Việt."
            )
            ai_reply = ask_ai(prompt)
            safe_send_message(chat_id, ai_reply)
            return

    # Câu hỏi thông thường
    ai_reply = ask_ai(clean_question)
    safe_send_message(chat_id, ai_reply)

def daily_job():
    safe_send_message(MY_CHAT_ID, f"⏰ *21h00 rồi! Dành 3 phút nạp bài học tối nay nhé:*")
    send_sheet_step(MY_CHAT_ID, DEFAULT_TAB, 0)

def run_scheduler():
    schedule.every().day.at("21:00").do(daily_job)
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    print(f"✅ Bot Trợ lý 3-in-1 đang khởi động...")
    bot.remove_webhook()
    try:
        me = bot.get_me()
        BOT_USERNAME = me.username
        print(f"🤖 Bot Username: @{BOT_USERNAME}")
    except Exception as e:
        print(f"Lỗi: {e}")

    t_web = threading.Thread(target=run_dummy_server)
    t_web.daemon = True
    t_web.start()

    t_sched = threading.Thread(target=run_scheduler)
    t_sched.daemon = True
    t_sched.start()

    bot.infinity_polling()
