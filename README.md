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

## ソースから実行

WindowsとPython 3.10以降が必要です。PowerShellで、このフォルダーから実行します。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m src.app.launch_guard
```

実行時のPython依存関係はPySide6（QtWebEngineを含む）、NumPy、ONNX Runtimeです。メモリ診断を使用する場合は `pip install -e ".[diagnostics]"` でpsutilも導入してください。

録音・音声変換にはFFmpegが必要です。`ffmpeg.exe` をPATHに置くか、`tools/ffmpeg/ffmpeg.exe` に配置してください。ソースにはFFmpegの実行ファイルを含めていません。

AIノイズ除去には、別途 [DeepFilterNet3のONNXモデル](https://github.com/Rikorose/DeepFilterNet/tree/main/models) が必要です。モデルはソースに含めていません。上流の利用条件を確認したうえで、`DeepFilterNet3_onnx.tar.gz` を `tools/denoise/` に配置するか、環境変数 `MAYOTTER_DENOISE_MODEL` にファイルのパスを指定してください。アプリはモデルのSHA-256を検証します。学習済み重みの再配布条件は、[上流で確認中](https://github.com/Rikorose/DeepFilterNet/issues/697)です。

設定・アカウントのProfile・録音は実行時に生成されます。`data/`、`data_dev/`、`audio_visual/` をGitHubへ追加しないでください。

Windows配布物のビルドには `pip install -e ".[build]"` とInno Setupが必要です。`packaging/build_distribution.bat` は独立した出力先へZIP・Setupを作成します。ビルド時に外部コンポーネントを取得するため、再配布前に [第三者ライセンスと配布条件](packaging/licenses/README.md) を確認してください。

## ソースと配布版の対応

このソースは公開済みv1.1.2を基に、配布後の不具合修正を含みます。配布済みバイナリと完全に同一のコードではありません。バージョン番号は1.1.2のままです。

- `profile_manager.py`: カラムを閉じた後のProfile再利用と、エラー時の参照・ログ処理を修正。
- `main_window.py`: Profileを開けない場合の通知、Dockの音声UI確認、設定説明文の折り返しを修正。
- `translations_en.py` / `translations_zh_cn.py`: Profileを開けずタブを追加できない場合の通知文を追加。

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
