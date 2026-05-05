class MailReaderUI {
  constructor(speech, gmail) {
    this.speech = speech;
    this.gmail = gmail;
    this.threads = [];
    this.threadIndex = 0;
    this.msgIndex = 0;
    this.fontSize = 26;
    this.pendingAnnounce = null;
    this.playGen = 0;

    this.els = {
      authScreen: document.getElementById("auth-screen"),
      mainScreen: document.getElementById("main-screen"),
      status: document.getElementById("status"),
      sender: document.getElementById("sender"),
      date: document.getElementById("date"),
      subject: document.getElementById("subject"),
      attachment: document.getElementById("attachment"),
      body: document.getElementById("body"),
    };

    this.speech.onSentenceStart = (text) => this._highlightSentence(text);
    this._applyFontSize();
  }

  showAuthScreen() {
    this.els.authScreen.hidden = false;
    this.els.mainScreen.hidden = true;
  }

  showMainScreen() {
    this.els.authScreen.hidden = true;
    this.els.mainScreen.hidden = false;
  }

  showMessage(msg) {
    this.els.status.textContent = msg;
    this.els.sender.textContent = "";
    this.els.date.textContent = "";
    this.els.subject.textContent = "";
    this.els.attachment.textContent = "";
    this.els.body.textContent = msg;
  }

  setEmailData(data) {
    this.threads = data.threads;
    this.threadIndex = 0;
    this.msgIndex = 0;
    if (data.threads.length > 0) {
      this.pendingAnnounce =
        `${data.threads.length}件のスレッドに${data.totalMsgs}件の未読メールがあります。`;
    }
  }

  _currentEmail() {
    if (!this.threads.length) return null;
    return this.threads[this.threadIndex][this.msgIndex];
  }

  _currentThread() {
    if (!this.threads.length) return [];
    return this.threads[this.threadIndex];
  }

  showCurrent() {
    const email = this._currentEmail();
    if (!email) return;
    const thread = this._currentThread();
    const tIdx = this.threadIndex + 1;
    const tTotal = this.threads.length;
    const mIdx = this.msgIndex + 1;
    const mTotal = thread.length;

    this.els.status.textContent =
      mTotal === 1
        ? `スレッド ${tIdx}/${tTotal}`
        : `スレッド ${tIdx}/${tTotal} — メール ${mIdx}/${mTotal}`;
    this.els.sender.textContent = `差出人: ${email.sender}`;
    this.els.date.textContent = `日時: ${email.date}`;
    this.els.subject.textContent = `件名: ${email.subject}`;
    this.els.attachment.textContent = email.hasAttachment ? "📎 添付ファイルあり" : "";

    const sentences = splitIntoSentences(email.bodyClean);
    this.els.body.innerHTML = "";
    for (const s of sentences) {
      const span = document.createElement("span");
      span.className = "sentence";
      span.textContent = s;
      this.els.body.appendChild(span);
      if (s.includes("\n") || s.endsWith("。") || s.endsWith("！") || s.endsWith("？")) {
        this.els.body.appendChild(document.createElement("br"));
      }
    }
  }

  _highlightSentence(text) {
    const spans = this.els.body.querySelectorAll(".sentence");
    for (const span of spans) {
      span.classList.remove("sentence-highlight");
    }
    const clean = text.trim();
    for (const span of spans) {
      if (span.textContent.trim() === clean) {
        span.classList.add("sentence-highlight");
        span.scrollIntoView({ behavior: "smooth", block: "nearest" });
        break;
      }
    }
  }

  _clearHighlight() {
    const spans = this.els.body.querySelectorAll(".sentence");
    for (const span of spans) span.classList.remove("sentence-highlight");
  }

  fontLarger() {
    this.fontSize = Math.min(this.fontSize + 4, 48);
    this._applyFontSize();
  }

  fontSmaller() {
    this.fontSize = Math.max(this.fontSize - 4, 14);
    this._applyFontSize();
  }

  _applyFontSize() {
    document.documentElement.style.setProperty("--font-size-base", this.fontSize + "px");
  }

  play() {
    const email = this._currentEmail();
    if (!email) return;
    const thread = this._currentThread();
    this._clearHighlight();

    const parts = [];
    if (this.pendingAnnounce) {
      parts.push(this.pendingAnnounce);
      this.pendingAnnounce = null;
    }
    if (this.msgIndex === 0) {
      if (thread.length > 1) {
        parts.push(`スレッド${this.threadIndex + 1}。${thread.length}件の新着があります。`);
      } else {
        parts.push(`スレッド${this.threadIndex + 1}。`);
      }
    }
    parts.push(`${email.sender}さんから。`);
    parts.push(`件名、${email.subject}。`);
    if (email.hasAttachment) {
      parts.push("添付ファイルがあります。いつものメール画面でメールを開いて確認してください。");
    }
    parts.push(email.bodyClean);

    this.playGen++;
    const gen = this.playGen;
    this.speech.speak(parts.join(""), () => this._autoNext(gen));
  }

  stop() {
    this.speech.stop();
    this._clearHighlight();
  }

  repeat() {
    this.play();
  }

  _advance() {
    const thread = this._currentThread();
    const email = this._currentEmail();
    if (email) this.gmail.markAsRead(email.id);
    if (this.msgIndex < thread.length - 1) {
      this.msgIndex++;
      return true;
    } else if (this.threadIndex < this.threads.length - 1) {
      this.threadIndex++;
      this.msgIndex = 0;
      return true;
    }
    return false;
  }

  _goBack() {
    if (this.msgIndex > 0) {
      this.msgIndex--;
      return true;
    } else if (this.threadIndex > 0) {
      this.threadIndex--;
      this.msgIndex = this.threads[this.threadIndex].length - 1;
      return true;
    }
    return false;
  }

  next() {
    if (!this.threads.length) return;
    this.stop();
    if (this._advance()) {
      this.showCurrent();
      this.play();
    } else {
      const email = this._currentEmail();
      if (email) this.gmail.markAsRead(email.id);
      this.speech.speak("全てのメールを読み終わりました。");
      this.els.status.textContent = "全て読み終わりました";
    }
  }

  prev() {
    if (!this.threads.length) return;
    this.stop();
    if (this._goBack()) {
      this.showCurrent();
      this.play();
    }
  }

  _autoNext(gen) {
    if (gen !== this.playGen) return;
    if (this._advance()) {
      this.showCurrent();
      this.play();
    } else {
      this.speech.speak("全てのメールを読み終わりました。");
      this.els.status.textContent = "全て読み終わりました";
    }
  }

  async refresh() {
    this.stop();
    this.threads = [];
    this.threadIndex = 0;
    this.msgIndex = 0;
    this.showMessage("メールを確認中...");
    this.speech.speak("メールを確認しています。");
    try {
      const data = await this.gmail.fetchAllUnread();
      if (data.error === "label-not-found") {
        this.showMessage("ラベルが見つかりません");
        return;
      }
      if (data.threads.length === 0) {
        this.showMessage("未読メールはありません");
        this.speech.speak("未読メールはありません。");
        return;
      }
      this.setEmailData(data);
      this.showCurrent();
      this.play();
    } catch (e) {
      this.showMessage("エラー: " + e.message);
    }
  }
}
