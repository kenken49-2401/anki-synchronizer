# GitHub Actions＋Pagesで自動更新する

**Renderや別のサーバー契約は不要**です。ActionsがAnkiWebのカード・タグ・履歴・参照画像を読み取り、暗号化してPagesへ配信します。閲覧パスワードはブラウザー内の復号に使います。

## 運用開始までの残りの設定

コードは `main` から利用できます。実アカウントの認証情報、Pages公開、定期更新はまだ有効になっていません。

1. [Pages設定](https://github.com/kenken49-2401/anki-synchronizer/settings/pages)で配信元を **GitHub Actions** にする。現在のリポジトリは非公開です。非公開Pagesに対応するプランが必要です。無料の公開リポジトリ方式を選ぶ場合は、公開範囲と履歴を確認してから変更してください。
2. 自分のPCで以下の手順2を実行し、閲覧パスワードとAnkiWebトークンを作る。
3. [Environments設定](https://github.com/kenken49-2401/anki-synchronizer/settings/environments)で `anki-sync` を作り、手順3のSecretsを登録する。
4. [公開ワークフロー](https://github.com/kenken49-2401/anki-synchronizer/actions/workflows/ankiweb-refresh.yml)を `source=ankiweb` で手動実行し、公開画面を確認する。
5. [Actions Variables](https://github.com/kenken49-2401/anki-synchronizer/settings/variables/actions)に `ANKI_AUTO_SYNC_ENABLED=true` を登録する。

クラウド環境のGitHub連携には設定APIの権限がなく、Pages・Environment・Secretsの操作は403で拒否されました。設定はGitHub画面で行ってください。秘密の値をチャットへ送る必要はありません。

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

環境に鍵を登録しただけでは更新は始まりません。トークンは読み取り専用権限のトークンではないため秘密にし、リポジトリの書き込み権限は信頼できる人だけに与えてください。本ワーカーは通常同期・アップロード・削除APIを呼びません。

## 4. 手動更新を確認する

**Actions → Publish encrypted Anki Pages → Run workflow** を開きます。

- `source` は **`ankiweb`** を選びます。
- `discard_previous` は通常 **false** のままです。

初回は既存データがない404を許容して作成します。以後は前回の暗号文を読み取り、パスワードや整合性が一致しない場合に上書きを止めます。Pages URLはGitHubから自動取得するので、送信先URLや送信用トークンの設定はありません。

成功するとPagesの公開URLが表示されます。ブラウザーで開き、**`PAGES_PASSWORD` の値**で復号してください。自分のカード・図・タグ・統計・最終受信日時を確認します。手元のAnkiやスマートフォンで学習した後は、AnkiWebへの通常同期を済ませてからもう一度実行すると、PCを停止したまま更新を確認できます。

画像もAnkiのメディアサーバーから読み取ります。PNG/JPEG/GIF/WebPが対象で、双方向のメディア同期やアップロードは実行しません。AnkiWeb未同期・未対応形式・欠損した画像は表示できません。取得失敗時には公開を止め、前のサイトを維持します。

PCのAnkiConnectから作った `pages-data/snapshot.enc.json` を使う場合だけ **`source=seed`** を選びます。この場合はAnkiWebトークンが不要で、`PAGES_PASSWORD` だけで手動公開できます。作成方法は [DASHBOARD.md](DASHBOARD.md) にあります。

## 5. 3時間ごとの自動更新を有効にする

手動成功後、**Settings → Secrets and variables → Actions → Variables → Repository variables** に登録します。

| Variable名 | 値 |
| --- | --- |
| `ANKI_AUTO_SYNC_ENABLED` | 小文字の **`true`** |
| `ANKI_TIMEZONE` | 任意。日本なら `Asia/Tokyo`。省略時も同じ |

未設定・falseでは定期実行をスキップします。手動実行はこの変数に関係なく、明示的な操作として実行できます。デフォルトブランチへ暗号化シードをpushした場合も、有効化済みならAnkiWeb更新が動きます。

予定は `17 */3 * * *`（UTC）。日本時間では **02:17 / 05:17 / 08:17 / 11:17 / 14:17 / 17:17 / 20:17 / 23:17** です。GitHubの混雑などによる遅延・欠落があり、時刻は保証されません。公開リポジトリでは60日間活動がないと定期実行が停止する場合があります。

公開リポジトリの標準ランナーは無料で利用できます。非公開リポジトリではプランの無料実行分数を消費します。1回5分なら3時間ごとで30日約1,200分、毎時では約3,600分です。他の実行も含めて利用量を確認し、有料実行の予算は設定しないでください。Pages配信物は公開アセットと暗号文のみで、平文のコレクション・画像・パスワードはartifactやキャッシュへ保存しません。

## 変更・停止・復旧

- **停止**：`ANKI_AUTO_SYNC_ENABLED=false` にするかワークフローを無効化します。
- **失敗**：Actionsのステップを確認します。トークン、閲覧パスワード、AnkiWebの互換性、サイズ制限、Pages設定を確認してください。失敗したビルドは公開されず、前のサイトが残ります。
- **パスワード変更**：新しい強い値を `PAGES_PASSWORD` に設定し、`source=ankiweb`、`discard_previous=true` で手動実行します。古い暗号化シードを使わず、AnkiWebからカード・画像を再取得します。ローカルの `.pages.env` も同じ値へ更新し、古いシードは再取り込みして作り直してください。過去のGit履歴・第三者が保存した暗号文は、古いパスワードで引き続き復号可能な点に注意してください。
- **完全な再公開**：AnkiWebかローカル取り込みが元データです。パスワードを失った既存暗号文は復号できませんが、新しいパスワードで元データを再取得できます。
- **画像サーバーを使わない例外**：ローカルの `pages_site.py --cached-media-only` は前回／シードの画像を再利用します。この場合だけ、新規・同名変更の図はPCからの再取り込みが必要です。通常のActionsはこのオプションを使いません。

暗号文からカード数・プロフィール名などを平文で公開するメタデータは作りません。ただしファイルサイズや更新時刻は公開配信から分かります。ActionsはAnkiWebへ書き込みません。アプリで追加したタグは、暗号化ファイルをPCで取り込み、明示的な操作で通常同期できます。[DASHBOARD.mdの逆取り込み手順](DASHBOARD.md#追加したタグをankiへ戻す)を参照してください。GitHub Secretsの追加は不要です。答えの開閉や閲覧はAnkiの回答履歴に記録しません。

実装の追加だけで外部サービスは有効になりません。コードのmain反映、Pages設定、Secretsの登録、手動成功確認、変数による有効化を行ってください。実アカウントとGitHub上での実行はこれらの設定後の確認事項です。
