import os
import imaplib
import email
import email.header
import smtplib
import re
import threading
import asyncio
import tempfile
import time
from datetime import datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
from email.mime.text import MIMEText

from dotenv import load_dotenv
import anthropic
import edge_tts
import pygame
import tkinter as tk

load_dotenv()

IMAP_SERVER = "mail.biglobe.ne.jp"
IMAP_PORT = 993
SMTP_SERVER = "mail.biglobe.ne.jp"
SMTP_PORT = 465
BIGLOBE_EMAIL = os.getenv("BIGLOBE_EMAIL", "")
BIGLOBE_PASSWORD = os.getenv("BIGLOBE_PASSWORD", "")
DRY_RUN = True

CASUAL_CONTACTS = [
    name.strip() for name in os.getenv("CASUAL_CONTACTS", "").split(",") if name.strip()
]

VOICE = "ja-JP-NanamiNeural"
FONT_LARGE = ("Meiryo UI", 22)
FONT_BUTTON = ("Meiryo UI", 20)
FONT_STATUS = ("Meiryo UI", 16)


# --- IMAP / メール処理 ---

def decode_header_value(value):
    if not value:
        return ""
    decoded_parts = email.header.decode_header(value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def connect_imap():
    conn = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    conn.login(BIGLOBE_EMAIL, BIGLOBE_PASSWORD)
    return conn


def get_unread_messages(conn, days=30):
    conn.select("INBOX")
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    _, data = conn.search(None, f"UNSEEN SINCE {since}")
    msg_ids = data[0].split()
    return msg_ids


def get_message_detail(conn, msg_id):
    _, data = conn.fetch(msg_id, "(BODY.PEEK[])")
    raw = data[0][1]
    msg = email.message_from_bytes(raw)

    subject = decode_header_value(msg.get("Subject", ""))
    sender_raw = decode_header_value(msg.get("From", ""))
    date_str = msg.get("Date", "")
    message_id = msg.get("Message-ID", "")

    sender_name = parseaddr(sender_raw)[0] or sender_raw
    sender_email = parseaddr(sender_raw)[1]

    date_display = ""
    if date_str:
        try:
            dt = parsedate_to_datetime(date_str)
            date_display = dt.strftime("%Y年%m月%d日 %H:%M")
        except Exception:
            date_display = date_str

    has_attachment = False
    body = ""
    for part in msg.walk():
        content_disposition = str(part.get("Content-Disposition", ""))
        if "attachment" in content_disposition:
            has_attachment = True
            continue
        if part.get_content_type() == "text/plain" and not body:
            charset = part.get_content_charset() or "utf-8"
            payload = part.get_payload(decode=True)
            if payload:
                body = payload.decode(charset, errors="replace")

    if not body:
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode(charset, errors="replace")
                    break

    return {
        "uid": msg_id,
        "sender": sender_name,
        "sender_email": sender_email,
        "message_id": message_id,
        "subject": subject,
        "body": body,
        "date": date_display,
        "has_attachment": has_attachment,
    }


def download_and_open_attachments(conn, msg_id):
    _, data = conn.fetch(msg_id, "(BODY.PEEK[])")
    raw = data[0][1]
    msg = email.message_from_bytes(raw)
    opened = 0
    for part in msg.walk():
        content_disposition = str(part.get("Content-Disposition", ""))
        if "attachment" not in content_disposition:
            continue
        filename = part.get_filename()
        if filename:
            filename = decode_header_value(filename)
        if not filename:
            continue
        if filename.lower() in ("winmail.dat", "smime.p7s"):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        tmp_dir = os.path.join(tempfile.gettempdir(), "mail_reader_attachments")
        os.makedirs(tmp_dir, exist_ok=True)
        filepath = os.path.join(tmp_dir, filename)
        with open(filepath, "wb") as f:
            f.write(payload)
        os.startfile(filepath)
        opened += 1
    return opened


def normalize_subject(subject):
    return re.sub(r"^(Re:\s*|Fwd?:\s*|転送:\s*)+", "", subject, flags=re.IGNORECASE).strip()


def group_by_thread(details):
    threads = {}
    for d in details:
        key = normalize_subject(d["subject"])
        if key not in threads:
            threads[key] = []
        threads[key].append(d)
    return list(threads.values())


def get_past_emails(conn, sender_email, limit=5):
    conn.select("INBOX")
    _, data = conn.search(None, f'FROM "{sender_email}"')
    msg_ids = data[0].split() if data[0] else []
    msg_ids = msg_ids[-limit:]
    results = []
    for mid in msg_ids:
        _, msg_data = conn.fetch(mid, "(BODY.PEEK[])")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        subject = decode_header_value(msg.get("Subject", ""))
        date_str = msg.get("Date", "")
        sender_raw = decode_header_value(msg.get("From", ""))
        sender_name = parseaddr(sender_raw)[0] or sender_raw
        body = ""
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not body:
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode(charset, errors="replace")
        if not body:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    charset = part.get_content_charset() or "utf-8"
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode(charset, errors="replace")
                    break
        results.append({
            "sender": sender_name,
            "subject": subject,
            "date": date_str,
            "body": clean_body_for_reading(body)[:1000],
        })
    return results


def mark_as_read(conn, msg_id):
    conn.store(msg_id, "+FLAGS", "\\Seen")


def strip_quoted_text(text):
    lines = text.split("\n")
    result = []
    for line in lines:
        if line.strip().startswith(">"):
            continue
        if re.match(r"^-{5,}\s*(Forwarded|Original|転送)", line):
            break
        if re.match(r"^\d{4}年\d{1,2}月\d{1,2}日.*[:：]$", line.strip()):
            break
        if re.match(r"^On .+ wrote:$", line.strip()):
            break
        if re.match(r"^(送信者|From|差出人)\s*[:：]", line.strip()):
            break
        result.append(line)
    return "\n".join(result)


def clean_body_for_reading(body):
    text = re.sub(r"<style[^>]*>.*?</style>", "", body, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#\d+;", "", text)
    text = re.sub(r"&\w+;", "", text)
    text = strip_quoted_text(text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines).strip()
    return text[:10000]


# --- SMTP送信 ---

def send_reply(to_addr, subject, body, in_reply_to=""):
    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = BIGLOBE_EMAIL
    msg["To"] = to_addr
    msg["Subject"] = reply_subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(BIGLOBE_EMAIL, BIGLOBE_PASSWORD)
        server.send_message(msg)


# --- AI返信生成 ---

def is_casual_contact(sender_name):
    for name in CASUAL_CONTACTS:
        if name in sender_name:
            return True
    return False


REPLY_DIRECTIONS = {
    "accept": "相手の提案・依頼を承諾・了承する方向で返信してください。「問題ありません」「進めてください」のようなニュアンスで。",
    "decline": "相手の提案・依頼をやんわり辞退・見送る方向で返信してください。「今回は見送らせていただきます」のようなニュアンスで。",
    "hold": "保留・検討中であることを伝える方向で返信してください。「確認して後日ご連絡します」のようなニュアンスで。",
    "auto": "メールの内容に応じて、最も適切な返信を書いてください。",
}


def generate_reply(sender, subject, body_clean, casual=False, direction="auto", past_emails=None):
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    tone = (
        "親しい友人や家族に書くようなくだけた口調（「〜だよ」「ありがとう」「よろしくね」など）"
        if casual else
        "一般的な丁寧語（「〜です」「〜します」「よろしくお願いします」など）"
    )
    direction_instruction = REPLY_DIRECTIONS.get(direction, REPLY_DIRECTIONS["auto"])

    history_section = ""
    if past_emails:
        history_parts = []
        for pe in past_emails:
            history_parts.append(f"日時: {pe['date']}\n差出人: {pe['sender']}\n件名: {pe['subject']}\n本文:\n{pe['body']}")
        history_section = "\n【過去のやり取り（古い順）】\n" + "\n---\n".join(history_parts) + "\n"

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": f"""以下のメールへの返信を書いてください。
{history_section}
【今回のメール】
差出人: {sender}
件名: {subject}
本文:
{body_clean}

【方向性】
{direction_instruction}

【条件】
- 返信者は80歳の日本人男性です
- {tone}で書いてください
- 過去のやり取りの文脈を踏まえて、自然な返信を書いてください
- 簡潔に、要点だけ返してください
- 挨拶文と署名は不要です
- メール本文のみを出力してください（件名やヘッダーは不要）
- 300文字以内で収めてください
"""
        }],
    )
    return response.content[0].text.strip()


# --- 音声エンジン（edge-tts + pygame + ハイライト） ---

class SpeechEngine:
    def __init__(self):
        self._stop_flag = threading.Event()
        self._thread = None
        self._generation = 0
        self._highlight_callback = None
        self._highlight_done_callback = None
        pygame.mixer.init()

    async def _synthesize(self, text):
        communicate = edge_tts.Communicate(text, VOICE)
        audio_file = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        audio_path = audio_file.name
        audio_file.close()

        sentence_events = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                with open(audio_path, "ab") as f:
                    f.write(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                sentence_events.append({
                    "offset": chunk["offset"] / 10_000_000,
                    "text": chunk["text"],
                })

        return audio_path, sentence_events

    def _run(self, text, on_done=None, gen=0):
        audio_path = None
        try:
            loop = asyncio.new_event_loop()
            audio_path, sentence_events = loop.run_until_complete(self._synthesize(text))
            loop.close()

            if self._stop_flag.is_set() or gen != self._generation:
                os.unlink(audio_path)
                return

            pygame.mixer.music.load(audio_path)
            pygame.mixer.music.play()
            start_time = time.time()

            event_idx = 0
            while pygame.mixer.music.get_busy():
                if self._stop_flag.is_set() or gen != self._generation:
                    pygame.mixer.music.stop()
                    break
                elapsed = time.time() - start_time
                while event_idx < len(sentence_events) and sentence_events[event_idx]["offset"] <= elapsed:
                    sentence = sentence_events[event_idx]["text"]
                    if self._highlight_callback:
                        self._highlight_callback(sentence)
                    event_idx += 1
                time.sleep(0.05)

            pygame.mixer.music.unload()
        except Exception:
            pass
        finally:
            if audio_path and os.path.exists(audio_path):
                try:
                    os.unlink(audio_path)
                except OSError:
                    pass

        if gen != self._generation:
            return
        if self._highlight_done_callback:
            self._highlight_done_callback()
        if on_done and not self._stop_flag.is_set():
            on_done()

    def speak(self, text, on_done=None):
        self.stop()
        self._stop_flag.clear()
        self._generation += 1
        self._thread = threading.Thread(target=self._run, args=(text, on_done, self._generation), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_flag.set()
        pygame.mixer.music.stop()

    def set_highlight_callback(self, callback, done_callback=None):
        self._highlight_callback = callback
        self._highlight_done_callback = done_callback


# --- GUI ---

class MailReaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("メール読み上げ")
        self.root.configure(bg="#1a1a2e")
        self.root.state("zoomed")

        self.speech = SpeechEngine()
        self.speech.set_highlight_callback(
            lambda sentence: self.root.after(0, self._highlight_sentence, sentence),
            lambda: self.root.after(0, self._clear_highlight),
        )
        self.conn = None
        self.threads = []
        self.thread_index = 0
        self.msg_index = 0
        self.font_size = 26
        self._highlight_search_pos = "1.0"
        self._pending_announce = None
        self._play_gen = 0
        self._draft_text = ""
        self._reply_direction = "auto"

        self._build_ui()
        self.root.after(100, self._load_emails)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        bg = "#1a1a2e"
        fg = "#e0e0e0"
        accent = "#4fc3f7"

        top_frame = tk.Frame(self.root, bg=bg)
        top_frame.pack(fill="x")

        self.status_var = tk.StringVar(value="読み込み中...")
        status = tk.Label(top_frame, textvariable=self.status_var, font=FONT_STATUS,
                          bg=bg, fg="#aaaaaa", anchor="w", padx=20, pady=10)
        status.pack(side="left", fill="x", expand=True)

        font_btn_style = dict(font=("Meiryo UI", 14), width=4, height=1, relief="flat", cursor="hand2")
        self.btn_font_down = tk.Button(top_frame, text="A-", bg="#334155", fg=fg,
                                       activebackground="#475569", activeforeground="white",
                                       command=self._font_smaller, **font_btn_style)
        self.btn_font_down.pack(side="right", padx=(0, 10), pady=5)
        self.btn_font_up = tk.Button(top_frame, text="A+", bg="#334155", fg=fg,
                                     activebackground="#475569", activeforeground="white",
                                     command=self._font_larger, **font_btn_style)
        self.btn_font_up.pack(side="right", padx=(0, 5), pady=5)

        # メール操作ボタン
        self.mail_btn_frame = tk.Frame(self.root, bg=bg, pady=20)
        self.mail_btn_frame.pack(side="bottom", fill="x")

        # 返信方向性選択ボタン（初期非表示）
        self.direction_btn_frame = tk.Frame(self.root, bg=bg, pady=20)

        # 返信操作ボタン（初期非表示）
        self.reply_btn_frame = tk.Frame(self.root, bg=bg, pady=20)

        display_frame = tk.Frame(self.root, bg=bg, padx=30, pady=10)
        display_frame.pack(fill="both", expand=True)

        self.sender_var = tk.StringVar()
        self.sender_label = tk.Label(display_frame, textvariable=self.sender_var,
                                     font=("Meiryo UI", self.font_size),
                                     bg=bg, fg=accent, anchor="w", justify="left", wraplength=900)
        self.sender_label.pack(fill="x", pady=(10, 2))

        self.date_var = tk.StringVar()
        self.date_label = tk.Label(display_frame, textvariable=self.date_var,
                                   font=("Meiryo UI", self.font_size - 4),
                                   bg=bg, fg="#888888", anchor="w")
        self.date_label.pack(fill="x", pady=(0, 5))

        self.subject_var = tk.StringVar()
        self.subject_label = tk.Label(display_frame, textvariable=self.subject_var,
                                      font=("Meiryo UI", self.font_size),
                                      bg=bg, fg=fg, anchor="w", justify="left", wraplength=900)
        self.subject_label.pack(fill="x", pady=(0, 2))

        self.attachment_var = tk.StringVar()
        self.attachment_label = tk.Label(display_frame, textvariable=self.attachment_var,
                                         font=("Meiryo UI", self.font_size - 4),
                                         bg=bg, fg="#ff8a65", anchor="w")
        self.attachment_label.pack(fill="x", pady=(0, 10))

        self.body_text = tk.Text(display_frame, font=("Meiryo UI", self.font_size - 2),
                                 bg="#16213e", fg=fg, wrap="word", relief="flat",
                                 padx=20, pady=15, state="disabled", cursor="arrow", height=10)
        self.body_text.tag_configure("highlight", background="#f9a825", foreground="#1a1a2e")
        self.body_text.pack(fill="both", expand=True)

        btn_style = dict(font=FONT_BUTTON, width=12, height=2, relief="flat", cursor="hand2")

        # --- メール画面ボタン ---
        self.btn_play = tk.Button(self.mail_btn_frame, text="▶ 再生", bg="#1b5e20", fg="white",
                                  activebackground="#2e7d32", activeforeground="white",
                                  command=self._play, **btn_style)
        self.btn_play.pack(side="left", padx=15, expand=True)

        self.btn_stop = tk.Button(self.mail_btn_frame, text="■ 停止", bg="#b71c1c", fg="white",
                                  activebackground="#c62828", activeforeground="white",
                                  command=self._stop, **btn_style)
        self.btn_stop.pack(side="left", padx=15, expand=True)

        self.btn_prev = tk.Button(self.mail_btn_frame, text="⏪ 前へ", bg="#334155", fg=fg,
                                  activebackground="#475569", activeforeground="white",
                                  command=self._prev, **btn_style)
        self.btn_prev.pack(side="left", padx=15, expand=True)

        self.btn_repeat = tk.Button(self.mail_btn_frame, text="↻ 聞き直す", bg="#e65100", fg="white",
                                    activebackground="#ef6c00", activeforeground="white",
                                    command=self._repeat, **btn_style)
        self.btn_repeat.pack(side="left", padx=15, expand=True)

        self.btn_next = tk.Button(self.mail_btn_frame, text="次へ ⏩", bg="#334155", fg=fg,
                                  activebackground="#475569", activeforeground="white",
                                  command=self._next, **btn_style)
        self.btn_next.pack(side="left", padx=15, expand=True)

        self.btn_attachment = tk.Button(self.mail_btn_frame, text="📎 添付を開く", bg="#795548", fg="white",
                                       activebackground="#8d6e63", activeforeground="white",
                                       command=self._open_attachments, **btn_style)

        self.btn_reply = tk.Button(self.mail_btn_frame, text="✉ 返信", bg="#6a1b9a", fg="white",
                                   activebackground="#7b1fa2", activeforeground="white",
                                   command=self._start_reply, **btn_style)
        self.btn_reply.pack(side="left", padx=15, expand=True)

        self.btn_refresh = tk.Button(self.mail_btn_frame, text="🔄 更新", bg="#0d47a1", fg="white",
                                     activebackground="#1565c0", activeforeground="white",
                                     command=self._refresh, **btn_style)
        self.btn_refresh.pack(side="left", padx=15, expand=True)

        self.btn_quit = tk.Button(self.mail_btn_frame, text="✕ 終了", bg="#424242", fg="#e0e0e0",
                                  activebackground="#616161", activeforeground="white",
                                  command=self._on_close, **btn_style)
        self.btn_quit.pack(side="left", padx=15, expand=True)

        # --- 方向性選択ボタン ---
        self.btn_accept = tk.Button(self.direction_btn_frame, text="👍 承諾", bg="#1b5e20", fg="white",
                                    activebackground="#2e7d32", activeforeground="white",
                                    command=lambda: self._pick_direction("accept"), **btn_style)
        self.btn_accept.pack(side="left", padx=15, expand=True)

        self.btn_decline = tk.Button(self.direction_btn_frame, text="👎 辞退", bg="#b71c1c", fg="white",
                                     activebackground="#c62828", activeforeground="white",
                                     command=lambda: self._pick_direction("decline"), **btn_style)
        self.btn_decline.pack(side="left", padx=15, expand=True)

        self.btn_hold = tk.Button(self.direction_btn_frame, text="⏳ 保留", bg="#e65100", fg="white",
                                  activebackground="#ef6c00", activeforeground="white",
                                  command=lambda: self._pick_direction("hold"), **btn_style)
        self.btn_hold.pack(side="left", padx=15, expand=True)

        self.btn_auto = tk.Button(self.direction_btn_frame, text="✨ おまかせ", bg="#6a1b9a", fg="white",
                                  activebackground="#7b1fa2", activeforeground="white",
                                  command=lambda: self._pick_direction("auto"), **btn_style)
        self.btn_auto.pack(side="left", padx=15, expand=True)

        self.btn_cancel_direction = tk.Button(self.direction_btn_frame, text="← 戻る", bg="#424242", fg="#e0e0e0",
                                              activebackground="#616161", activeforeground="white",
                                              command=self._cancel_reply, **btn_style)
        self.btn_cancel_direction.pack(side="left", padx=15, expand=True)

        # --- 返信画面ボタン ---
        self.btn_send = tk.Button(self.reply_btn_frame, text="📤 送信", bg="#1b5e20", fg="white",
                                  activebackground="#2e7d32", activeforeground="white",
                                  command=self._send_reply, **btn_style)
        self.btn_send.pack(side="left", padx=15, expand=True)

        self.btn_read_draft = tk.Button(self.reply_btn_frame, text="▶ 読み上げ", bg="#0d47a1", fg="white",
                                        activebackground="#1565c0", activeforeground="white",
                                        command=self._read_draft, **btn_style)
        self.btn_read_draft.pack(side="left", padx=15, expand=True)

        self.btn_retry = tk.Button(self.reply_btn_frame, text="↻ やり直す", bg="#e65100", fg="white",
                                   activebackground="#ef6c00", activeforeground="white",
                                   command=self._retry_reply, **btn_style)
        self.btn_retry.pack(side="left", padx=15, expand=True)

        self.btn_cancel_reply = tk.Button(self.reply_btn_frame, text="← 戻る", bg="#424242", fg="#e0e0e0",
                                          activebackground="#616161", activeforeground="white",
                                          command=self._cancel_reply, **btn_style)
        self.btn_cancel_reply.pack(side="left", padx=15, expand=True)

        self.btn_play.focus_set()
        all_btns = [self.btn_play, self.btn_stop, self.btn_prev, self.btn_repeat, self.btn_next,
                     self.btn_attachment, self.btn_reply, self.btn_refresh, self.btn_quit,
                     self.btn_font_up, self.btn_font_down,
                     self.btn_accept, self.btn_decline, self.btn_hold, self.btn_auto, self.btn_cancel_direction,
                     self.btn_send, self.btn_read_draft, self.btn_retry, self.btn_cancel_reply]
        for btn in all_btns:
            btn.bind("<Return>", lambda e, b=btn: b.invoke())
            btn.bind("<space>", lambda e, b=btn: b.invoke())

    def _show_mail_buttons(self):
        self.direction_btn_frame.pack_forget()
        self.reply_btn_frame.pack_forget()
        self.mail_btn_frame.pack(side="bottom", fill="x")

    def _show_direction_buttons(self):
        self.mail_btn_frame.pack_forget()
        self.reply_btn_frame.pack_forget()
        self.direction_btn_frame.pack(side="bottom", fill="x")

    def _show_reply_buttons(self):
        self.mail_btn_frame.pack_forget()
        self.direction_btn_frame.pack_forget()
        self.reply_btn_frame.pack(side="bottom", fill="x")

    def _load_emails(self):
        def load():
            try:
                self.conn = connect_imap()
                msg_ids = get_unread_messages(self.conn)
                if not msg_ids:
                    self.root.after(0, lambda: self._show_message("未読メールはありません"))
                    self.root.after(0, lambda: self.speech.speak("未読メールはありません。"))
                    return
                details = []
                for mid in msg_ids:
                    detail = get_message_detail(self.conn, mid)
                    detail["body_clean"] = clean_body_for_reading(detail["body"])
                    details.append(detail)
                threads = group_by_thread(details)
                self.threads = threads
                total_msgs = sum(len(t) for t in threads)
                n_threads = len(threads)
                self._pending_announce = f"{n_threads}件のスレッドに{total_msgs}件の未読メールがあります。"
                self.root.after(0, self._show_current)
                self.root.after(0, self._play)
            except Exception as e:
                self.root.after(0, lambda: self._show_message(f"エラー: {e}"))

        threading.Thread(target=load, daemon=True).start()

    def _show_message(self, msg):
        self.status_var.set(msg)
        self.sender_var.set("")
        self.date_var.set("")
        self.subject_var.set("")
        self.attachment_var.set("")
        self.body_text.configure(state="normal")
        self.body_text.delete("1.0", "end")
        self.body_text.insert("1.0", msg)
        self.body_text.configure(state="disabled")

    def _current_email(self):
        if not self.threads:
            return None
        return self.threads[self.thread_index][self.msg_index]

    def _current_thread(self):
        if not self.threads:
            return []
        return self.threads[self.thread_index]

    def _show_current(self):
        email_data = self._current_email()
        if not email_data:
            return
        thread = self._current_thread()
        t_total = len(self.threads)
        t_idx = self.thread_index + 1
        m_total = len(thread)
        m_idx = self.msg_index + 1

        if m_total == 1:
            self.status_var.set(f"スレッド {t_idx}/{t_total}")
        else:
            self.status_var.set(f"スレッド {t_idx}/{t_total} — メール {m_idx}/{m_total}")

        self.sender_var.set(f"差出人: {email_data['sender']}")
        self.date_var.set(f"日時: {email_data['date']}")
        self.subject_var.set(f"件名: {email_data['subject']}")
        if email_data.get("has_attachment"):
            self.attachment_var.set("📎 添付ファイルあり")
            self.btn_attachment.pack(side="left", padx=15, expand=True, before=self.btn_reply)
        else:
            self.attachment_var.set("")
            self.btn_attachment.pack_forget()

        self.body_text.configure(state="normal")
        self.body_text.delete("1.0", "end")
        self.body_text.insert("1.0", email_data["body_clean"])
        self.body_text.configure(state="disabled")

    def _highlight_sentence(self, sentence):
        self.body_text.tag_remove("highlight", "1.0", "end")
        clean = sentence.strip()
        if not clean:
            return
        pos = self.body_text.search(clean, self._highlight_search_pos, stopindex="end")
        if not pos:
            pos = self.body_text.search(clean, "1.0", stopindex="end")
        if pos:
            end_pos = f"{pos}+{len(clean)}c"
            self.body_text.tag_add("highlight", pos, end_pos)
            self.body_text.see(pos)
            self._highlight_search_pos = end_pos

    def _clear_highlight(self):
        self.body_text.tag_remove("highlight", "1.0", "end")
        self._highlight_search_pos = "1.0"

    def _font_larger(self):
        self.font_size = min(self.font_size + 4, 48)
        self._apply_font_size()

    def _font_smaller(self):
        self.font_size = max(self.font_size - 4, 14)
        self._apply_font_size()

    def _apply_font_size(self):
        self.sender_label.configure(font=("Meiryo UI", self.font_size))
        self.date_label.configure(font=("Meiryo UI", self.font_size - 4))
        self.subject_label.configure(font=("Meiryo UI", self.font_size))
        self.attachment_label.configure(font=("Meiryo UI", self.font_size - 4))
        self.body_text.configure(font=("Meiryo UI", self.font_size - 2))

    def _play(self):
        email_data = self._current_email()
        if not email_data:
            return
        thread = self._current_thread()
        self._highlight_search_pos = "1.0"
        self._clear_highlight()

        parts = []
        if self._pending_announce:
            parts.append(self._pending_announce)
            self._pending_announce = None
        if self.msg_index == 0:
            if len(thread) > 1:
                parts.append(f"スレッド{self.thread_index + 1}。{len(thread)}件の新着があります。")
            else:
                parts.append(f"スレッド{self.thread_index + 1}。")
        parts.append(f"{email_data['sender']}さんから。")
        parts.append(f"件名、{email_data['subject']}。")
        if email_data.get("has_attachment"):
            parts.append("添付ファイルがあります。いつものメール画面でメールを開いて確認してください。")
        parts.append(email_data["body_clean"])
        speech_text = "".join(parts)
        self._play_gen += 1
        gen = self._play_gen
        self.speech.speak(speech_text, on_done=lambda: self.root.after(0, self._auto_next, gen))

    def _stop(self):
        self.speech.stop()
        self._clear_highlight()

    def _repeat(self):
        self._play()

    def _open_attachments(self):
        email_data = self._current_email()
        if not email_data or not self.conn:
            return
        self.speech.stop()
        self.speech.speak("添付ファイルを開いています。")

        def do_open():
            try:
                count = download_and_open_attachments(self.conn, email_data["uid"])
                if count == 0:
                    self.root.after(0, lambda: self.speech.speak("添付ファイルが見つかりませんでした。"))
                else:
                    msg = f"{count}件の添付ファイルを開きました。"
                    self.root.after(0, lambda: self.speech.speak(msg))
            except Exception as e:
                err_msg = f"添付ファイルエラー: {e}"
                self.root.after(0, lambda: self.speech.speak(err_msg))

        threading.Thread(target=do_open, daemon=True).start()

    def _advance(self):
        thread = self._current_thread()
        current = self._current_email()
        if current and self.conn and not DRY_RUN:
            try:
                mark_as_read(self.conn, current["uid"])
            except Exception:
                pass
        if self.msg_index < len(thread) - 1:
            self.msg_index += 1
            return True
        elif self.thread_index < len(self.threads) - 1:
            self.thread_index += 1
            self.msg_index = 0
            return True
        return False

    def _go_back(self):
        if self.msg_index > 0:
            self.msg_index -= 1
            return True
        elif self.thread_index > 0:
            self.thread_index -= 1
            self.msg_index = len(self.threads[self.thread_index]) - 1
            return True
        return False

    def _next(self):
        if not self.threads:
            return
        self.speech.stop()
        if self._advance():
            self._show_current()
            self._play()
        else:
            current = self._current_email()
            if current and self.conn and not DRY_RUN:
                try:
                    mark_as_read(self.conn, current["uid"])
                except Exception:
                    pass
            self.speech.speak("全てのメールを読み終わりました。")
            self.status_var.set("全て読み終わりました")

    def _prev(self):
        if not self.threads:
            return
        self.speech.stop()
        if self._go_back():
            self._show_current()
            self._play()

    def _auto_next(self, gen):
        if gen != self._play_gen:
            return
        if self._advance():
            self._show_current()
            self._play()
        else:
            self.speech.speak("全てのメールを読み終わりました。")
            self.status_var.set("全て読み終わりました")

    # --- 返信機能 ---

    def _start_reply(self):
        email_data = self._current_email()
        if not email_data:
            return
        self.speech.stop()
        self._show_direction_buttons()
        self.status_var.set("返信の方向性を選んでください")
        self.body_text.configure(state="normal")
        self.body_text.delete("1.0", "end")
        self.body_text.insert("1.0", "返信の方向性を選んでください。\n\n"
                              "👍 承諾 — 問題ありません、進めてください\n"
                              "👎 辞退 — 今回は見送ります\n"
                              "⏳ 保留 — 確認して後日連絡します\n"
                              "✨ おまかせ — AIにおまかせ")
        self.body_text.configure(state="disabled")
        self.speech.speak("返信の方向性を選んでください。承諾、辞退、保留、おまかせ、から選べます。")

    def _pick_direction(self, direction):
        self._reply_direction = direction
        self._show_reply_buttons()
        self.status_var.set("返信の下書きを作成中...")
        self.body_text.configure(state="normal")
        self.body_text.delete("1.0", "end")
        self.body_text.insert("1.0", "返信を考えています...")
        self.body_text.configure(state="disabled")
        self.speech.speak("返信を考えています。少々お待ちください。")
        threading.Thread(target=self._generate_draft, daemon=True).start()

    def _generate_draft(self):
        email_data = self._current_email()
        try:
            past = []
            if self.conn and email_data.get("sender_email"):
                try:
                    past = get_past_emails(self.conn, email_data["sender_email"])
                except Exception:
                    pass
            casual = is_casual_contact(email_data["sender"])
            draft = generate_reply(
                email_data["sender"],
                email_data["subject"],
                email_data["body_clean"],
                casual=casual,
                direction=self._reply_direction,
                past_emails=past,
            )
            self._draft_text = draft
            self.root.after(0, self._show_draft)
        except Exception as e:
            err_msg = f"AI生成エラー: {e}"
            self.root.after(0, lambda: self._show_message(err_msg))

    def _show_draft(self):
        email_data = self._current_email()
        self.status_var.set(f"返信の下書き → {email_data['sender']}（編集できます）")
        self.body_text.configure(state="normal", cursor="xterm", insertbackground="#f9a825", insertwidth=3)
        self.body_text.delete("1.0", "end")
        self.body_text.insert("1.0", self._draft_text)
        self.body_text.focus_set()
        self.speech.speak(f"下書きを読み上げます。{self._draft_text}")

    def _read_draft(self):
        current_text = self.body_text.get("1.0", "end").strip()
        if current_text:
            self.speech.speak(current_text)

    def _retry_reply(self):
        self.speech.stop()
        self.status_var.set("返信を再作成中...")
        self.body_text.configure(state="normal")
        self.body_text.delete("1.0", "end")
        self.body_text.insert("1.0", "返信を考え直しています...")
        self.body_text.configure(state="disabled")
        self.speech.speak("返信を考え直しています。")
        threading.Thread(target=self._generate_draft, daemon=True).start()

    def _send_reply(self):
        email_data = self._current_email()
        self._draft_text = self.body_text.get("1.0", "end").strip()
        if not email_data or not self._draft_text:
            return
        if DRY_RUN:
            self.speech.speak("テストモードのため送信をスキップしました。")
            self.status_var.set("テストモード: 送信スキップ")
            return
        self.speech.stop()
        self.status_var.set("送信中...")

        def do_send():
            try:
                send_reply(
                    email_data["sender_email"],
                    email_data["subject"],
                    self._draft_text,
                    in_reply_to=email_data.get("message_id", ""),
                )
                self.root.after(0, self._on_send_success)
            except Exception as e:
                self.root.after(0, lambda: self._show_message(f"送信エラー: {e}"))

        threading.Thread(target=do_send, daemon=True).start()

    def _on_send_success(self):
        self.speech.speak("送信しました。")
        self.status_var.set("送信完了")
        self.root.after(2000, self._cancel_reply)

    def _cancel_reply(self):
        self.speech.stop()
        self._draft_text = ""
        self.body_text.configure(state="disabled")
        self._show_mail_buttons()
        self._show_current()

    # --- その他 ---

    def _refresh(self):
        self.speech.stop()
        self.threads = []
        self.thread_index = 0
        self.msg_index = 0
        self._show_message("メールを確認中...")
        self.speech.speak("メールを確認しています。")
        self._load_emails()

    def _on_close(self):
        self.speech.stop()
        pygame.mixer.quit()
        if self.conn:
            try:
                self.conn.logout()
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = MailReaderApp(root)
    root.mainloop()
