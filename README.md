# ChatGPTから使う、無料枠向けAnki連携の試作

**タグ別カード一覧・学習統計のWebアプリ「Anki Atlas」を追加しました。** AnkiConnect経由で自分のAnkiのカードと学習履歴を取り込み、認証付きのオンライン画面で確認できます。セットアップ・公開方法は [DASHBOARD.md](DASHBOARD.md) を参照してください。以下は従来のMCP試作の説明です。

PCがオフでもChatGPTのカスタムMCPから文字カードを作成・検索・編集し、復習回答をAnkiに記録するためのコードです。Renderは必要なときに起動し、保存データとOAuthの接続情報はSupabaseに暗号化して置きます。生成と解説は会話中のChatGPTが担当するため、OpenAI APIキーは使いません。

これは導入前の試作です。実際のRender、Supabase、GitHub OAuth、ChatGPT、および利用者のAnkiWebとの接続はまだ検証していません。Renderの無料インスタンスでの起動時間・メモリ・タイムアウトも公開後の確認が必要です。

```text
ChatGPT Plus → HTTPS / OAuth → Render Free のMCP
                                 ├─ Anki公式ライブラリ（GUIなし）
                                 ├─ Supabase Free：暗号化データ・認証情報
                                 └─ AnkiWeb：明示的に同期
                                               ↕
                                           PC / スマホ
```

## できることと範囲

| 機能 | 実装 |
|---|---|
| コレクション情報 | デッキ、ノートタイプ、フィールド、カード数 |
| カード作成 | ノートタイプを指定、プレーンテキスト、タグ、重複拒否 |
| 検索・編集・削除 | Anki検索構文、編集前バージョンの確認、明示的削除 |
| 復習 | Ankiのスケジューラーから次のカードを取得、正解表示、4段階評価 |
| 回答記録 | 本物のAnki復習履歴、再送時の二重記録防止 |
| 同期 | AnkiWebへの通常同期、初回ダウンロード、全体置換の保護 |

画像・音声の同期、添付ファイル、任意のHTML・JavaScriptの作成、全Anki設定の編集は対象外です。既存カードの文字情報は扱えますが、画像だけの問題には答えられません。カード表示のHTMLはテキストへ変換し、外部画像やスクリプトを実行しません。同期は自動ではなく `sync_ankiweb` の呼び出しで行います。PC・スマホ側でも同期が必要です。

## 費用を発生させない条件

- Renderは **Free**、Supabaseの組織も **Free** を選びます。GitHubも既存の無料枠を利用します。
- クレジットカード・支払い方法は登録せず、有料プランや追加機能は選びません。サービスがカード登録を必須にした場合は中断してください。
- 有料化、課金API、休止を避けるための定期アクセスはコードに含めていません。
- 無料枠を超えると機能が停止・制限される前提です。無料サービスの提供条件を固定することはできません。
- コレクションは展開後 **20MB以内** に制限します。操作ごとに暗号化スナップショットを読み書きするため、月間通信量も上限に達する場合があります。
- Renderは約15分の無通信で休止します。最初の操作は起動待ちになり、ChatGPTがタイムアウトした場合は同じ操作IDで再試行します。
- Supabase Freeも低稼働で休止する場合があります。ダッシュボードで再開する必要があります。長期保管を無料サービスだけに依存しないでください。

