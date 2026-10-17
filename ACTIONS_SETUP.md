# GitHub Actions＋Pagesで自動更新する

**Renderや別のサーバー契約は不要**です。ActionsがAnkiWebのカード・タグ・履歴・参照画像を読み取り、暗号化してPagesへ配信します。閲覧パスワードはブラウザー内の復号に使います。

## 404で開けない場合

初回だけ **Actions → Publish initial app screen → Run workflow** で、認証情報なしでアプリ画面を公開できます。Anki接続前であることを表示し、デモを利用できます。この処理は既存の暗号化データがある場合や公開状態を確認できない場合には停止し、実データを上書きしません。

実データを表示するには、以下の認証情報を登録して **Publish encrypted Anki Pages** を実行してください。初期画面の公開だけではAnkiの接続・定期同期は有効になりません。

## 運用開始までの残りの設定

コードは `main` から利用できます。リポジトリの公開とPagesの配信元設定（GitHub Actions）は確認済みです。実データの初回公開・認証情報の登録・定期更新の有効化は、GitHub側で確認してください。

1. [Pages設定](https://github.com/kenken49-2401/anki-synchronizer/settings/pages)の配信元 **GitHub Actions** は設定済みです。再設定時は同じ値を選んでください。
2. 自分のPCで以下の手順2を実行し、閲覧パスワードとAnkiWebトークンを作る。
3. [Environments設定](https://github.com/kenken49-2401/anki-synchronizer/settings/environments)で `anki-sync` を作り、手順3のSecretsを登録する。
4. [公開ワークフロー](https://github.com/kenken49-2401/anki-synchronizer/actions/workflows/ankiweb-refresh.yml)を `source=ankiweb` で手動実行し、公開画面を確認する。
5. [Actions Variables](https://github.com/kenken49-2401/anki-synchronizer/settings/variables/actions)に `ANKI_AUTO_SYNC_ENABLED=true` を登録する。これで毎時のタグ確認も動きます。タグの書き戻しだけ止める場合は `ANKI_TAG_IMPORT_ENABLED=false` を追加します。

クラウド環境のGitHub連携ではSecrets・Variablesの確認と設定APIが403で拒否されました。コード変更と自動テストは行えますが、認証情報の登録と `ANKI_AUTO_SYNC_ENABLED=true` の設定はGitHub画面で行ってください。秘密の値をチャットへ送る必要はありません。

## 1. コードをmainへ反映し、Pagesを有効にする

1. デフォルトブランチの `main` を使います。今後の変更を別ブランチで作る場合は、公開前に `main` へ反映してください。
2. リポジトリの **Settings → Pages → Build and deployment → Source** を **GitHub Actions** にします。
3. GitHub Freeでの標準のPages公開は公開リポジトリを使います。公開されるデータは暗号文です。アカウントのプラン条件はGitHubで確認してください。

手動実行と定期実行は、ワークフローがデフォルトブランチへ置かれてから利用します。旧デモ専用ワークフローは新構成へ統合しました。画面だけのデモは公開URLに `?demo=1` を付けると表示できます。

## 2. PCで閲覧パスワードとAnkiWebトークンを作る

[DASHBOARD.mdの手順1・2](DASHBOARD.md) に従ってPython 3.12とuvを用意し、リポジトリで実行します。

```sh
uv sync --frozen
uv run --frozen python scripts/pages_setup.py
uv run --frozen python scripts/ankiweb_token.py
```

- `.pages.env` に **`PAGES_PASSWORD`** が作られます。既存ファイルは上書きしません。
- トークン取得時にメールアドレスとAnkiWebパスワードをPCで入力します。パスワードは非表示で、保存しません。
- **`secrets.env`** に `ANKIWEB_HKEY` と `ANKIWEB_ENDPOINT` が作られます。既存ファイルは上書きしません。

PCのエディターでファイルを開き、次のGitHub設定へ値だけを移します。ファイルをコミットしたり、チャットやログへ値を貼ったりしないでください。AnkiWebのパスワードそのものはGitHubへ登録しません。Windowsでは自分だけが読めるファイルアクセス権も設定します。

以前のサーバー方式の `DASHBOARD_PASSWORD`、`ANKI_UPLOAD_TOKEN`、`DASHBOARD_ENCRYPTION_KEY`、`DASHBOARD_URL`、Render設定は新構成では不要です。値は以下のGitHub Secretsへ設定します。

## 3. GitHub Secretsを設定する

**Settings → Environments** で **`anki-sync`** を作り、**Environment secrets** に登録します。無人実行する場合はRequired reviewersを設定しません。

| Secret名 | 値 |
| --- | --- |
| `PAGES_PASSWORD` | `.pages.env` の同名の値。閲覧時にも使う強いランダムなパスワード |
| `ANKIWEB_HKEY` | `secrets.env` の同名の値 |
| `ANKIWEB_ENDPOINT` | `secrets.env` に値がある場合のみ。空なら省略 |

GitHubのプランによってEnvironmentの利用条件が異なります。Environmentを利用できない場合は同名のRepository secretsを登録してもジョブから読み取れますが、GitHub Pages自体を利用できる公開範囲・プランが前提です。

環境に鍵を登録しただけでは更新は始まりません。トークンは読み取り専用権限のトークンではないため秘密にし、リポジトリの書き込み権限は信頼できる人だけに与えてください。通常の公開処理は読み取り専用です。後述のタグ取り込みが有効で、所有者の未処理リクエストがある場合だけ、所有者がGitHubで送信を確定したタグ追加を通常の差分同期でAnkiWebへ反映します。全量アップロード・削除・回答記録・メディアの書き込みは行いません。

## 4. 手動更新を確認する

**Actions → Publish encrypted Anki Pages → Run workflow** を開きます。

- `source` は **`ankiweb`** を選びます。
- `discard_previous` は通常 **false** のままです。

初回は既存データがない404を許容して作成します。以後は前回の暗号文を読み取り、パスワードや整合性が一致しない場合に上書きを止めます。Pages URLはGitHubから自動取得するので、送信先URLや送信用トークンの設定はありません。

成功するとPagesの公開URLが表示されます。ブラウザーで開き、**`PAGES_PASSWORD` の値**で復号してください。自分のカード・図・タグ・統計・最終受信日時を確認します。手元のAnkiやスマートフォンで学習した後は、AnkiWebへの通常同期を済ませてからもう一度実行すると、PCを停止したまま更新を確認できます。

画像もAnkiのメディアサーバーから読み取ります。PNG/JPEG/GIF/WebPが対象で、双方向のメディア同期やアップロードは実行しません。AnkiWeb未同期・未対応形式・欠損した画像は表示できません。取得失敗時には公開を止め、前のサイトを維持します。

PCのAnkiConnectから作った `pages-data/snapshot.enc.json` を使う場合だけ **`source=seed`** を選びます。この場合はAnkiWebトークンが不要で、`PAGES_PASSWORD` だけで手動公開できます。作成方法は [DASHBOARD.md](DASHBOARD.md) にあります。

## 5. 1時間ごとの自動更新を有効にする

手動成功後、**Settings → Secrets and variables → Actions → Variables → Repository variables** に登録します。

| Variable名 | 値 |
| --- | --- |
| `ANKI_AUTO_SYNC_ENABLED` | 小文字の **`true`**。毎時の公開・確認処理を有効化 |
| `ANKI_TAG_IMPORT_ENABLED` | 任意。省略時は **`true`** として本人送信のタグを確認。**`false`** で書き戻し停止 |
| `ANKI_TIMEZONE` | 任意。日本なら `Asia/Tokyo`。省略時も同じ |

未設定・falseでは定期実行をスキップします。手動実行はこの変数に関係なく、明示的な操作として実行できます。デフォルトブランチへ暗号化シードをpushした場合も、有効化済みならAnkiWeb更新が動きます。

予定は `17 * * * *`（UTC）。日本時間でも **毎時17分** です。毎回、許可された未処理タグ変更を先に確認・反映し、その後にカード・統計・画像を暗号化して公開します。未処理変更がなければ読み取り・公開だけです。GitHubの混雑などによる遅延・欠落があり、時刻は保証されません。公開リポジトリでは60日間活動がないと定期実行が停止する場合があります。

公開リポジトリの標準ランナーは無料で利用できます。非公開リポジトリではプランの無料実行分数を消費します。1回5分なら毎時実行で30日約3,600分です。他の実行も含めて利用量を確認し、有料実行の予算は設定しないでください。Pages配信物は公開アセットと暗号文のみで、平文のコレクション・画像・パスワードはartifactやキャッシュへ保存しません。

## 6. スマホからタグをAnkiWebへ戻す

前提：上のPages・Secrets設定と、**`ANKI_AUTO_SYNC_ENABLED=true`** を設定します。`ANKI_TAG_IMPORT_ENABLED` は省略可能で、停止時だけ `false` にします。リポジトリの **Settings → General → Features → Issues** も有効にしてください。個人所有リポジトリを対象とし、受け付けるのはリポジトリ所有者本人が作成したIssueだけです。

1. スマホのAnkiで同期し、学習内容・編集をAnkiWebへ送ります。
2. Pagesのアプリでカードにタグを付け、**スマホから送信** を押します。
3. **GitHubで送信を確定** を開き、リポジトリ所有者のアカウントでログインし、**Create issue** を押します。小さい変更は暗号文が入力済みです。大きい場合は画面の「暗号化データをコピー」を押して、GitHubの本文へ貼り付けます。タイトル・暗号文の内容は変更しません。
4. 毎時のActionsが未処理のIssueを確認します。暗号文を復号し、AnkiWeb上のノートのID・カード対応・本文の指紋を照合して、足りないタグだけを追加します。追加後は通常の差分同期を行い、さらにAnkiWebから読み直して反映を確認します。
5. 成功したIssueには完了メッセージが付き、閉じられます。その後、**スマホのAnkiで同期** を押すとタグを受け取れます。PCの起動・AnkiConnectは不要です。
6. 後続のPages公開が成功したら、アプリの **表示を更新** で新しいタグが表示されます。反映済みのタグだけ下書きから自動で外れます。

GitHubのIssueは暗号化された変更の受け付けに使います。平文のカード・タグ・パスワードを送信せず、ブラウザーにGitHubトークンやAnkiWebトークンを保存しません。Actionsの `GITHUB_TOKEN` はジョブ実行時だけ発行され、同じリポジトリのIssue読み書きに使います。新しい個人アクセストークンや外部サーバーは不要です。公開リポジトリでは、暗号文・Issueの存在・時刻・送信者は公開されます。

取り込みは1回につき最大5リクエストです。超過分は次回に回ります。送信前にスマホのAnkiを同期し、Actions処理中は同じノートの本文・タグ・ノートタイプを別端末で編集しないでください。通常のAnki同期の競合解決が適用され、同じノートの同時編集を原子的にマージする保証はありません。本文が既に変わっている場合は指紋の照合で停止します。全体同期が必要な場合は全量アップロードを選択せず停止し、Anki本体で解決してから再試行してください。

- **確認**：GitHubのIssuesで自分が送った `[Anki Atlas] Encrypted tag update` を確認します。Actionsの手動実行（source=ankiweb）でも未処理分を確認できます。source=seedでは書き戻しません。
- **取り消し**：処理開始前に該当Issueを閉じます。アプリの「下書きを取り消す」は端末内の下書きだけを削除し、送信済みIssueは取り消しません。処理済みのタグを自動で削除する機能はありません。
- **要確認**：暗号文やノート照合に問題があるとIssueのタイトルが `Tag update needs attention` に変わり、自動再試行の対象から外れます。最新データでタグを付け直し、新しいIssueを送ってください。
- **一時障害**：通信失敗や同期結果が不明な場合はIssueを保留し、次回に再試行します。反映済みのタグは重複追加しません。Pages公開だけが失敗した場合、AnkiWebへの反映が先に完了している場合があります。IssueとスマホAnkiの同期で確認してください。
- **停止**：`ANKI_TAG_IMPORT_ENABLED=false` で書き戻しだけを停止できます。公開更新全体は `ANKI_AUTO_SYNC_ENABLED=false` で停止します。

## 変更・停止・復旧

**アプリのコード更新**：mainの `web/` や公開処理のコードが更新されると、自動更新が有効な場合はpushでも再公開します。ブラウザー・iPhoneのホーム画面版は新しい公開版を検知して更新し、PCランチャーは起動時にmainを取得します。[UPDATES.md](UPDATES.md) を参照してください。

- **停止**：`ANKI_AUTO_SYNC_ENABLED=false` にするかワークフローを無効化します。
- **失敗**：Actionsのステップを確認します。トークン、閲覧パスワード、AnkiWebの互換性、サイズ制限、Pages設定を確認してください。失敗したビルドは公開されず、前のサイトが残ります。
- **パスワード変更**：新しい強い値を `PAGES_PASSWORD` に設定し、`source=ankiweb`、`discard_previous=true` で手動実行します。古い暗号化シードを使わず、AnkiWebからカード・画像を再取得します。ローカルの `.pages.env` も同じ値へ更新し、古いシードは再取り込みして作り直してください。過去のGit履歴・第三者が保存した暗号文は、古いパスワードで引き続き復号可能な点に注意してください。
- **完全な再公開**：AnkiWebかローカル取り込みが元データです。パスワードを失った既存暗号文は復号できませんが、新しいパスワードで元データを再取得できます。
- **画像サーバーを使わない例外**：ローカルの `pages_site.py --cached-media-only` は前回／シードの画像を再利用します。この場合だけ、新規・同名変更の図はPCからの再取り込みが必要です。通常のActionsはこのオプションを使いません。

暗号文からカード数・プロフィール名などを平文で公開するメタデータは作りません。ただしファイルサイズや更新時刻は公開配信から分かります。通常の公開は読み取り専用です。タグ取り込みを有効にすると、アプリからGitHubで送信を確定したタグ追加をActionsがAnkiWebへ反映します。PCで暗号化ファイルを取り込み、明示的に同期する方法も使えます。[DASHBOARD.mdの逆取り込み手順](DASHBOARD.md#追加したタグをankiへ戻す)を参照してください。GitHub Secretsの追加は不要です。答えの開閉や閲覧はAnkiの回答履歴に記録しません。

実装の追加だけで外部サービスは有効になりません。コードのmain反映、Pages設定、Secretsの登録、手動成功確認、変数による有効化を行ってください。実アカウントとGitHub上での実行はこれらの設定後の確認事項です。

## 公開が失敗する場合の診断

Actionsの実行詳細に `Anki Pages progress` と `Anki Pages diagnostic` が表示されます。カード本文・認証情報を含まず、失敗した工程と安全な分類だけを示します。AnkiWebへの接続では先に読み取り専用のサーバー確認を行い、アカウントのコレクションサーバーへダウンロードします。カードごとの重複CSSは省き、大量の画像は別の暗号化パッケージに分割します。

画像は10,000個・各2 MiB・合計128 MiBまでです。初回は画像のダウンロードに数分かかることがあります。公開ジョブ全体の上限は15分で、失敗したビルドは配信中のサイトを置き換えません。
