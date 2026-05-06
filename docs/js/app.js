const CLIENT_ID = "245880544982-9en8grj41iq5uh5ua6l709ki86uh8h4s.apps.googleusercontent.com";

let gmailClient;
let speechController;
let ui;

async function init() {
  speechController = new SpeechController();
  gmailClient = new GmailClient(CLIENT_ID);
  ui = new MailReaderUI(speechController, gmailClient);

  document.getElementById("btn-login").addEventListener("click", handleLogin);
  document.getElementById("btn-play").addEventListener("click", () => ui.play());
  document.getElementById("btn-stop").addEventListener("click", () => ui.stop());
  document.getElementById("btn-repeat").addEventListener("click", () => ui.repeat());
  document.getElementById("btn-next").addEventListener("click", () => ui.next());
  document.getElementById("btn-prev").addEventListener("click", () => ui.prev());
  document.getElementById("btn-refresh").addEventListener("click", () => ui.refresh());
  document.getElementById("btn-font-up").addEventListener("click", () => ui.fontLarger());
  document.getElementById("btn-font-down").addEventListener("click", () => ui.fontSmaller());
  document.getElementById("btn-exit").addEventListener("click", handleExit);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") ui.stop();
  });

  await gmailClient.init();
  await tryAutoLogin();
}

async function tryAutoLogin() {
  try {
    await gmailClient.requestAuth();
    await loadAndPlay();
  } catch {
    // セッション切れ or 初回 → ログインボタン表示のまま
  }
}

async function handleLogin() {
  try {
    await gmailClient.requestAuth();
    await loadAndPlay();
  } catch (e) {
    ui.showMessage("ログインに失敗しました: " + e.message);
  }
}

async function loadAndPlay() {
  ui.showMainScreen();
  ui.showMessage("メールを読み込み中...");
  const data = await gmailClient.fetchAllUnread();
  if (data.error === "label-not-found") {
    ui.showMessage("ラベルが見つかりません");
    return;
  }
  if (data.threads.length === 0) {
    ui.showMessage("未読メールはありません");
    speechController.speak("未読メールはありません。");
    return;
  }
  ui.setEmailData(data);
  ui.showCurrent();
  ui.play();
}

function handleExit() {
  ui.stop();
  gmailClient.signOut();
  ui.showAuthScreen();
}

window.addEventListener("load", init);
