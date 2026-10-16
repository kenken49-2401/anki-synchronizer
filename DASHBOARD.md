# Anki Atlas：ローカル＋GitHubだけで使う

Render・Supabase・常駐Pythonサーバーは不要です。GitHub ActionsがAnkiWebを読み取り、カード・復習履歴・画像を暗号化してGitHub Pagesへ配置します。閲覧パスワードを入力するとブラウザー内で復号します。

- 青いカード一覧、図・化学式、答えの個別／一括表示、検索、タグ別表示。
- カード別の正解率、日別の回答数・学習時間、連続学習。
- **一覧／デッキごと／親フォルダごと**の表示切り替え。親デッキを選んでサブデッキを含めることもできます。
- PCのAnkiConnectから取り込む方法もあります。AnkiWebへのカード編集・回答記録・画像アップロードは行いません。

```text
PC / スマホのAnki → AnkiWebへの通常同期
                           ↓ 読み取りだけ
                 GitHub Actions → データ＋画像を暗号化
                           ↓
                 GitHub Pages（画面＋暗号文）
                           ↓ 閲覧パスワード
                 自分のブラウザー内で復号・表示
```

## 1. 自分のPCにコードとツールを用意する

この作業はCodexの画面内ではなく、**自分のPCのターミナル**で行います。[Python 3.12](https://www.python.org/downloads/) と [uv](https://docs.astral.sh/uv/getting-started/installation/) をインストールしてください。

まだリポジトリを持っていない場合：

```sh
git clone --branch feat/anki-dashboard https://github.com/kenken49-2401/anki-synchronizer.git
cd anki-synchronizer
```

既にある場合は、そのフォルダを開き、`feat/anki-dashboard` の今回の変更を取り込んでください。GitHubで変更をmainへ反映した後はmainを使えます。

## 2. 依存関係と閲覧パスワードを準備する

リポジトリのフォルダで、次の2行を実行します。

```sh
uv sync --frozen
uv run --frozen python scripts/pages_setup.py
```

1行目はアプリに必要なライブラリを `.venv` へ入れます。2行目は強いランダムな閲覧パスワードを作り、**`.pages.env`** へ保存します。既存ファイルは上書きしません。

`.pages.env` をPCのエディターで開き、`PAGES_PASSWORD=` の右側をパスワード管理ツールへ保管してください。ブラウザーで閲覧するときと、GitHub Secretsの設定に使います。端末出力やチャットへ貼る必要はありません。

- `.pages.env` と `secrets.env` はGitへ追加しません。Windowsでは自分だけが読めるアクセス権も設定してください。
- **以前の `.dashboard.env`、送信用トークン、Fernetキーは新構成では不要**です。旧サーバー設定を新しい手順へコピーしないでください。
- パスワードは16～1024 UTF-8バイトに対応しますが、生成された長いランダム値を使ってください。AnkiWebのパスワードとは別です。

## 3. GitHubだけで公開・自動更新する（推奨）

[ACTIONS_SETUP.md](ACTIONS_SETUP.md) の順番で、手元でAnkiWebトークンを取得し、GitHubにSecretsを設定します。Pagesの配信元をGitHub Actionsにして、最初に手動更新を実行します。

GitHub FreeでPagesを利用する標準の方法は公開リポジトリです。公開するのはソースと暗号文で、平文のカード、画像、Ankiのコレクション、鍵は配置しません。PC停止中も、学習した端末からAnkiWebへ同期済みの内容をActionsが定期取得できます。

## 4. PCのAnkiConnectから取り込む（任意）

AnkiWebを使わず、PCで開いているプロフィールを取り込みたい場合の方法です。

1. デスクトップ版Ankiで自分のプロフィールを開きます。
2. [AnkiConnect](https://ankiweb.net/shared/info/2055492159)（アドオンコード `2055492159`）を導入して再起動します。
3. AnkiConnectの設定は `webBindAddress=127.0.0.1`、`webBindPort=8765` のまま使い、必要なら `apiKey` を設定します。同じキーを `.pages.env` の `ANKI_CONNECT_API_KEY` に追加します。8765番ポートは公開しません。
4. 次のコマンドをPCで実行します。

```sh
uv run --frozen --env-file .pages.env python pages_site.py --source ankiconnect --seed-output pages-data/snapshot.enc.json
```

必要なら `--profile "自分のプロフィール名"` や `--query 'tag:化学'` を追加できます。現在開いているプロフィールが違う場合は停止し、勝手に切り替えません。古いAnkiConnectではプロフィールが1つの場合のみ識別できます。

作成されるもの：

| 場所 | 中身・扱い |
| --- | --- |
| `site/` | 配信用の画面と `snapshot.enc.json`。平文データやパスワードは含みません。Gitでは無視されます |
| `pages-data/snapshot.enc.json` | GitHubへ渡すための暗号化済みシード。これだけを明示的に追加します |

```sh
git add pages-data/snapshot.enc.json
git commit -m "Update encrypted Anki seed"
git push
```

コードとシードがデフォルトブランチに反映されたら、Actionsを `source=seed` で手動実行すると、AnkiWebトークンなしでも公開できます。自動更新を有効にしていない場合は、PCでの再取り込み・シード更新・手動公開で更新します。

ローカルで画面を確認する場合：

```sh
uv run --frozen python -m http.server 8000 --bind 127.0.0.1 --directory site
```

PCのブラウザーでlocalhostの8000番を開き、`.pages.env` の閲覧パスワードを入力します。サーバーに復号処理はありません。

## カードをフォルダごとにまとめる

「タグ別カード」の **まとめ方**、または「接続・設定」の **カードのまとめ方** で選びます。

- **一覧**：従来どおり、まとめずに並べます。
- **デッキごと**：`科学::化学`、`科学::化学::高分子` を別の見出しに分けます。
- **親フォルダごと**：上記を最上位の `科学` にまとめます。

Ankiのフォルダはデッキ／サブデッキに対応します。絞り込みにはカードのない親デッキも現れます。「サブデッキを含める」を外すと、選択したデッキ直下だけになります。`科学` と `科学館` は混ざりません。タグ・検索・並び順・ページ送りと併用でき、まとめ方の設定はこのブラウザーへ保存します。デッキ名・カード本文・パスワードはブラウザーの永続ストレージへ保存しません。

Markdown保存は、画面と同じまとめ方でPCへ書き出します。ダウンロードしたMarkdownは平文なので、公開リポジトリへ追加しないでください。

## 暗号化と表示の範囲

PBKDF2-SHA256（600,000回・ランダムsalt）から256ビット鍵を作り、AES-GCM（ランダムnonce・認証タグ）でカード・履歴・画像・プロフィール名をまとめて暗号化します。ブラウザーのWeb Cryptoで復号し、画像はメモリー内のBlob URLで表示します。パスワードは送信せず、復号キーはメモリー内だけに保持します。ログアウト・再読み込みで再度パスワードが必要です。

暗号文は誰でもダウンロードできます。生成した強いパスワードを使い、ソースを書き換えられる人やGitHub自体も信頼する必要があります。パスワードが漏れた場合、過去に公開した暗号文も読まれる可能性があります。ブラウザー上の平文を共有端末や拡張機能から完全に隠す仕組みではありません。

画像はPNG/JPEG/GIF/WebP、下付き・上付き文字や基本的な表に対応します。カードのスクリプト・外部画像URL・SVG・音声・MathJaxの実行はしません。未取得／未対応の画像は「画像未取得」と表示します。AnkiWebの画像取得は `begin` と `downloadFiles` の読み取りAPIのみです。

パッケージの平文は32 MiB、カード50,000枚、履歴1,000,000件、画像500個・各2 MiB・合計16 MiBまでです。超過や取得失敗時は公開を行わず、最後の成功したサイトを維持します。

正解率はAgainを不正解、Hard/Good/Easyを正解とした自己評価の割合です。学習時間はAnkiの回答時間の合計で、休憩・閲覧時間は含みません。日付の区切りは画面で選んだタイムゾーンです。

## 開発・検証

```sh
uv sync --frozen
uv run --frozen pytest -q
node --test tests/*.test.mjs
```

[検証結果](DASHBOARD_VERIFICATION.md)。旧MCPやサーバー方式のソースは互換用に残っていますが、新しいPages構成では `server:app`、`dashboard:app`、`render-dashboard.yaml`、`Dockerfile.dashboard` を使いません。
