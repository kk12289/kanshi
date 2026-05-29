# kanshi（監視）β

kanshiは、日本語UIのシンプルなURL監視SaaS MVPです。登録したURLを60秒ごとにチェックし、状態変化があったときだけDiscordまたはメールへ通知します。

現在はβ版です。小規模な検証や顧客への試験提供を想定しています。

## 主な機能

- URLの死活監視
- 管理ダッシュボードとサマリーカード
- 顧客向け公開ステータスページ
- インシデント履歴
- 障害報告文テンプレートのコピー
- Discord Webhook通知
- SMTPメール通知
- SQLite / PostgreSQL対応

Discord通知とメール通知はどちらも任意です。両方を設定することも、どちらも設定せずに監視だけ行うこともできます。

## ローカルセットアップ

ローカル開発では `DATABASE_URL` を設定しなければSQLiteで動きます。

```bat
cd C:\Users\admin\Documents\Codex\2026-05-29\you-are-building-a-japanese-uptime
```

```bash
pip install -r requirements.txt
```

Windowsで `pip` が見つからない場合:

```bat
python -m pip install -r requirements.txt
```

このCodex環境では、同梱Pythonでも実行できます。

```bat
C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pip install -r requirements.txt
```

## ローカル起動

```bash
python app.py
```

`python` が見つからない場合:

```bat
C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe app.py
```

起動後、ブラウザで開きます。

```text
http://127.0.0.1:5000
```

初回起動時にテーブルが自動作成されます。既存SQLite DBに通知用カラムがない場合も、簡易マイグレーションで追加します。

## 環境変数

`.env.example` を参考に `.env` を作成できます。

```env
SECRET_KEY=change-me
ADMIN_USERNAME=admin
ADMIN_PASSWORD=
BASE_URL=http://127.0.0.1:5000
DATABASE_URL=
DATABASE_SSLMODE=
FLASK_DEBUG=0
SCHEDULER_ENABLED=1
ALLOW_PRIVATE_URLS=0
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=
```

主な設定:

- `SECRET_KEY`: Flaskのセッション署名キー。本番では必ず変更してください。
- `ADMIN_USERNAME`: 管理画面Basic認証のユーザー名です。未設定時は `admin` です。
- `ADMIN_PASSWORD`: 管理画面Basic認証のパスワードです。設定した場合、管理画面に認証がかかります。
- `BASE_URL`: 通知内の公開ステータスページURLに使います。例: `https://kanshi.example.com`
- `DATABASE_URL`: 本番DB接続URL。未設定なら `sqlite:///kanshi.db` を使います。
- `DATABASE_SSLMODE`: 必要な場合だけPostgreSQL接続のSSLモードを指定します。RenderのExternal Database URLを使う場合は `require` を試してください。Internal Database URLでは通常は空欄でOKです。
- `FLASK_DEBUG`: 本番では `0` にしてください。未設定時も `0` 扱いです。
- `SCHEDULER_ENABLED`: `1` ならAPSchedulerを起動します。WebとWorkerを分ける場合は制御に使えます。
- `ALLOW_PRIVATE_URLS`: `1` の場合のみlocalhostやprivate IPの監視URLを許可します。本番では `0` 推奨です。
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`: メール通知用SMTP設定です。

メール送信はSTARTTLS前提です。`SMTP_PORT=587` を推奨します。SSL直接接続の `465` は現在未対応です。

Renderなどで `postgres://...` が渡される場合も、アプリ側で `postgresql://...` に変換します。

## PostgreSQLについて

ローカル開発はSQLiteで問題ありません。本番やβ版デプロイでは、Render PostgreSQLなどのPostgreSQLを推奨します。

例:

```env
DATABASE_URL=postgresql://user:password@host:5432/database
DATABASE_SSLMODE=
BASE_URL=https://your-kanshi.onrender.com
```

SQLiteは手軽ですが、RenderのWeb Serviceではローカルファイルが再起動や再デプロイで消える可能性があります。

## gunicornでの起動

Renderなどでは次のStart Commandを使えます。

```bash
gunicorn --workers 1 app:app
```

`gunicorn` はLinux/Unix向けです。Windowsローカルでは次のどちらかで起動してください。

開発用:

```bash
python app.py
```

Windowsで本番に近いWSGI起動を試す場合:

```bash
waitress-serve --listen=127.0.0.1:5000 app:app
```

`waitress-serve` がPATHにない場合は、Codex同梱Pythonでは次のように実行できます。

```bat
C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Scripts\waitress-serve.exe --listen=127.0.0.1:5000 app:app
```

RenderやLinux環境でgunicorn起動を試す場合:

```bash
gunicorn --workers 1 app:app
```

Windowsのコマンドプロンプトで `gunicorn --workers 1 app:app` を実行すると、`gunicorn` が見つからない、またはWindows非対応のため起動できないことがあります。Render上ではLinux環境で実行されるため、Start Commandは `gunicorn --workers 1 app:app` のままで問題ありません。

## Renderデプロイ手順

`render.yaml` を追加済みなので、Render Blueprintとして作成することもできます。手動でWeb Serviceを作る場合は以下の手順です。

1. GitHubなどにこのプロジェクトをpushします。
2. RenderでPostgreSQLを作成します。
3. RenderでWeb Serviceを作成し、リポジトリを接続します。
4. Build Commandを設定します。

