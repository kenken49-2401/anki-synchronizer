# Ankiタグ別ダッシュボード

自分のAnkiカードをタグごとに閲覧し、カード別の正解率と日ごとの学習記録を確認する個人用Webアプリです。接続先のAnkiアカウントは後から設定できます。Web画面にAnkiWebのパスワードを預ける必要はありません。

共有されたChatGPTのチャット本文はこの環境から取得できていません。画面は依頼された機能を基に作成しており、そのチャットの表示形式との完全一致は未確認です。

## 構成とできること

```text
自分のPCで起動したAnki
  └─ AnkiConnect（127.0.0.1:8765、APIキー）
       └─ connector.py：カード・復習履歴の読み取り
            └─ HTTPS + アップロード専用トークン
                 └─ クラウドの dashboard.py
                      ├─ 暗号化した最新スナップショット
                      └─ パスワード認証 → ブラウザーのダッシュボード
```

- 「学習ダッシュボード」でカード数や学習状況を確認できます。
- 「タグ別カード」でタグ・検索による絞り込み、カードの表裏、カード別の成績を確認できます。複数タグのカードは各タグに現れるため、タグ別件数を足すと全カード数を超える場合があります。
- 「学習の記録」で日ごとの学習時間・回答数・正解率を確認できます。
- 「接続・設定」で接続方法と最終同期の状態を確認できます。

ブラウザー用のデモデータと、自分のデータを扱う認証付きモードがあります。カードはテキストとして表示し、カードに含まれるHTMLやJavaScriptは実行しません。画像・音声の転送、ブラウザーからのカード編集や復習回答の書き込みは対象外です。

## 1. PCのAnkiを準備する

