# PCを止めたままAnkiWebからダッシュボードを更新する

GitHub Actionsの一時的なLinuxランナーがAnkiWebからカードと復習履歴をダウンロードし、認証付きダッシュボードへ送信します。PCやデスクトップ版Ankiの常時起動は不要です。スマートフォンで学習した後は、スマートフォン側でAnkiWebへの同期を済ませてください。AnkiWebへ届いていない履歴は取り込めません。

```text
スマートフォン / PCのAnki → 通常のAnkiWeb同期
                                  ↓
                        GitHub Actions（一時ランナー）
                                  ↓ HTTPS・送信専用トークン
                        自分のダッシュボード → ログインして閲覧
```

`cloud_sync.py` はAnkiWebのコレクションを読み取るためのワーカーです。カード編集や復習回答をAnkiWebへ書き込む処理はありません。AnkiWebのトークン自体は読み取り専用の権限ではないため、秘密情報として扱ってください。従来の `connector.py` はPCでAnkiConnectが動作している間だけ使える別の取り込み方法です。

## 1. 個人用ダッシュボードを公開する

[DASHBOARD.md](DASHBOARD.md) の手順で、`render-dashboard.yaml` を使ってダッシュボードを配置します。RenderはFreeを選び、有料ディスク・有料プラン・支払い方法を追加する必要はありません。自動デプロイは無効なので、今回のコードを反映するにはRender側で手動デプロイします。

Renderに `DASHBOARD_PASSWORD`、`ANKI_UPLOAD_TOKEN`、`DASHBOARD_ENCRYPTION_KEY` を秘密の環境変数として設定し、割り当てられたHTTPSオリジンを `DASHBOARD_PUBLIC_URL` に設定します。例は `https://YOUR-SERVICE.onrender.com` で、末尾にパスを付けません。ブラウザーでログインできることを確認してください。静的なGitHub Pagesのデモは取り込み先として使えません。

Render Freeは無通信時に休止し、次の送信や閲覧で起動待ちになる場合があります。無料の一時ファイル領域が失われた場合も、次の自動更新または手動実行でAnkiWebから再送できます。常時稼働や永続保存は保証されません。今回の定期実行は新しいデータを反映するためのもので、休止回避だけの定期アクセスは行いません。

## 2. 手元のPCでAnkiWebトークンを取得する

