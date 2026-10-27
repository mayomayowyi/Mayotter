# 第三者コンポーネント

このソース配布には、FFmpeg・Qt・Pythonの実行バイナリやDeepFilterNet3のモデルを含めていません。

| 対象 | ライセンス・同梱内容 |
| --- | --- |
| Mayotter | MIT。ルートの `LICENSE` |
| Noto Sans SC 2.004 | SIL OFL 1.1。`src/ui/assets/fonts/` のOTFと著作権表示を含む `OFL.txt` |
| DeepFilterNet由来の信号処理 | MIT OR Apache-2.0。`DeepFilterNet/LICENSE-MIT`、`DeepFilterNet/LICENSE-APACHE` |
| PySide6 / Qt / QtWebEngine | 使用する配布物のLGPL/GPLまたは商用ライセンスと、Chromium等の第三者表記を確認 |
| NumPy / ONNX Runtime | BSD-3-Clause / MIT。ビルド時にwheel内のライセンスを採取 |
| FFmpeg 9.0（配布ビルドが取得） | 固定したGyan.devビルドはGPL-3.0-or-later。対応ソースと外部ライブラリの配布義務を確認 |

フォントの取得元は [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk/tree/165c01b46ea533872e002e0785ff17e44f6d97d8/Sans/SubsetOTF/SC)、OFL表記は同版を配布する [google/fonts](https://github.com/google/fonts/blob/a85815a42757630ce188fdad368c2dfc444d4773/ofl/notosanssc/OFL.txt) です。フォントは無改変です。

DeepFilterNet3のソースコードのライセンスだけで、学習済み重みの再配布許諾を断定しないでください。[上流issue #697](https://github.com/Rikorose/DeepFilterNet/issues/697)・[#712](https://github.com/Rikorose/DeepFilterNet/issues/712) で確認が続いています。モデルファイルはこのリポジトリの公開対象に含めません。

`packaging/third_party.json` と `requirements-dist.txt` が配布ビルド用のバージョンとハッシュを定義します。`stage_third_party.py` は実行時にモデル・FFmpeg・Python依存を取得し、ライセンスとマニフェストをステージングします。ソース公開と、生成されたバイナリ配布物の再配布条件の確認は別に行ってください。

FFmpegの外部ライブラリを含む対応ソース一式と、Qt等の配布条件をビルドスクリプトだけで充足する保証はありません。Inno Setupにも独自の利用条件があります。未確認の配布物をそのまま再公開しないでください。
