import os
import base64
import re
import threading
import asyncio
import tempfile
import time
from email.utils import parseaddr, parsedate_to_datetime

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import edge_tts
import pygame
import tkinter as tk

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
LABEL_NAME = "_親族/親父"
VOICE = "ja-JP-NanamiNeural"
FONT_LARGE = ("Meiryo UI", 22)
FONT_BUTTON = ("Meiryo UI", 20)
FONT_STATUS = ("Meiryo UI", 16)


# --- Gmail / メール処理 ---

def get_gmail_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def get_label_id(service, label_name):
    results = service.users().labels().list(userId="me").execute()
    for label in results.get("labels", []):
        if label["name"] == label_name:
            return label["id"]
    return None


def get_unread_messages_grouped(service, label_id):
    results = (
        service.users()
        .messages()
        .list(userId="me", labelIds=[label_id], q="is:unread")
        .execute()
    )
    messages = results.get("messages", [])
    threads = {}
    for msg in messages:
        tid = msg.get("threadId")
        if tid not in threads:
            threads[tid] = []
        threads[tid].append(msg)
    for tid in threads:
        threads[tid].reverse()
    return list(threads.values())


def get_message_detail(service, msg_id):
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    headers = msg["payload"]["headers"]
    subject = ""
    sender = ""
    date_str = ""
    for h in headers:
        name = h["name"].lower()
        if name == "subject":
            subject = h["value"]
        elif name == "from":
            sender = h["value"]
        elif name == "date":
            date_str = h["value"]

    date_display = ""
    if date_str:
        try:
            dt = parsedate_to_datetime(date_str)
            date_display = dt.strftime("%Y年%m月%d日 %H:%M")
        except Exception:
            date_display = date_str

    has_attachment = check_attachments(msg["payload"])
    body = extract_body(msg["payload"])
    sender_name = parseaddr(sender)[0] or sender
    return {
        "id": msg_id, "sender": sender_name, "subject": subject,
        "body": body, "date": date_display, "has_attachment": has_attachment,
    }


def check_attachments(payload):
    if payload.get("filename"):
        return True
    for part in payload.get("parts", []):
        if part.get("filename"):
            return True
        if check_attachments(part):
            return True
    return False


def extract_body(payload):
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    parts = payload.get("parts", [])
    for part in parts:
        if part["mimeType"] == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
    for part in parts:
        result = extract_body(part)
        if result:
            return result
    return ""


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
    text = re.sub(r"<[^>]+>", "", body)
    text = strip_quoted_text(text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines).strip()
    return text[:500]


