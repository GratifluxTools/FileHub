# File Hub

ファイルが「どこにあるか分からない」ときに、すぐ探せるファイル管理アプリです。
ファイルの実体は動かさず、**場所・タグ・リンク・メモ・音声や動画の情報**を索引として管理します。
Windows と Linux（x64 / arm64）で動きます。日本語と英語に対応しています。

[日本語](#日本語) | [English](#english)

---

## 日本語

### 目次
- [2つの版](#2つの版)
- [ダウンロードと起動](#ダウンロードと起動)
- [初回のスキャン範囲](#初回のスキャン範囲)
- [画面の使い方](#画面の使い方)
- [対応している拡張子](#対応している拡張子)
- [データの保存場所とプライバシー](#データの保存場所とプライバシー)
- [制限事項](#制限事項)
- [ビルドと開発](#ビルドと開発)
- [トラブルシューティング](#トラブルシューティング)

<a id="2つの版"></a>
### 2つの版

| | シングルデバイス版 | ポータブル版 |
|---|---|---|
| 想定 | 普段使うPC 1台で使う | USBメモリなどで持ち運ぶ |
| データの場所 | ユーザーのデータフォルダ（Windows: `%APPDATA%\FileHub`、Linux: `~/.file_hub`） | アプリと同じフォルダの `data` フォルダ |
| 機能 | 同じ（違いはデータの保存場所だけ） | 同じ |

どちらの版も、同じ画面・同じ機能です。ポータブル版は、フォルダごと別のPCに移したときに
「場所の再リンク」（後述）でファイルの場所を付け直せます。

<a id="ダウンロードと起動"></a>
### ダウンロードと起動

GitHub の Releases（または Actions の成果物）から、次のどれかの zip を取ります。

| ファイル名 | 対象 |
|---|---|
| `FileHub-single-windows-x64.zip` | Windows（64bit）、シングルデバイス版 |
| `FileHub-single-linux-x64.zip` | Linux（Intel / AMD）、シングルデバイス版 |
| `FileHub-single-linux-arm64.zip` | Linux（ARM64）、シングルデバイス版 |
| `FileHub-portable-windows-x64.zip` | Windows（64bit）、ポータブル版 |
| `FileHub-portable-linux-x64.zip` | Linux（Intel / AMD）、ポータブル版 |
| `FileHub-portable-linux-arm64.zip` | Linux（ARM64）、ポータブル版 |

**Windows**
1. zip を展開します（ポータブル版は USB メモリなど、書き込みできる場所へ）。
2. `file_hub.exe` を起動します。
3. 署名されていないため SmartScreen の警告が出ることがあります。「詳細情報」→「実行」を選んでください。

**Linux**
1. `uname -m` で CPU の種類を確かめます（`x86_64` なら x64、`aarch64` なら arm64）。
2. zip を展開し、中の実行ファイルを起動します。

> ポータブル版のフォルダは**書き込みできる場所**に置いてください（`Program Files` などは不可）。

<a id="初回のスキャン範囲"></a>
### 初回のスキャン範囲

初回起動時に「スキャンするフォルダ」の画面が開きます。

- ホーム直下の `Desktop` `Documents` `Downloads` `Pictures` `Music` `Videos` と、
  `Google Drive` `OneDrive` `Dropbox` などの同期フォルダ（見つかったもの）が候補に出ます。
- 候補にないフォルダは「フォルダを追加」で選べます。
- 対象は **自分のアカウント（ホームフォルダ）の中だけ** です。他のユーザーのフォルダや、システムの領域は選べません。
- 次は**含まれません**：システムフォルダ（Windows・Program Files など）、Windows の隠し・システムファイル、
- **FileHub 自身のファイルは含めません**：プログラム一式（`file_hub.exe` とアプリ本体の組み合わせ）、索引・設定のフォルダ、書き出した `.json`、配布用の zip（`FileHub-single-windows-x64.zip` など）が対象です。名前ではなく中身で判定するので、フォルダ名を変えても除外されます。既に登録されていたものは、起動時・スキャンの後・メンテナンスの「FileHub自身のファイルを索引から外す」で索引から外れます（ファイルは消えません）。
  `AppData`（設定で含められます）、`node_modules` `.git` `__pycache__` などの作業用フォルダ、シンボリックリンク。
- 「隠しファイル・フォルダを含める」を選ぶと、ドット（`.`）で始まるものも対象になります。

後からは、画面「場所」の **スキャン範囲の設定** で変更できます。

<a id="画面の使い方"></a>
### 画面の使い方

画面は上のタブで切り替えます。**検索**・**場所**・**タグ**・**設定**。
ファイルの名前をクリックすると、そのファイルの**詳細画面**が開きます（左上の ← で戻れます）。

#### 1. 検索（ファイルがどこにあるか探す）
- **キーワード**：ファイル名・パス・メモを検索します。空白で区切ると「すべての語を含む」で探します（例：`請求 2025`）。
- **絞り込み**（「絞り込み」ボタン）：拡張子（`pdf, xlsx` のようにカンマで複数指定）、カテゴリ、場所、タグ、サイズ（MB）、更新日（`2025-01-01` の形式）、並び順、欠落ファイルも含めるか。条件の数は検索の横に表示されます。リセットで全部外せます。
- **欠落ファイルも含める**：ディスクから消えたファイルも表示します（`[欠落]` と表示されます）。
- 結果の上に **「N件（うち欠落 M件）」** が出ます。「該当するファイルはありません」なら、そのような条件のファイルは無いと分かります。
- **CSVに書き出し**：検索結果を表計算ソフトで開ける CSV にします（名前・パス・場所・タグ・メモなど）。

#### 2. 複数選択
結果の左のチェックボックスで複数のファイルを選ぶと、下のバーで次の操作ができます。
- **選択中に付ける**：タグを一度にまとめて付けられます。
- **選択を圧縮**：選んだファイルを1つの zip にまとめます（元の場所に `archive-日時.zip` ができます）。
- **選択解除**。

#### 3. 詳細画面（ファイルの操作）
| 操作 | 内容 |
|---|---|
| 開く | 既定のアプリで開きます |
| フォルダで表示 | エクスプローラー（Finder・ファイルマネージャー）で場所を開き、選択します |
| パスをコピー | 絶対パスをクリップボードへ |
| 名前を変更 | 同じフォルダ内で名前を変えます。タグ・メモ・リンクは残ります |
| 移動 | 別のフォルダへ移します。登録した場所の外へ出すと、索引から外れます |
| 圧縮 | このファイルを zip にします |
| 索引から外す | 索引からだけ外します。ファイルは残ります |
| ファイルを削除 | 削除します（設定でごみ箱へ移動できます） |

#### 4. プレビューと編集
- **画像**（jpg・png・gif・bmp・webp・heic）：画面に表示します。
- **テキスト系**（txt・md・csv・tsv・json・xml・yaml・log・ini・cfg・html・css・js・py など）：
  画面の中で**編集して保存**できます。元の文字コード（UTF-8・Shift_JIS など）のまま保存します。
  大きすぎるファイル（設定の「プレビューの最大サイズ」、既定は 100MB を超えるもの）は閲覧のみです。
- **Word（docx）・Excel（xlsx）・PowerPoint（pptx）・ODF・PDF・RTF**：中の文章や表を読み取って表示します（編集はできません。古い形式の doc・xls・ppt は「開く」で既定のアプリを使ってください）。
- **画像の簡単な加工**：左右・上下の回転、180°回転、左右・上下反転、白黒、縮小（最大辺のピクセル数を指定）。
  既定では「_edited」付きの**新しいファイル**を作ります。「元の画像を上書き」を入れると元を書き換えます。
- **音声・動画**：情報を登録できます（後述）。再生は既定のアプリで行います。

#### 5. 圧縮ファイル
- **中身を表示**：zip・tar・tar.gz・gz・7z・rar の中身の一覧を見られます。
- **ここに展開**：同じフォルダに、圧縮ファイルと同じ名前のフォルダを作って展開します（Zip Slip のような危険なパスは拒否します）。

#### 6. 音声・動画の情報（タイトル・アルバム・トラック番号・シーズン・話数など）
- **MP4・MOV・M4A・M4V**：タイトル・アルバム・トラック・年に加え、**シリーズ・シーズン・話数もファイルのタグ（MP4 のメタデータ）に書き込み**ます。既存のタグは最初に読み込んで表示します。
- **MP3・FLAC・OGG**：タイトル・アーティスト・アルバム・トラック・年をファイルのタグ（ID3 など）に書き込みます。シリーズ・シーズン・話数はこの形式に無いので、索引だけに保存します（保存後に「索引のみ」と表示されます）。
- **mkv・avi・webm・wmv**：タグは書けないので、索引だけに保存します（ファイル自体は変わりません）。
- 再生は既定のアプリで行います。

#### 7. タグ・関連ファイル・メモ
- **タグ**：詳細画面で追加・削除します。タグ画面では名前の変更・削除、タグで検索ができます。タグは全ファイルで共有されます。
- **関連ファイル**：「関連付けを追加」で別のファイルを選ぶと、両方の詳細画面からお互いへ移動できます。
- **メモ**：自由な文章を付けられます。メモも検索の対象です。

#### 8. 登録・デバイス・場所
「登録」画面で、ファイルを索引に入れます。最初に**デバイス**を選びます。

- **デバイス**：このPCは「(このPC) ホスト名 · Windows」のように先頭に `(このPC)` が付きます。Google Drive などは「Google Drive · taro@example.com」のように、登録したアカウントやメールが表示されます。「デバイスを追加」で Windows・Linux・macOS・Google Drive・OneDrive・Dropbox・その他を登録できます。
- **このPCを選んだ場合**：
  - **フォルダを選ぶ（ツリー）**：ホームフォルダに加えて、外付けSSD・USBメモリなど、このPCから見えているドライブ（システムのドライブ以外）もツリーの一番上に並びます。チェックボックス付きのフォルダツリーが開きます。フォルダにチェックを入れると、その中身すべてが対象になります。外すと、中身すべてが対象外になります（上位を選んだまま下位だけ外すと、残りは兄弟フォルダとして選び直されます）。「選んだフォルダを登録してスキャン」で、各フォルダが場所として登録され、すぐスキャンされます。
  - **手動で登録**：下の手動登録と同じです。
- **ほかのデバイス（Google Drive など、このPCでないもの）**：フォルダは選べないので、**手動で登録**します。「場所」で登録済みのデバイスをプルダウンから選ぶと、そのデバイス名が場所の名前になります（同じ名前があれば番号が付きます）。ファイルの一覧を1行に1つずつ相対パス（例：`Documents/report.docx`）で入力します。フォルダ（末尾が `/`）と重複は無視されます。後から「ファイルを追加」で増やせます。
- 手動で登録したファイルは索引にだけあり、本体はこのPCにありません。開く・移動・削除はできず、タグ・メモ・リンク・関連付けは使えます。

**場所（ロケーション）** は、ファイルがあるデバイス上のフォルダです。場所の画面はデバイスごとにまとめて表示されます。
- **スキャン**：その場所だけを再スキャンします。新しいファイルを追加し、見つからないファイルは「欠落」にします（削除はしません）。
- **再リンク**：フォルダが見つからない（別のPCに移した、ドライブ文字が変わった、など）ときに、新しいフォルダを指定し直します。タグやメモはそのまま残ります。
- **ファイルを表示**・**名前の変更**・**削除**（索引から外すだけで、ディスク上のファイルは消えません）。
- デバイスを**削除**すると、その下の場所（索引の情報）もまとめて消えます。このPCのデバイスは削除できません。

#### 9. 設定
- **言語**（English / 日本語）：反映にはアプリの再起動が必要です。
- **プレビューの最大サイズ**（MB、既定 100MB）。
- **除外するフォルダ名**（カンマ区切り）。
- **隠しファイル・フォルダを含める**・**AppData を除外**。
- **削除時にごみ箱へ移動**（Windows・Linux で `send2trash` が使える場合）。
- **メンテナンス**：欠落したエントリの削除、索引の消去（ファイルは消えません）。
- **全データを書き出し／データを読み込み**：デバイス・場所・ファイル情報・タグ・メモ・リンクを1つのJSONファイルにまとめます。別のPCのFileHubで「データを読み込み」を選ぶと、索引に統合されます（同じ場所・同じデバイスは1つにまとまり、タグやメモは足し合わされます）。ディスク上のファイルは動きません。このファイルには索引の情報が平文で入るので、取り扱いに注意してください。
- **更新の確認**と、データフォルダを開く。

### ポータブル版の使い方
1. USB メモリなどに zip を展開します。
2. 初回起動時、アプリと同じフォルダに `data` フォルダができ、索引や設定が保存されます。
3. 別のPCで使うとき、場所のフォルダの場所が変わっていれば、場所の画面の **再リンク** でフォルダを指定し直します。
4. `data` フォルダも一緒に持ち運んでください。`data` を消すと、索引がリセットされます（ファイル本体は消えません）。

<a id="対応している拡張子"></a>
### 対応している拡張子

どの拡張子も登録できます（一覧にない拡張子は「その他」になります）。下は、機能ごとに対応している拡張子です。

| カテゴリ | 拡張子 | 画面で | 補足 |
|---|---|---|---|
| 文書 | txt・md | 閲覧・**編集** | |
| | docx・odt・rtf・pdf | 中身の表示 | 文章を読み取って表示（doc は「開く」で外部アプリ） |
| 表計算・データ | csv・tsv・json・xml・yaml | **編集** | 文字コードを保って保存 |
| | xls・xlsx・ods | 中身の表示 | xlsx・ods は表として表示（先頭の数シート） |
| プレゼン | ppt・pptx・key・odp | 中身の表示 | pptx・odp は文字を表示。ppt・key は「開く」で外部アプリ |
| 画像 | jpg・jpeg・png・gif・bmp・webp | 表示・**簡単な加工** | gif は1コマ目のみ保存 |
| | heic | 表示 | pillow-heif が必要 |
| | svg | テキストとして編集 | |
| | psd・ai | 「開く」で外部アプリ | |
| 音声 | mp3・flac・m4a・ogg | 情報の登録・**タグの書き換え** | |
| | wav・aac | 情報の登録（索引のみ） | |
| 動画 | mp4・mov・avi・mkv・webm・wmv | 情報の登録（索引のみ） | 再生は外部アプリ |
| 圧縮 | zip・tar・tar.gz・gz・7z | 中身の表示・**展開**・圧縮（zip） | 7z は py7zr が必要 |
| | rar | 中身の表示・展開 | unrar 本体と rarfile が必要（後述） |
| プログラム | exe・msi・app・dmg・apk・ipa | 「開く」・情報 | |
| Web・コード | html・htm・css・js・ts・py・php・java・c・cpp など | **編集** | |
| ディスクイメージ | iso・bin・cue | 情報 | |
| ログ・設定 | log・ini・cfg | **編集** | |

<a id="データの保存場所とプライバシー"></a>
### データの保存場所とプライバシー
- 索引（`index.db`）・設定（`config.json`）は、上の「2つの版」で書いた場所に保存されます。
- **アプリは通信をしません**。更新の確認を押したときだけ GitHub の最新版の情報を取得します。
- 索引には**ファイル名・パス・メモ・タグ**などが入ります。**索引は暗号化していません**。
  ポータブル版を持ち歩くときは、USB メモリ自体の管理（パスワード付きの USB など）にご注意ください。
- ファイルの**中身**は索引に保存しません（検索はファイル名・パス・メモ・タグが対象です）。
- 「ファイルを削除」は、設定によりごみ箱へ入ります。ごみ箱を使わない設定や、ごみ箱が使えない環境では完全に消えます。

<a id="制限事項"></a>
### 制限事項
- **編集できるのはテキスト系の形式だけ**です。Word・Excel・PDF などは中身の表示までです（編集は既定のアプリで）。
- 音声・動画の**再生機能はありません**（既定のアプリで開きます）。
- **Google Drive for desktop の仮想ドライブ**（`G:` など）は、ホームフォルダの外にあるため登録できません。
  Google Drive の**同期フォルダ**（ホーム内にできるもの）を登録してください。
- 欠落の検知は**スキャンしたときだけ**行います（常時監視はしていません）。
- **RAR** を扱うには、rarfile に加えて、システムに **unrar**（または unar など）が必要です。無い場合は「中身の表示」でエラーになります。
- **HEIC** の表示は pillow-heif の動作環境に依存します。
- 画像の加工は基本操作だけです。アニメーション GIF は1コマ目のみを保存します。

<a id="ビルドと開発"></a>
### ビルドと開発

**GitHub Actions でビルドする**（推奨）
1. このリポジトリを GitHub に置きます。
2. **Actions** → **Build** → **Run workflow** を押します（Release を公開すると自動で実行され、zip が Release に付きます）。
3. テストが通ると、2つの版 × 3つの環境（Windows x64・Linux x64・Linux arm64）のビルドが並列で走ります。
4. 完成した zip は Actions の成果物（Artifacts）からダウンロードできます。

**ローカルで動かす（開発者向け）**
```bash
python -m venv .venv
source .venv/bin/activate        # Windows は .venv\Scripts\activate
pip install -r requirements.txt pytest
python main.py                   # 起動（既定はシングルデバイス版）
python -m pytest tests -q        # テスト
```

**構成**
| ファイル | 役割 |
|---|---|
| `main.py` | 画面（Flet）。検索・詳細・場所・タグ・設定 |
| `db.py` | SQLite の索引（場所・ファイル・タグ・リンク・検索） |
| `scanner.py` | フォルダ走査、差分更新、欠落の判定、再リンク後の付け替え |
| `archive_utils.py` | zip / tar / gz / 7z / rar の展開と作成（Zip Slip 対策つき） |
| `text_io.py` | 文字コードの判定・読み書き、Office・PDF・RTF の文章抽出 |
| `image_tools.py` | 画像のプレビュー（HEIC 含む）と簡単な加工 |
| `media_tags.py` | 音声タグ（mutagen）の読み書き |
| `categories.py` | 拡張子とカテゴリ、機能ごとの対応表 |
| `edition.py` | 版の種類（`single` / `portable`）。ビルド時に書き換えられる |
| `config.py` | 設定とデータフォルダの場所 |
| `i18n.py` | 英語・日本語の文言 |

**版の切り替え**：`edition.py` の `EDITION` を `"single"` か `"portable"` にします。
GitHub Actions では、ポータブル版のビルド時に自動で書き換えます。

<a id="トラブルシューティング"></a>
### トラブルシューティング
- **「場所が見つかりません」と出る**：フォルダを移動した、ドライブ文字が変わった、別のPCで開いた、などが原因です。
  場所の画面で **再リンク** を押して、新しいフォルダを指定してください。
- **スキャンしてもファイルが出ない**：そのファイルが隠し・システムファイル、または除外フォルダ（`node_modules` など）の中にないか確認してください。
  隠しファイルは設定の「隠しファイル・フォルダを含める」で対象にできます。
- **文字化けする**：UTF-8 と Shift_JIS（cp932）を自動判定します。判定できない場合は外部アプリで開いて文字コードを確かめてください。
- **Linux でファイルを開けない**：`xdg-open` が使えるか確認してください（デスクトップ環境が必要です）。
- **ポータブル版でデータが保存されない**：フォルダが書き込み禁止になっていないか（`Program Files` などに置いていないか）確認してください。

---

## English

### Contents
- [Two editions](#two-editions)
- [Download and start](#download-and-start)
- [First-run scan scope](#first-run-scan-scope)
- [Using the app](#using-the-app)
- [Supported file types](#supported-file-types)
- [Where data lives and privacy](#where-data-lives-and-privacy)
- [Limitations](#limitations)
- [Build and development](#build-and-development)
- [Troubleshooting](#troubleshooting-en)

<a id="two-editions"></a>
### Two editions
- **Single device**: data is stored in your user data folder (Windows: `%APPDATA%\FileHub`, Linux: `~/.file_hub`).
- **Portable**: data is stored in a `data` folder next to the app, so the whole folder can travel on a USB drive.

Both editions have the same features and screens.

<a id="download-and-start"></a>
### Download and start
Download the zip that matches your edition and platform from Releases (or the Actions artifacts):
`FileHub-{single|portable}-{windows-x64|linux-x64|linux-arm64}.zip`

- **Windows**: unzip and run `file_hub.exe`. SmartScreen may warn because the app is not code-signed; choose *More info* → *Run anyway* if you trust the download.
- **Linux**: check your CPU with `uname -m` (`x86_64` → x64, `aarch64` → arm64), unzip, and run the app inside.
- Keep the portable folder in a **writable** place (not `Program Files`).

<a id="first-run-scan-scope"></a>
### First-run scan scope
On first start you choose folders to index. Candidates are the common folders in your home folder (Desktop, Documents, Downloads, Pictures, Music, Videos) and any sync folders such as Google Drive, OneDrive or Dropbox. You can add others with **Add folder**.

- Only folders **inside your home folder** (your own account) can be used.
- System folders, Windows hidden/system files, symbolic links, `AppData` (optional), and work folders such as `node_modules` and `.git` are **not** included.
- **FileHub's own files are never included**: the program folder (`file_hub.exe` with the app files), the index and settings folder, exported `.json` files, and build zips such as `FileHub-single-windows-x64.zip`. They are recognised by their contents, not their names, so renaming the folder does not help them slip in. Entries registered earlier are removed from the index at startup, after a scan, or with "Remove FileHub's own files from the index" in Maintenance (files are not deleted).
- Hidden files can be included with a setting. You can change the scope any time from **Locations → Scan settings**.

<a id="using-the-app"></a>
### Using the app
Tabs: **Search**, **Locations**, **Tags**, **Settings**. Click a file name to open its details (← to go back).

- **Search**: the keyword box (all words must match name, path or memo). Other conditions are on the **Filters** page (press Reset filters to clear them): extensions (`pdf, xlsx`), category, location, tag, size in MB, modified date (`2025-01-01`), include missing files, sort order. The summary shows the count and how many are missing, so you can quickly check whether matching files exist.
- **Multi-select**: add a tag to all selected files, compress the selection into a zip, or export the results to CSV.
- **Details**: open, show in folder, copy path, rename (keeps tags, memo and links), move, compress, remove from index (keeps the file), or delete (to the Recycle Bin/Trash when enabled).
- **Preview and edit**: images are shown; text formats (txt, md, csv, json, html, code, log, etc.) can be edited and saved in their original encoding (UTF-8 or Shift_JIS); Office, PDF, ODF and RTF show extracted text (read-only). The preview limit is 100 MB by default (Settings).
- **Simple image edits**: rotate, flip, grayscale, and resize. The result is saved as a new `_edited` file unless you choose to overwrite the original.
- **Archives**: list contents; extract next to the archive (unsafe paths are refused).
- **Audio / video info**: title, artist, album, track, year, series, season, episode. For MP4/MOV/M4A/M4V all of them are written to the file's tags; for MP3/FLAC/OGG the common ones are written and series/season/episode stay in the index; mkv, avi, webm and wmv are index-only.
- **Tags, linked files and memos** are available on every file. Tags can be renamed, deleted and searched on the Tags tab.
- **Registration** starts with choosing a **device**. On this PC you can pick folders (your home folder and any connected external drive, such as an SSD or USB stick, except the system drive) with a checkbox tree (checking a folder includes everything inside it) or enter a file list by hand. For other devices such as Google Drive, enter a file list by hand (one relative path per line). Manually entered files live in the index only.
- **Locations** belong to devices and are grouped by device. Rescan, relink (when a folder moved), rename, or remove them. Relink keeps all tags and memos. Removing a device removes its locations from the index (not the files).

<a id="supported-file-types"></a>
### Supported file types
Any extension can be registered; unlisted ones are grouped as "Other". The full per-feature table is in the Japanese section above (same list).

<a id="where-data-lives-and-privacy"></a>
### Where data lives and privacy
- The index (`index.db`) and settings (`config.json`) are stored in the folder described above.
- The app makes **no network connections** except when you press *Check for updates*.
- The index contains file names, paths, tags and memos. **The index is not encrypted**, so protect a portable USB drive accordingly. File contents are not stored in the index.

<a id="limitations"></a>
### Limitations
- Only plain-text formats can be edited inside the app; Office, PDF and RTF files are read-only previews.
- No built-in audio or video playback (files open in the default app).
- Google Drive for desktop's virtual drive (e.g. `G:`) is outside the home folder and cannot be indexed; use the sync folder inside your home folder.
- Missing files are detected during scans only.
- RAR needs the **unrar** tool installed on the system.
- HEIC preview depends on pillow-heif.

<a id="build-and-development"></a>
### Build and development
- **GitHub Actions**: run the *Build* workflow (or publish a Release). Tests run first, then six builds (2 editions × Windows x64 / Linux x64 / Linux arm64) produce zip files.
- **Local**: `pip install -r requirements.txt pytest`, `python main.py`, `python -m pytest tests -q`.
- Set `EDITION` in `edition.py` to `"single"` or `"portable"` (the workflow does this for portable builds).

<a id="troubleshooting-en"></a>
### Troubleshooting
- **Location not found**: the folder moved or the drive letter changed. Use **Relink** on the Locations tab.
- **Files missing from search**: they may be hidden, system files, or inside a skipped folder such as `node_modules`.
- **Garbled text**: encoding is auto-detected between UTF-8 and Shift_JIS (cp932). Open the file in another app to confirm the encoding.
- **Portable data not saved**: make sure the folder is writable.

---

## License

Not specified yet. Add a LICENSE file before publishing.