まずPCまたはスマートフォンのAnkiをAnkiWebへ同期し、既存のバックアップを確保してください。Python 3.12と [uv](https://docs.astral.sh/uv/) を入れたPCで、このリポジトリのルートから実行します。

```sh
uv sync --frozen
uv run --frozen python scripts/ankiweb_token.py
```

メールアドレスとAnkiWebパスワードを対話入力します。パスワードは非表示入力で、保存・表示しません。トークンと任意の接続先が `secrets.env` に保存されます。Unixでは所有者だけが読める権限（0600）で作成し、既存ファイルは上書きしません。Windowsでは自分だけが読めるファイルアクセス権も設定してください。

`secrets.env` をPC上のエディターで開き、次のGitHub設定へ値だけをコピーします。`ANKIWEB_HKEY=` などの名前部分は含めません。ファイル・パスワード・トークンをチャット、Git、Issue、Actionsログへ貼らないでください。設定後はローカルの `secrets.env` を削除するか、安全な保管先へ移します。スクリプトの案内文にはRenderとありますが、この用途ではGitHubのEnvironment secretsへ設定します。AnkiWebパスワードをGitHubへ設定する必要はありません。

## 3. GitHubのEnvironment secretsを設定する

リポジトリの **Settings → Environments → New environment** で、名前を正確に **`anki-sync`** として作成します。GitHubのプランやリポジトリの公開範囲によってEnvironmentの利用条件が異なるので、設定できることを確認してください。無人実行するため、実行ごとの承認を必要とするRequired reviewersは設定しません。

このEnvironmentの **Environment secrets → Add environment secret** に以下を登録します。

| Secret名 | 値 |
| --- | --- |
| `ANKIWEB_HKEY` | 手元で作った `secrets.env` の同名の値 |
| `ANKIWEB_ENDPOINT` | `secrets.env` に値がある場合だけ登録。空の場合は省略可 |
| `ANKI_UPLOAD_TOKEN` | Renderに設定した送信専用トークンと完全に同じ値 |

`DASHBOARD_PASSWORD` と `DASHBOARD_ENCRYPTION_KEY` はRender側に保持します。AnkiConnectのAPIキーもActionsには不要です。Environmentへのアクセスを許可するブランチは、必要なデフォルトブランチと手動検証用ブランチに限定できます。リポジトリへ書き込める人はワークフローを変更できるため、ソースが公開でも書き込み権限を信頼できる人に限定してください。

## 4. Repository variablesで有効化する

**Settings → Secrets and variables → Actions → Variables → New repository variable** から登録します。SecretsタブやEnvironment variablesではなく、**Repository variables** を使用してください。ジョブの有効・無効はEnvironmentに入る前にこの値で判定します。

| Variable名 | 値 |
| --- | --- |
| `DASHBOARD_URL` | Renderに割り当てられたHTTPSオリジン。例：`https://YOUR-SERVICE.onrender.com`。末尾パスなし |
| `ANKI_TIMEZONE` | 任意。日本なら `Asia/Tokyo`。省略時も `Asia/Tokyo` |
| `ANKI_AUTO_SYNC_ENABLED` | 準備完了後に小文字で `true`。未設定・別の値ではジョブをスキップ |

これらは秘密でない設定値です。トークンはVariablesへ入れず、手順3のEnvironment secretsへ入れます。`DASHBOARD_URL` は個人データを受け取る自分のサーバーのURLなので、ホスト名を確認してから有効化してください。

## 5. 手動実行で確認してから定期運用する

`.github/workflows/ankiweb-refresh.yml` と関連コードをGitHubのデフォルトブランチへ反映します。GitHubでは手動実行の `workflow_dispatch` も、ワークフローがデフォルトブランチに置かれてから表示されます。

1. **Actions → Refresh dashboard from AnkiWeb → Run workflow** を開き、反映済みのブランチを選んで実行します。
2. ジョブがスキップされた場合は、Repository variable `ANKI_AUTO_SYNC_ENABLED=true` を確認します。
3. 実行成功後にダッシュボードへログインし、カード・タグ・学習履歴と最終同期日時が更新されたことを確認します。ヘルスチェックの成功だけでは同期成功を確認できません。
4. スマートフォンで学習してAnkiWebへ同期した後、もう一度手動実行して履歴が反映されることを確認します。PCは停止したままで構いません。

ワークフローはPull requestでは実行せず、GitHubリポジトリへの書き込み権限も要求しません。定期・手動実行は同じconcurrency groupを使い、実行中の同期を途中でキャンセルしません。コレクションやトークンをActions artifactsへ保存しません。uvの依存パッケージ用キャッシュだけを使用します。

## 更新間隔と無料枠

初期設定は `17 */3 * * *` で、UTCの3時間ごとの17分です。日本時間では **02:17、05:17、08:17、11:17、14:17、17:17、20:17、23:17** が予定時刻です。定期実行はデフォルトブランチのコードを使います。GitHubの混雑などで遅延や実行の欠落があり、時刻・更新間隔は保証されません。公開リポジトリでは60日間活動がないと定期実行が自動停止することもあります。

公開リポジトリの標準GitHubホストランナーは無料で利用できます。個人データやSecretsはソースとして公開せず、一時ランナーと自分のサーバーで処理します。プライベートリポジトリは契約ごとのActions無料分数を消費するため、**Settings → Billing and licensing** など現在の利用量・予算画面を確認し、有料実行を許可する予算は設定しないでください。費用条件が変わった場合は停止してください。

例えば1回5分なら、3時間ごとで30日間に約240回・1,200分です。毎時に変更すると約720回・3,600分となり、2,000分の無料枠では収まりません。他のワークフローや実際の起動時間も消費に含まれます。この例は実測や無料保証ではありません。頻度を上げる場合だけ、予算を確認した上でcronを `17 * * * *` に変更します。

停止するときはRepository variable `ANKI_AUTO_SYNC_ENABLED` を `false` にするか、Actions画面でワークフローを無効化します。不要になったSecretsも削除してください。

## 失敗したとき

- 認証に失敗する場合：PCでAnkiWebへログインできることを確認し、必要ならトークンを再取得してEnvironment secretsを更新します。値をログへ出して診断しないでください。
- 送信に失敗する場合：`DASHBOARD_URL` とRenderの稼働状態、両側の `ANKI_UPLOAD_TOKEN` が一致することを確認します。休止からの起動待ちの場合は起動後に手動実行します。
- データが古い場合：まず学習した端末でAnkiWebへ同期し、Actionsの最終成功日時を確認します。
- 大きなコレクションなどで制限を超えた場合：エラーを確認し、安易に上限を引き上げたり有料プランを追加したりせず、取り込み対象と頻度を見直します。

この説明書とワークフローの追加だけでは外部サービスのデプロイや定期実行は開始しません。デフォルトブランチへの反映、Renderの設定、GitHubのSecretsと明示的な有効化が必要です。実際のAnkiWebアカウントとの接続と、公開先への送信は設定後に確認してください。

公式仕様：[定期実行](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)、[手動実行](https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-workflow-runs/manually-running-a-workflow)、[Environment](https://docs.github.com/en/actions/deployment/targeting-different-environments/managing-environments-for-deployment)、[Actionsの課金](https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-actions/about-billing-for-github-actions)、[Render Free](https://render.com/docs/free)。

## 図・化学式の表示

カードの下付き・上付き文字、表、太字などは安全な形式へ変換して表示します。添付図はPNG/JPEG/GIF/WebPに対応し、ログイン後だけ取得できます。スクリプト、外部画像URL、SVGは読み込みません。添付図はカードと一緒に暗号化して保存します。

AnkiWeb側の通常のメディア同期は双方向のため、この読み取り専用ワーカーでは実行しません。**新しい図は一度PCの `connector.py --server …` で取り込んでください**（画像は初期設定で含まれます）。その後のActions更新では、同じファイル名が参照される間は取り込み済みの図を保持します。同じ名前の図を編集した場合もPCから再送してください。未取得の図は「画像未取得」と表示します。文章・タグ・復習履歴はPC停止中もAnkiWebから更新できます。