公式仕様： [Render Free](https://render.com/docs/free)、[Supabase Free](https://supabase.com/pricing)、[Supabaseの休止](https://supabase.com/docs/guides/platform/free-project-pausing)。

## 1. Supabase Freeを用意する

RenderとGitHubが既にある場合、追加するのは[Supabase](https://supabase.com/)です。GitHubでログインし、Free組織に新しいプロジェクトを作ります。DBのパスワードはパスワード管理ツールに保存し、チャットやGitには貼りません。

SQL Editorで `schema.sql` 全体を実行します。これで保存テーブルと、排他制御・保存・認証情報の書き込み用関数ができます。匿名ユーザーおよびSupabaseにログインしただけのユーザーには読み書き権限を与えません。

プロジェクトURLと、API Keysの **legacy `service_role` キー（JWT形式）** を確認します。`anon` キーや公開キーは使いません。後でRenderの秘密の環境変数へ入れます。Supabaseは専用プロジェクトにし、このキーをクライアントや公開リポジトリへ渡さないでください。

## 2. ソースをGitHubへ置く

新しいプライベートリポジトリに、このフォルダーのソースをアップロードします。`.venv`、`.env`、`secrets.env`、`generated-secrets.env`、Ankiデータ、バックアップは入れません。

Renderからこのリポジトリを選んでPython Web Serviceを作ります。設定は `render.yaml` と同じにします。

```text
Instance Type: Free
Build Command: pip install --require-hashes -r requirements.txt
Start Command: uvicorn server:app --host 0.0.0.0 --port $PORT --workers 1 --no-access-log
Health Check Path: /health
Python Version: 3.12.14
```

環境変数がまだない段階では起動に失敗しますが、割り当てられた `https://...onrender.com` のURLを次のOAuth設定で使えます。常時起動の有料workerや有料ディスクを追加する必要はありません。ソースのトップに `server.py` があることを確認してください。

## 3. GitHub OAuthを設定する

[GitHub OAuth Apps](https://github.com/settings/developers)で自分用のOAuth Appを作ります。

```text
Homepage URL: https://YOUR-SERVICE.onrender.com
Authorization callback URL: https://YOUR-SERVICE.onrender.com/auth/callback
```

Client IDとClient SecretをRenderの環境変数に設定します。このアプリのGitHub権限はプロフィール読み取りの `read:user` だけで、リポジトリの読み書き権限は要求しません。

ブラウザーで `https://api.github.com/users/YOUR_USERNAME` を開き、`id` の数値を確認します。`ALLOWED_GITHUB_USER_ID` にはこの数値を入れます。ユーザー名やUUIDを入れても起動しません。他のGitHubアカウントではAnkiにアクセスできません。

接続用のOAuthクライアントコールバックは、ChatGPTの接続設定に表示される**正確なURL**を `MCP_REDIRECT_URIS` に入れます。GitHubに登録する `/auth/callback` とは別です。複数ならカンマ区切り、ワイルドカードは使いません。ChatGPTのURLを取得できない場合は初期値を仮設定し、接続画面で実際のコールバックを確認してから修正します。

## 4. 鍵とAnkiWebトークンを作る

一度だけ、手元のPCでPython 3.12とこのソースを使います。PCは初期設定に使うだけで、運用中の常時起動は不要です。

```sh
python -m venv .venv
# Linux/macOS
.venv/bin/python -m pip install --require-hashes -r requirements.txt
.venv/bin/python scripts/generate_secrets.py
.venv/bin/python scripts/ankiweb_token.py
# Windowsでは .venv/bin/python を .venv\Scripts\python.exe に置き換えます。
```

`generate_secrets.py` は暗号化キー2個と署名キーを `generated-secrets.env` に保存します。`ankiweb_token.py` はAnkiWebパスワードを非表示入力で受け取り、トークンだけを `secrets.env` に保存します。パスワードは保存・表示しません。ファイルが既にある場合は上書きしません。

これらの値はRenderのEnvironmentへ直接入れてください。チャットに送る必要はありません。`DATA_ENCRYPTION_KEY` は別の安全な場所にも保存します。このキーを失うと暗号化データは復元できません。Windowsのファイルアクセス権は別途自分だけが読めるように設定してください。

## 5. Renderの環境変数を設定する

`.env.example` に全項目があります。

| 変数 | 値 |
|---|---|
| `PUBLIC_URL` | RenderのHTTPS URL、末尾パスなし |
| `SUPABASE_URL` | SupabaseのプロジェクトURL |
| `SUPABASE_SERVICE_KEY` | 専用プロジェクトのlegacy service_roleキー |
| `DATA_ENCRYPTION_KEY` | ローカルで生成したデータ暗号化キー |
| `OAUTH_ENCRYPTION_KEY` | 別に生成したOAuth暗号化キー |
| `JWT_SIGNING_KEY` | 生成した署名キー |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | OAuth Appの値 |
| `ALLOWED_GITHUB_USER_ID` | 自分のGitHub数値ID |
| `MCP_REDIRECT_URIS` | ChatGPTに表示される正確なコールバックURL |
| `ANKIWEB_HKEY` / `ANKIWEB_ENDPOINT` | ローカルのログインスクリプトの値 |
| `TZ` | 日本なら `Asia/Tokyo` |

`ANKIWEB_ENDPOINT` が空なら未設定のままで構いません。値がある場合はスクリプトの出力をそのまま使います。`.env.example` の空欄を公開Git上で埋めないでください。

設定後にデプロイし、`/health` が `{"status":"ok"}` を返すことを確認します。これは起動確認であり、保存先・AnkiWebの疎通成功を意味しません。

## 6. ChatGPTにつなぐ

Plusで利用できるカスタムMCP接続に、次を設定します。

```text
MCP URL: https://YOUR-SERVICE.onrender.com/mcp
Authentication: OAuth
```

GitHubで自分のアカウントにログインして認証します。最初の呼び出しが起動待ちで失敗したら、起動後に接続を再試行します。

最初は既存のAnkiをAnkiWebへ同期し、バックアップを取ってから、ChatGPTで次の順に確認します。

1. 「Ankiの接続状態とデッキ一覧を確認して」
2. 「AnkiWebから同期して」— 空のサーバーコレクションへの初回ダウンロードです。
3. 「Ankiのテスト用デッキに、表が『2+2』、裏が『4』のカードを1枚追加して」
4. 「テスト用デッキを検索して」
5. 「テスト用デッキから1問出して」→ 回答 → 正解表示 → 自分で評価を選択
6. 「AnkiWebへ同期して」→ PCかスマホも同期 → カードと復習履歴を確認
7. Renderを再起動して、同じカード・履歴・OAuth接続が維持されることを確認

`request_id` はChatGPTが操作ごとにUUIDを作ります。同じ操作を再送するときは同じIDを使います。別のIDで同じ復習を二度送ると、古い復習セッションとして拒否します。全体同期の方向が不明な場合は止まり、自動ではどちらのデータも置換しません。

## セキュリティと復旧

- HTTPSとOAuth、GitHub数値IDによる本人制限を使います。OAuthプロキシにはPKCE・同意画面・正確なコールバック制限を使い、認証情報もSupabaseへ暗号化して保存します。
- AnkiConnect、AnkiのGUI、SSH、任意のコマンド実行や任意のURL取得は公開しません。
- 起動設定が不足している場合は起動しません。保存先が休止・故障したときも、空のコレクションで既存データを上書きしません。
- DBの120秒リースとリビジョン確認で、同時処理と期限切れの処理による上書きを防ぎます。カード処理は1分30操作、受信本文は64KBまでです。
- 内容と認証情報は保存先で暗号化されますが、操作中はRenderで復号します。Render、Supabase、GitHub、ChatGPTおよびAnkiWebを信頼する構成です。クラウド運営者からも完全に秘匿する方式ではありません。
- Freeで常時稼働やデータ保存の保証はありません。前回スナップショット1世代は短期の復旧補助で、独立したバックアップではありません。
- ローカルの環境変数にSupabaseの値を設定して `scripts/backup.py` を実行すると、暗号化バックアップをPCへ保存できます。CLIは保存先を変更しません。復元はバックアップとキーを確認して手動で行う想定で、自動復元コマンドはありません。
- AnkiWeb側の変更とSupabaseの書き込みは単一トランザクションにはできません。同期後の保存に失敗した場合は同期済みと返さず、AnkiWeb側を確認してから再試行します。

## 開発と検証

```sh
uv sync --frozen
uv run pytest -q
```

テストにはローカルのHTTPポートを使います。`tests/test_sync_integration.py` はAnki公式のローカル同期サーバーを一時起動し、実際の同期プロトコルで初回ダウンロード・復習履歴の往復を検証します。外部のAnkiWebアカウントや有料APIは使いません。

SQLはPostgreSQL 17に `anon`、`authenticated`、`service_role`（BYPASSRLS）のテスト用ロールを作り、`schema.sql` → `tests/postgres.sql` の順で実行して確認できます。Supabase本番のロールを作り直す必要はありません。

依存ライブラリは `uv.lock` とハッシュ付き `requirements.txt` で固定しています。Ankiバックエンドの一部APIは安定した公開APIではないため、更新時は同期・スケジューラーのテストが必要です。

AnkiはAGPL-3.0-or-laterです。この試作ソースも同じライセンスで提供します。デプロイ時は利用したソースと依存のライセンス条件を維持してください。

PC停止中の定期取り込みは [GitHub Actions設定手順](ACTIONS_SETUP.md) を参照してください。