1. [Anki公式サイト](https://apps.ankiweb.net/)からデスクトップ版を導入し、自分のプロファイルを開きます。既存のカードがAnkiWebにある場合は、Anki側で自分のアカウントを設定し、通常の同期を済ませます。
2. 「ツール → アドオン → アドオンを取得」から [AnkiConnect](https://ankiweb.net/shared/info/2055492159)（コード `2055492159`）を導入し、Ankiを再起動します。
3. AnkiConnectの設定で `apiKey` にパスワード管理ツールなどで生成した十分に長いキーを設定します。接続先の `webBindAddress` は `127.0.0.1`、`webBindPort` は `8765` を使います。キーの変更後はAnkiを再起動します。

AnkiConnectのポート8765をインターネットへ公開したり、ルーターで転送したりする必要はありません。PC上のコネクターがクラウドへ送信します。

接続するアカウントを後から変える場合は、デスクトップ版Ankiで対応するプロファイルを開き、コネクターを起動し直します。`--profile` でプロファイル名を指定すると、別のプロファイルが開かれた場合の取り違えを防げます。コネクターは自動でプロファイルを切り替えません。`getActiveProfile` に対応していない古いアドオンでは、プロフィールが1つの環境だけで利用できます。複数ある場合は対応版への更新が必要です。

## 2. 依存関係と秘密ファイルを準備する

Python 3.12と [uv](https://docs.astral.sh/uv/) が必要です。リポジトリのルートで実行します。

```sh
uv sync --frozen
uv run --frozen python scripts/dashboard_setup.py --output .dashboard.env
```

生成スクリプトは秘密の値を端末に表示せず、既存ファイルを上書きしません。`.dashboard.env` を自分のPC上のエディターで開き、ログイン用パスワードと設定項目を確認します。チャットやGitHubへ貼り付けないでください。

| 変数 | 用途 |
| --- | --- |
| `DASHBOARD_PASSWORD` | ブラウザーのログイン用。12文字以上 |
| `ANKI_UPLOAD_TOKEN` | コネクターからの送信用。32文字以上。ログイン用とは別 |
| `DASHBOARD_ENCRYPTION_KEY` | Fernet形式のデータ暗号化キー。生成済みの値を保管 |
| `DASHBOARD_PUBLIC_URL` | オンライン公開先のHTTPSオリジン（例：`https://YOUR-SERVICE.onrender.com`）。HTTPS終端プロキシ利用時のログイン・Cookieに必要。ローカルでは省略可 |
| `DASHBOARD_DATA_DIR` | 保存先。ローカルの初期値は `.dashboard-data` |
| `TZ` | 初期値 `Asia/Tokyo` |
| `ANKI_CONNECT_API_KEY` | PC上だけで設定。AnkiConnectに設定したAPIキーと同じ値 |

最後の `ANKI_CONNECT_API_KEY` は生成されません。`.dashboard.env` に追加してください。このキーをクラウド側へ渡す必要はありません。Windowsでは秘密ファイルを自分のアカウントだけが読めるようアクセス権を設定してください。

ローカルで画面とログインを確認する場合は次を実行し、PCのブラウザーでポート8000を開きます。

```sh
uv run --frozen --env-file .dashboard.env uvicorn dashboard:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

## 3. GitHubとオンライン公開

**GitHubへのソース公開と、個人データを扱うWebアプリの稼働先は別です。** GitHub Pagesは静的ファイルだけを配信し、Pythonサーバーや暗号化データ保存先を実行できません。

- GitHubの公開リポジトリへ置くもの：ソース、テスト、説明書。
- 公開リポジトリへ置かないもの：`.dashboard.env`、Ankiのコレクション、バックアップ、`.dashboard-data`、アップロード済みのデータ。
- 個人データを扱う本体：HTTPS対応のPython/Dockerホストで実行します。外部から使うときは必ずHTTPSのURLを使います。
- 静的な画面デモ：`web/` の内容だけをGitHub Pagesなどへ配信できます。公開URLに `?demo=1` を付けるとサンプルデータを表示します。自分のデータの同期にはサーバーが必要です。

`.github/workflows/dashboard.yml` はコードの検証用です。このワークフローだけでは公開やデプロイは行いません。

静的デモを公開する場合は、アプリのソースと `.github/workflows/pages-demo.yml` をGitHubのデフォルトブランチに置きます。リポジトリの「Settings → Pages → Build and deployment → Source」で **GitHub Actions** を選び、「Actions → Deploy static dashboard demo → Run workflow」で公開するソースのブランチを選んで手動実行します。自動公開は行いません。配信するのは `web/` だけです。完了後のPages URLに `?demo=1` を付けて開いてください。URLに指定がない場合はログイン画面が表示されますが、Pagesでは個人データ用のPython APIは動作しません。

### Pythonサービスとして配置する例：Render

既存の `render.yaml` はChatGPT向けMCPサービス用です。ダッシュボード用には無料プランの `render-dashboard.yaml` を用意しています。Renderで新しいBlueprintを作成し、GitHub上のアプリのソースがあるリポジトリとブランチ、Blueprintのパス `render-dashboard.yaml` を指定します。既存MCPサービスとは別のサービスが作成されます。手動で別のWeb Serviceを作る場合は、次の設定を使います。

```text
Runtime: Python
Python Version: 3.12.14
Build Command: pip install --require-hashes -r requirements.txt
Start Command: uvicorn dashboard:app --host 0.0.0.0 --port $PORT --workers 1 --no-access-log
Health Check Path: /api/health
```

サービスの秘密の環境変数に、ローカルで生成した `DASHBOARD_PASSWORD`、`ANKI_UPLOAD_TOKEN`、`DASHBOARD_ENCRYPTION_KEY` を設定し、`TZ=Asia/Tokyo` を指定します。割り当てられたHTTPS URLを `DASHBOARD_PUBLIC_URL` に設定してください。末尾のパスは含めません。値を公開された設定ファイルに書き込まないでください。

`render-dashboard.yaml` はこの3つの秘密をRender側で入力する設定です。有料ディスクや有料サービスは定義していません。保存先は無料プランの一時領域なので、消失後はPCから再送してください。自動デプロイは無効です。

保存先には次の違いがあります。

| 保存方法 | 設定と性質 |
| --- | --- |
| Freeの一時ファイル領域 | `DASHBOARD_DATA_DIR=.dashboard-data`。再起動・再デプロイなどでスナップショットが失われる可能性があります。PCから再送すれば復元できます |
| 永続ディスク対応のホスト | ディスクを `/data` に接続し、`DASHBOARD_DATA_DIR=/data`。Renderの永続ディスクは有料です。プランと費用を確認して自分で選択してください |

無料サービスは休止や制限があるため、PCが停止している間の継続閲覧を保証しません。永続化できるホストと保存先を用意した場合は、PC停止中も最後に受信したデータを閲覧できます。

### Dockerで配置する場合

`Dockerfile.dashboard` を使います。次の例はホスト内のポート8000にだけ公開するので、HTTPS対応のリバースプロキシまたはホスティングサービスから接続します。

```sh
docker build -f Dockerfile.dashboard -t anki-dashboard .
docker volume create anki-dashboard-data
docker run -d --name anki-dashboard --restart unless-stopped \
  --env-file .dashboard.env \
  -e DASHBOARD_DATA_DIR=/data \
  -e DASHBOARD_PUBLIC_URL=https://YOUR-DASHBOARD.example \
  -p 127.0.0.1:8000:8000 \
  -v anki-dashboard-data:/data \
  anki-dashboard
```

複数ワーカーや複数インスタンスで同じファイルを共有する構成には対応していません。`--workers 1` で動かしてください。

## 4. PCから自分のカードを送信する

クラウドの起動後、Web画面で `.dashboard.env` の `DASHBOARD_PASSWORD` を使ってログインします。初回はまだカードがない状態です。

Ankiを開いたPCで、次を実行します。`https://YOUR-DASHBOARD.example` は実際のHTTPS URLへ置き換えます。

```sh
uv run --frozen --env-file .dashboard.env python connector.py \
  --server https://YOUR-DASHBOARD.example \
  --token-env ANKI_UPLOAD_TOKEN \
  --api-key-env ANKI_CONNECT_API_KEY \
  --timezone Asia/Tokyo
```

継続して取り込みたい場合は `--watch 300` を追加すると、PCとAnkiが動作している間は300秒ごとに送信します。間隔は30秒以上にしてください。特定のプロファイルに限定する場合は `--profile "自分のプロファイル名"` も追加します。AnkiConnectのAPIキーとアップロード用トークンは環境変数から読み込み、コマンド引数へ直接書きません。

送信後、Web画面で自分のプロファイル、カード、タグ、最終同期日時を確認します。元のAnkiでカードや学習履歴があることも確認してください。`/api/health` の成功だけではAnki接続・データ送信の成功を確認できません。

## PCのスリープ中の動作

AnkiConnectはデスクトップ版Ankiのアドオンなので、PCのスリープ中やAnki終了中は新しいデータを読み取れません。クラウドは最後に受信したデータを表示し、次にPCが復帰してコネクターが送信すると更新します。スマートフォンで学習した直後の履歴も、PCのAnkiへ通常同期してから送信する必要があります。

PCが停止していてもAnkiWebから直接取り込む自動同期は、このダッシュボードには実装していません。リポジトリ内の既存MCPサービスにあるAnkiWeb同期は別機能で、このダッシュボードの自動同期には接続していません。

## 成績の読み方

正解率は、Ankiの回答評価を基に集計する指標です。「もう一度」を不正解、「難しい・普通・簡単」を正解として扱うため、試験の正答率や、カード内容をAIが採点した結果ではありません。スケジュールの変更など学習回答ではない履歴は除外します。未回答のカードは履歴なしとして表示します。

学習時間はAnkiの復習履歴に記録された回答時間の合計です。Ankiを開いていた総時間や、アプリの閲覧時間ではありません。Ankiの回答時間の上限設定や、記録のない過去の学習は反映できません。日付は画面の「接続・設定」で選んだタイムゾーン（初期値は日本）で区切ります。コネクターの `--timezone` は送信元の情報として保存されます。

## バックアップと動作確認

保存ファイルは `DASHBOARD_DATA_DIR/snapshot.fernet` です。このファイルと暗号化キーを別々の安全な場所へ保管します。暗号化キーを失うと保存済みデータを復号できません。PCに元のAnkiが残っている場合は、新しいキーで起動して再送できます。

アップロードは最大32 MiB、カードは50,000枚、復習履歴は1,000,000件までです。上限を超えたデータは切り捨てず拒否されます。必要に応じてコネクターに `--query 'tag:英語'` などのAnki検索条件を付け、送信対象を絞ってください。保存するのは最新のスナップショット1つで、複数プロファイルのデータは合算しません。暗号化して保存しますが、表示や処理のためにサーバー上では復号するので、信頼できる運営先へ配置してください。

開発時の確認コマンドです。外部のAnkiWebアカウントを使う操作は含みません。

```sh
uv sync --frozen
uv run --frozen pytest -q
node --check web/app.js
node --check web/stats.mjs
node --test tests/stats.test.mjs
```

自分のPCとの実接続では、Ankiを起動 → 1回送信 → Webでタグと成績を確認 → サーバー再起動後に再確認、の順で検証します。デモの表示成功は、自分のアカウントとの同期成功を意味しません。

今回の検証結果と未検証の範囲は [DASHBOARD_VERIFICATION.md](DASHBOARD_VERIFICATION.md) に記録しています。
