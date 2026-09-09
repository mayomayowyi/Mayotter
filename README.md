## Mayotter

複数の X（旧Twitter）アカウントを、複数カラムで表示する Windows 向けアプリです。

Python / PySide6 / Qt WebEngine で実装しています。

## Releaseにおける注意

Mayotter v1.0.0 ～ v1.0.4 では、自動アップデートに不具合があります。

`Mayotter\Mayotter.exe` の構成で配置されていない場合、自動アップデートが正常に機能しません。

v1.0.5 未満のバージョンをお使いの場合は、手動で上書きするか、Mayotter.exe が入っている大本のフォルダを `Mayotter` に変更してください。

## 既知の問題

**GoogleIMEの入力重複について**

GoogleIMEで変換を確定した直後、次の入力開始時に直前の確定文字列を含んだ状態で入力が開始され、文字が重複して入力されることがあります。

QtWebEngine / ChromiumとIME間の入力処理に起因する可能性があるため、現時点では修正を保留しています。

## 必要環境

* Python 3.10 以上
* PySide6 6.6.1 以上

## インストール

```bash
pip install -e .
```

## 起動

```bash
python -m src.app.main
```

## ソースコードについて

自分用に作っているアプリですが、透明性のためにソースコードを公開しています。

ご利用については LICENSE を確認してください。
