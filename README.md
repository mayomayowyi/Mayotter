# Mayotter

複数のX（旧Twitter）アカウントやタイムラインを、ひとつの画面で利用できるWindows向けデスクトップアプリです。

## 主な機能

- 複数アカウント・複数カラム・タブ
- Work（ワークスペース）の作成と切り替え
- 画面端に収納するDockと、試験的なFlip
- カラム内検索、Web表示率の同期
- 録音・音声投稿、試験的なローカルノイズキャンセリング
- 日本語・英語・簡体字中国語

## ダウンロード

[最新版をダウンロード（GitHub Releases）](https://github.com/mayomayowyi/Mayotter/releases/latest)

ZIP版は展開して `Mayotter.exe` を起動してください。セットアップ版が公開されている場合は、インストーラーの案内に従ってください。

## 使い方

### 操作説明動画

https://github.com/user-attachments/assets/2b2e85a2-ddcd-45ef-87ac-a207be3cd51e

1. 起動し、初回の言語選択を行います。
2. 「+X」からアカウントを追加し、Xにログインします。
3. カラム追加からタイムライン・検索などを選択します。
4. 「Work」でカラム構成を切り替え、「Dock」「Flip」で表示方法を選びます。
5. カラム内検索は `Ctrl+F`、Web表示率の変更は `Ctrl`＋スクロールで行えます。

「Flip」はスマートフォン対応を想定した試験的な機能です。端末や環境によって正常に表示・動作しない場合があります。

## ソースコードについて

Mayotterの仕組みや開発内容を確認できるよう、ソースコードを公開しています。

### ソースから実行する

WindowsとPython 3.10以降が必要です。PowerShellでこのフォルダーを開き、以下のコマンドを順番に実行してください。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m src.app.launch_guard
```

基本的なPythonライブラリ（PySide6、NumPy、ONNX Runtimeなど）は、インストール時にまとめて導入されます。

音声関連の機能を使う場合は、次のファイルも必要です。

- **録音・音声変換**：FFmpegの `ffmpeg.exe` をPATHの通った場所か `tools/ffmpeg/` に配置してください。
- **AIノイズ除去**：[DeepFilterNet3のONNXモデル](https://github.com/Rikorose/DeepFilterNet/tree/main/models)が必要です。`DeepFilterNet3_onnx.tar.gz` を `tools/denoise/` に配置するか、環境変数 `MAYOTTER_DENOISE_MODEL` でファイルのパスを指定してください。

FFmpegやAIモデル本体はソースコードには含めていません。メモリ診断を利用する場合は、`pip install -e ".[diagnostics]"` でpsutilを追加できます。

設定やアカウントのProfile、録音データなどは、アプリの使用時に作成されます。これらの個人データも公開していません。

### Windows向けのビルド

配布用のZIPやインストーラーを作成するには、Inno Setupと追加のビルド環境が必要です。

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[build]"
```

`packaging/build_distribution.bat` でZIPとセットアップファイルを作成できます。外部コンポーネントも使用するため、再配布する際は[第三者ライセンスと配布条件](packaging/licenses/README.md)をご確認ください。

### 配布版との違い

公開しているソースコードは、Mayotter v1.1.2をベースに、その後の細かな修正も反映したものです。

主に、Profileの管理やエラー時の表示、Dockの音声関連UI、英語・中国語の案内文などを調整しています。

そのため、現在配布しているv1.1.2の実行ファイルとは一部のコードが異なります。バージョン番号は変更していません。

## ご利用にあたって

Mayotterは個人が開発している非公式のXクライアントであり、X Corp.とは関係ありません。Xの仕様変更や運用方針によって利用できなくなる場合や、アカウントの制限・ロックなどが発生する可能性があります。

本アプリの利用に伴うトラブルや損害について、開発者は法令で認められる範囲で責任を負いません。ご自身の判断と責任においてご利用ください。

ソースコードはMIT Licenseです。利用条件は [LICENSE](LICENSE) をご確認ください。第三者のコード・フォント・外部コンポーネントには、それぞれのライセンスが適用されます。

## お問い合わせ・開発支援

<p>
  <a href="https://mayoel.pages.dev/contact/">
    <img src="assets/contact.svg" alt="お問い合わせ" width="192">
  </a>
  <a href="https://ko-fi.com/mayomayoi">
    <img src="https://storage.ko-fi.com/cdn/kofi3.png" alt="Ko-fiで開発を支援" width="192">
  </a>
</p>

不具合の報告やご要望はお問い合わせから。開発支援はKo-fiで受け付けています。
