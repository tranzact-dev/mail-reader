class SpeechController {
  constructor() {
    this.synth = window.speechSynthesis;
    this.onSentenceStart = null;
    this.onDone = null;
    this._generation = 0;
    this._voice = null;
    this._resumeInterval = null;
    this.voiceName = "loading...";
    this._initVoice();
  }

  _initVoice() {
    const pick = () => {
      const voices = this.synth.getVoices();
      this._voice =
        voices.find(v => v.name.includes("Nanami") && v.name.includes("Online")) ||
        voices.find(v => v.name.includes("Nanami")) ||
        voices.find(v => v.name.includes("Google") && v.lang === "ja-JP") ||
        voices.find(v => v.lang === "ja-JP" && v.name.includes("Online")) ||
        voices.find(v => v.lang === "ja-JP") ||
        null;
      this.voiceName = this._voice ? this._voice.name : "none";
    };
    pick();
    if (!this._voice) {
      this.synth.addEventListener("voiceschanged", () => pick(), { once: true });
    }
  }

  speak(text, onDone) {
    this.stop();
    this._generation++;
    const gen = this._generation;
    const sentences = splitIntoSentences(text);
    this._resumeInterval = setInterval(() => this.synth.resume(), 5000);
    this._speakQueue(sentences, 0, gen, onDone);
  }

  _speakQueue(sentences, idx, gen, onDone) {
    if (gen !== this._generation) return;
    if (idx >= sentences.length) {
      this._clearInterval();
      if (onDone) onDone();
      return;
    }
    const utt = new SpeechSynthesisUtterance(sentences[idx]);
    utt.lang = "ja-JP";
    utt.rate = 0.9;
    if (this._voice) utt.voice = this._voice;
    utt.onstart = () => {
      if (gen === this._generation && this.onSentenceStart) {
        this.onSentenceStart(sentences[idx]);
      }
    };
    utt.onend = () => this._speakQueue(sentences, idx + 1, gen, onDone);
    utt.onerror = (e) => {
      if (e.error !== "interrupted") {
        this._speakQueue(sentences, idx + 1, gen, onDone);
      }
    };
    this.synth.speak(utt);
  }

  stop() {
    this._generation++;
    this.synth.cancel();
    this._clearInterval();
  }

  _clearInterval() {
    if (this._resumeInterval) {
      clearInterval(this._resumeInterval);
      this._resumeInterval = null;
    }
  }
}
