import os
import base64
import re
from email.utils import parseaddr

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import re
import pyttsx3

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
LABEL_NAME = "_親族/親父"


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


def get_unread_messages(service, label_id):
    results = (
        service.users()
        .messages()
        .list(userId="me", labelIds=[label_id], q="is:unread")
        .execute()
    )
    return results.get("messages", [])


def get_message_detail(service, msg_id):
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    headers = msg["payload"]["headers"]

    subject = ""
    sender = ""
    for h in headers:
        if h["name"].lower() == "subject":
            subject = h["value"]
        elif h["name"].lower() == "from":
            sender = h["value"]

    body = extract_body(msg["payload"])
    sender_name = parseaddr(sender)[0] or sender

    return {"id": msg_id, "sender": sender_name, "subject": subject, "body": body}


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
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500]


def speak(text):
    engine = pyttsx3.init()
    engine.setProperty("rate", 150)
    voices = engine.getProperty("voices")
    for voice in voices:
        if "japanese" in voice.name.lower() or "haruka" in voice.name.lower():
            engine.setProperty("voice", voice.id)
            break
    engine.say(text)
    engine.runAndWait()


def mark_as_read(service, msg_id):
    service.users().messages().modify(
        userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()


def main():
    print("メール読み上げアプリを起動しています...")

    service = get_gmail_service()
    label_id = get_label_id(service, LABEL_NAME)

    if not label_id:
        print(f"ラベル「{LABEL_NAME}」が見つかりません。Gmailでラベルを作成してください。")
        return

    messages = get_unread_messages(service, label_id)

    if not messages:
        announcement = "未読メールはありません。"
        print(announcement)
        speak(announcement)
        return

    print(f"{len(messages)}件の未読メールがあります。")
    speak(f"{len(messages)}件の未読メールがあります。読み上げを開始します。")

    for i, msg_ref in enumerate(messages, 1):
        detail = get_message_detail(service, msg_ref["id"])
        print(f"\n--- メール {i}/{len(messages)} ---")
        print(f"送信者: {detail['sender']}")
        print(f"件名: {detail['subject']}")

        intro = f"{i}通目。{detail['sender']}さんから。件名、{detail['subject']}。"
        speak(intro)

        body_text = clean_body_for_reading(detail["body"])
        print(f"本文: {body_text}")
        speak(body_text)

        mark_as_read(service, detail["id"])

    speak("以上で全てのメールの読み上げが完了しました。")
    print("\n読み上げ完了。")


if __name__ == "__main__":
    main()
