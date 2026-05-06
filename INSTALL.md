# メール読み上げアプリ インストール手順

## 前提条件

- Windows 10 または Windows 11
- インターネット接続

## 手順

### 1. Python のインストール

1. https://www.python.org/downloads/ にアクセス
2. 「Download Python 3.13.x」ボタンをクリック
3. ダウンロードした `python-3.13.x-amd64.exe` を実行
4. **「Add python.exe to PATH」にチェックを入れる**（重要）
5. 「Install Now」をクリック
6. インストール完了を待つ

**確認方法**: コマンドプロンプトを開き、以下を実行:
```
python --version
```
`Python 3.13.x` と表示されればOK。

### 2. アプリのダウンロード

#### 方法A: Git がある場合
```
git clone https://github.com/tranzact-dev/mail-reader.git
cd mail-reader
git checkout develop
```

#### 方法B: Git がない場合
1. https://github.com/tranzact-dev/mail-reader にアクセス
2. 緑の「Code」ボタン → 「Download ZIP」
3. ZIPを展開し、任意の場所に配置（例: `C:\mail-reader`）

### 3. 依存パッケージのインストール

コマンドプロンプトでアプリのフォルダに移動し、以下を実行:

```
cd C:\mail-reader
pip install -r requirements.txt
```

全パッケージが `Successfully installed` と表示されればOK。

### 4. 環境設定ファイルの作成

アプリのフォルダに `.env` ファイルを作成し、以下の内容を記入:

```
ANTHROPIC_API_KEY=（Claude APIキー）
BIGLOBE_EMAIL=（BIGLOBEメールアドレス）
BIGLOBE_PASSWORD=（BIGLOBEパスワード）
CASUAL_CONTACTS=
```

- `ANTHROPIC_API_KEY`: https://console.anthropic.com/ で取得
- `BIGLOBE_EMAIL` / `BIGLOBE_PASSWORD`: BIGLOBEメールのログイン情報
- `CASUAL_CONTACTS`: くだけた口調で返信する相手の名前（カンマ区切り、空でも可）

### 5. 本番モードへの切替

`mail_reader_gui.py` の29行目:
```python
DRY_RUN = True   ← テスト中はこのまま
DRY_RUN = False  ← 本番運用時に変更（メール送信・既読マークが有効になる）
```

### 6. 起動

```
cd C:\mail-reader
python mail_reader_gui.py
```

アプリが全画面で起動し、未読メールの読み上げが自動的に始まります。

## デスクトップショートカットの作成（任意）

ダブルクリックで起動できるようにする手順:

1. デスクトップを右クリック → 「新規作成」→「ショートカット」
2. 場所に以下を入力:
   ```
   pythonw.exe C:\mail-reader\mail_reader_gui.py
   ```
3. 名前を「メール読み上げ」に設定
4. 作成されたショートカットを右クリック → プロパティ
5. 「作業フォルダー」に `C:\mail-reader` を入力
6. 「OK」

> `pythonw.exe` を使うと、コマンドプロンプトの黒い画面が表示されません。

## トラブルシューティング

### 「python が見つかりません」と表示される

→ Pythonインストール時に「Add python.exe to PATH」にチェックを入れ忘れた可能性あり。Pythonを再インストールし、PATHオプションを有効にしてください。

### 「ModuleNotFoundError: No module named 'xxx'」と表示される

→ 依存パッケージがインストールされていません。以下を再実行:
```
pip install -r requirements.txt
```

### 「未読メールはありません」と表示されるが実際には未読がある

→ BIGLOBEのメールアドレス・パスワードが正しいか `.env` を確認してください。
→ 直近30日間の未読メールのみが対象です。それ以前のメールは表示されません。

### 音声が出ない

→ PCの音量がミュートになっていないか確認してください。
→ Edge-TTS はインターネット接続が必要です。オフラインでは動作しません。

### 返信が生成されない（「返信を考えています」のまま止まる）

→ Anthropic APIキーが正しいか `.env` を確認してください。
→ APIクレジット残高を https://console.anthropic.com/ で確認してください。

## アップデート方法

Git がある場合:
```
cd C:\mail-reader
git pull
pip install -r requirements.txt
```

Git がない場合: 最新のZIPをダウンロードし、既存ファイルを上書き。`.env` は上書きしないよう注意。
