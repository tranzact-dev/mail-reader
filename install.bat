@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo   メール読み上げアプリ インストーラー
echo ============================================
echo.

set "INSTALL_DIR=C:\mail-reader"
set "REPO_URL=https://github.com/tranzact-dev/mail-reader.git"
set "SCRIPT_DIR=%~dp0"
set "PYTHON_URL=https://www.python.org/ftp/python/3.13.5/python-3.13.5-amd64.exe"
set "GIT_URL=https://github.com/git-for-windows/git/releases/download/v2.49.0.windows.1/Git-2.49.0-64-bit.exe"

:: --- Python チェック ---
echo [1/5] Python を確認しています...
python --version >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo       Python %%v インストール済み（スキップ）
) else (
    echo       Python が見つかりません。ダウンロードしてインストールします...
    if not exist "%SCRIPT_DIR%python-3.13.5-amd64.exe" (
        echo       ダウンロード中...
        powershell -Command "Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%SCRIPT_DIR%python-3.13.5-amd64.exe'"
        if not exist "%SCRIPT_DIR%python-3.13.5-amd64.exe" (
            echo       [エラー] ダウンロードに失敗しました。インターネット接続を確認してください
            pause
            exit /b 1
        )
        echo       ダウンロード完了
    )
    echo       インストール中...
    "%SCRIPT_DIR%python-3.13.5-amd64.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_launcher=1
    if %errorlevel%==0 (
        echo       Python インストール完了
    ) else (
        echo       [エラー] Python のインストールに失敗しました
        pause
        exit /b 1
    )
    set "PATH=C:\Program Files\Python313;C:\Program Files\Python313\Scripts;%PATH%"
)
echo.

:: --- Git チェック ---
echo [2/5] Git を確認しています...
git --version >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=3" %%v in ('git --version') do echo       Git %%v インストール済み（スキップ）
) else (
    echo       Git が見つかりません。ダウンロードしてインストールします...
    if not exist "%SCRIPT_DIR%Git-2.49.0-64-bit.exe" (
        echo       ダウンロード中...
        powershell -Command "Invoke-WebRequest -Uri '%GIT_URL%' -OutFile '%SCRIPT_DIR%Git-2.49.0-64-bit.exe'"
        if not exist "%SCRIPT_DIR%Git-2.49.0-64-bit.exe" (
            echo       [エラー] ダウンロードに失敗しました。インターネット接続を確認してください
            pause
            exit /b 1
        )
        echo       ダウンロード完了
    )
    echo       インストール中...
    "%SCRIPT_DIR%Git-2.49.0-64-bit.exe" /VERYSILENT /NORESTART /NOCANCEL /SP- /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /COMPONENTS="icons,ext\reg\shellhere,assoc,assoc_sh"
    if %errorlevel%==0 (
        echo       Git インストール完了
    ) else (
        echo       [エラー] Git のインストールに失敗しました
        pause
        exit /b 1
    )
    set "PATH=C:\Program Files\Git\cmd;%PATH%"
)
echo.

:: --- アプリ取得 ---
echo [3/5] アプリを取得しています...
if exist "%INSTALL_DIR%\.git" (
    echo       %INSTALL_DIR% は取得済み（スキップ）
) else (
    git clone %REPO_URL% "%INSTALL_DIR%"
    if %errorlevel%==0 (
        echo       取得完了
    ) else (
        echo       [エラー] アプリの取得に失敗しました。インターネット接続を確認してください
        pause
        exit /b 1
    )
)
echo.

:: --- 依存パッケージ ---
echo [4/5] 依存パッケージをインストールしています...
pip install -r "%INSTALL_DIR%\requirements.txt"
echo       完了
echo.

:: --- .env 配置 ---
echo [5/5] 設定ファイルを配置しています...
if exist "%INSTALL_DIR%\.env" (
    echo       .env は既に存在します（スキップ）
) else if exist "%SCRIPT_DIR%.env" (
    copy "%SCRIPT_DIR%.env" "%INSTALL_DIR%\.env" >nul
    echo       .env を配置しました
) else (
    echo       [注意] .env ファイルが見つかりません
    echo       %INSTALL_DIR%\.env を手動で作成してください
)
echo.

:: --- デスクトップショートカット ---
echo デスクトップショートカットを作成しています...
set "SHORTCUT=%USERPROFILE%\Desktop\メール読み上げ.lnk"
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('%SHORTCUT%'); $sc.TargetPath = '%INSTALL_DIR%\start.bat'; $sc.WorkingDirectory = '%INSTALL_DIR%'; $sc.Description = 'メール読み上げアプリ'; $sc.Save()"
echo       完了
echo.

echo ============================================
echo   インストール完了！
echo   デスクトップの「メール読み上げ」から起動できます
echo ============================================
pause