```bash
pip install -r requirements.txt
```

5. Start Commandを設定します。

```bash
gunicorn --workers 1 app:app
```

`Procfile` も同じ内容で追加済みです。

6. Environment Variablesを設定します。

```env
SECRET_KEY=本番用の長いランダム文字列
ADMIN_USERNAME=admin
ADMIN_PASSWORD=管理画面用の長いパスワード
BASE_URL=https://your-kanshi.onrender.com
DATABASE_URL=Render PostgreSQLのExternal Database URLまたはInternal Database URL
DATABASE_SSLMODE=
FLASK_DEBUG=0
SCHEDULER_ENABLED=1
ALLOW_PRIVATE_URLS=0
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=
WEB_CONCURRENCY=1
```

7. デプロイ後、`https://your-kanshi.onrender.com` を開いて動作確認します。

## APSchedulerとRender Freeプランの注意

kanshiはFlaskアプリ内でAPSchedulerを起動し、60秒ごとに監視チェックを行います。Flaskのdebug reloaderでは二重起動しないようにしています。

RenderのFree Web Serviceはアクセスがないとスリープする可能性があります。スリープ中はアプリ内のAPSchedulerも止まるため、監視処理が実行されません。

β版検証ではFreeプランでも試せますが、本番運用では次のいずれかを検討してください。

- Renderの有料プラン
- VPSなど常時起動できる環境
- Webアプリと監視Workerの分離
- 外部CronやWorkerによるチェック実行

gunicornで複数workerを起動すると、APSchedulerも複数起動する可能性があります。β版では `gunicorn --workers 1 app:app` と `WEB_CONCURRENCY=1` を推奨します。

Webアプリと監視Workerを分ける場合は、Web側で `SCHEDULER_ENABLED=0`、Worker側で `SCHEDULER_ENABLED=1` のように分離してください。

## 管理画面の認証

`ADMIN_PASSWORD` を設定すると、管理画面にBasic認証がかかります。公開ステータスページ `/status/{slug}` は認証なしで表示できます。

β版として外部公開する場合は、必ず `ADMIN_PASSWORD` を設定してください。設定しない場合、誰でも監視URLを追加・削除できます。

## 監視URLを追加する

1. ダッシュボード右上の「監視を追加」を開きます。
2. サービス名と監視URLを入力します。
3. 必要に応じてDiscord Webhook URL、通知用メールアドレスを入力します。
4. 通知を使う場合は「Discord通知を有効にする」「メール通知を有効にする」にチェックを入れます。
5. 追加後、約60秒ごとに自動チェックされます。

URLは `http://` または `https://` から始まる必要があります。同じURLは重複登録できません。

本番環境ではSSRF対策として、localhostやprivate IPへのURL登録をブロックします。ローカル検証で必要な場合だけ `ALLOW_PRIVATE_URLS=1` を設定してください。

監視実行時にも同じSSRFチェックを行い、private IPやlocalhostに解決されるURLはリクエストしません。また、監視チェックではリダイレクトを追跡しません。

## Discord Webhookの設定方法

Discordの対象チャンネルで「チャンネル設定」→「連携サービス」→「ウェブフック」からWebhookを作成し、発行されたURLをkanshiの追加フォームに貼り付けます。

Discord Webhook URLが空欄の場合、Discord通知は送信されません。DOWN状態が続いている間、同じ障害通知は繰り返し送信されません。

## メール通知の設定方法

メール通知を使う場合はSMTP設定を環境変数に入れてください。

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=your-user@example.com
SMTP_PASSWORD=your-password
SMTP_FROM=alerts@example.com
```

`SMTP_HOST` または `SMTP_FROM` が未設定の場合、メール送信はスキップされます。メール送信に失敗してもアプリ全体は停止しません。

現在のメール送信はSTARTTLSを使う `587` 番ポート前提です。`465` 番ポートのSSL直接接続は未対応です。

Gmail SMTPを使う場合、通常のGoogleアカウントパスワードではなく、Googleアカウントの2段階認証を有効にしたうえで発行する「アプリパスワード」が必要です。

## 通知タイミング

通知は状態が変わったときだけ送信されます。

- UPまたは未確認からDOWNになったとき
- DOWNからUPに復旧したとき

DOWN状態が継続している間、Discord通知やメール通知を連続送信しません。

## テスト用にDOWN状態を作る方法

次のような公開URLの404ページを登録すると、HTTP 200以外としてDOWNを確認できます。

```text
https://example.com/not-found
```

localhostへの監視を試したい場合は、ローカル環境で `ALLOW_PRIVATE_URLS=1` を設定したうえで、起動していないポートを指定します。

```text
http://127.0.0.1:59999
```

登録後、初回チェックは数秒後、その後は約60秒ごとに実行されます。

## 公開ステータスページ

ダッシュボードの各監視項目にある「公開ステータスページ」リンクから開けます。

URL形式:

```text
http://127.0.0.1:5000/status/{slug}
```

本番では `BASE_URL` を設定すると、通知内では次のようなURLになります。

```text
https://your-kanshi.onrender.com/status/{slug}
```

ステータスページでは現在状態、過去30日間の稼働率、インシデント履歴、お知らせ文テンプレートを確認できます。公開ページには管理者向けの「監視を追加」ボタンは表示されません。