def mark_as_read(service, msg_id):
    service.users().messages().modify(
        userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()


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
        self.service = None
        self.threads = []
        self.thread_index = 0
        self.msg_index = 0
        self.font_size = 26
        self._highlight_search_pos = "1.0"
        self._pending_announce = None
        self._play_gen = 0

        self._build_ui()
        self.root.after(100, self._load_emails)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        bg = "#1a1a2e"
        fg = "#e0e0e0"
        accent = "#4fc3f7"

        # 上部バー（ステータス + フォントサイズ調整）
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

        # ボタンエリア（先にpackして下部に固定）
        btn_frame = tk.Frame(self.root, bg=bg, pady=20)
        btn_frame.pack(side="bottom", fill="x")

        # メール表示エリア
        display_frame = tk.Frame(self.root, bg=bg, padx=30, pady=10)
        display_frame.pack(fill="both", expand=True)

        self.sender_var = tk.StringVar()
        self.sender_label = tk.Label(display_frame, textvariable=self.sender_var,
                                     font=("Meiryo UI", self.font_size),
                                     bg=bg, fg=accent, anchor="w", wraplength=900)
        self.sender_label.pack(fill="x", pady=(10, 2))

        self.date_var = tk.StringVar()
        self.date_label = tk.Label(display_frame, textvariable=self.date_var,
                                   font=("Meiryo UI", self.font_size - 4),
                                   bg=bg, fg="#888888", anchor="w")
        self.date_label.pack(fill="x", pady=(0, 5))

        self.subject_var = tk.StringVar()
        self.subject_label = tk.Label(display_frame, textvariable=self.subject_var,
                                      font=("Meiryo UI", self.font_size),
                                      bg=bg, fg=fg, anchor="w", wraplength=900)
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

        self.btn_prev = tk.Button(btn_frame, text="◀ 前へ", bg="#334155", fg=fg,
                                  activebackground="#475569", activeforeground="white",
                                  command=self._prev, **btn_style)
        self.btn_prev.pack(side="left", padx=15, expand=True)

        self.btn_play = tk.Button(btn_frame, text="▶ 再生", bg="#1b5e20", fg="white",
                                  activebackground="#2e7d32", activeforeground="white",
                                  command=self._play, **btn_style)
        self.btn_play.pack(side="left", padx=15, expand=True)

        self.btn_stop = tk.Button(btn_frame, text="■ 停止", bg="#b71c1c", fg="white",
                                  activebackground="#c62828", activeforeground="white",
                                  command=self._stop, **btn_style)
        self.btn_stop.pack(side="left", padx=15, expand=True)

        self.btn_repeat = tk.Button(btn_frame, text="↻ リピート", bg="#e65100", fg="white",
                                    activebackground="#ef6c00", activeforeground="white",
                                    command=self._repeat, **btn_style)
        self.btn_repeat.pack(side="left", padx=15, expand=True)

        self.btn_next = tk.Button(btn_frame, text="次へ ▶", bg="#334155", fg=fg,
                                  activebackground="#475569", activeforeground="white",
                                  command=self._next, **btn_style)
        self.btn_next.pack(side="left", padx=15, expand=True)

        self.btn_refresh = tk.Button(btn_frame, text="🔄 更新", bg="#0d47a1", fg="white",
                                     activebackground="#1565c0", activeforeground="white",
                                     command=self._refresh, **btn_style)
        self.btn_refresh.pack(side="left", padx=15, expand=True)

        self.btn_quit = tk.Button(btn_frame, text="✕ 終了", bg="#424242", fg="#e0e0e0",
                                  activebackground="#616161", activeforeground="white",
                                  command=self._on_close, **btn_style)
        self.btn_quit.pack(side="left", padx=15, expand=True)

        # タブオーダー設定
        self.btn_play.focus_set()
        for btn in [self.btn_prev, self.btn_play, self.btn_stop, self.btn_repeat, self.btn_next,
                     self.btn_refresh, self.btn_quit, self.btn_font_up, self.btn_font_down]:
            btn.bind("<Return>", lambda e, b=btn: b.invoke())
            btn.bind("<space>", lambda e, b=btn: b.invoke())

    def _load_emails(self):
        def load():
            try:
                self.service = get_gmail_service()
                label_id = get_label_id(self.service, LABEL_NAME)
                if not label_id:
                    self.root.after(0, lambda: self._show_message("ラベルが見つかりません"))
                    return
                thread_groups = get_unread_messages_grouped(self.service, label_id)
                if not thread_groups:
                    self.root.after(0, lambda: self._show_message("未読メールはありません"))
                    self.root.after(0, lambda: self.speech.speak("未読メールはありません。"))
                    return
                threads = []
                total_msgs = 0
                for group in thread_groups:
                    thread_emails = []
                    for ref in group:
                        detail = get_message_detail(self.service, ref["id"])
                        detail["body_clean"] = clean_body_for_reading(detail["body"])
                        thread_emails.append(detail)
                        total_msgs += 1
                    threads.append(thread_emails)
                self.threads = threads
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
        email = self._current_email()
        if not email:
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

        self.sender_var.set(f"差出人: {email['sender']}")
        self.date_var.set(f"日時: {email['date']}")
        self.subject_var.set(f"件名: {email['subject']}")
        if email.get("has_attachment"):
            self.attachment_var.set("📎 添付ファイルあり")
        else:
            self.attachment_var.set("")

        self.body_text.configure(state="normal")
        self.body_text.delete("1.0", "end")
        self.body_text.insert("1.0", email["body_clean"])
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
        email = self._current_email()
        if not email:
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
        parts.append(f"{email['sender']}さんから。")
        parts.append(f"件名、{email['subject']}。")
        if email.get("has_attachment"):
            parts.append("添付ファイルがあります。いつものメール画面でメールを開いて確認してください。")
        parts.append(email["body_clean"])
        speech_text = "".join(parts)
        self._play_gen += 1
        gen = self._play_gen
        self.speech.speak(speech_text, on_done=lambda: self.root.after(0, self._auto_next, gen))

    def _stop(self):
        self.speech.stop()
        self._clear_highlight()

    def _repeat(self):
        self._play()

    def _advance(self):
        thread = self._current_thread()
        mark_as_read(self.service, self._current_email()["id"])
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
            mark_as_read(self.service, self._current_email()["id"])
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
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = MailReaderApp(root)
    root.mainloop()
