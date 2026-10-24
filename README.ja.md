# Reciplate

[English](README.md) | [Deutsch](README.de.md) | 日本語

Instagramのリール（または手元のPDF）から、ドイツ語と英語のLuaLaTeXレシピを作ります。シート、動画、カバー写真、コンパイル済みPDFまで揃います。

マスターテンプレートは書き換えません。コピーを作り、そのコピーだけを埋めてからコンパイルします。Python 3.10+。単体で動きます。隣にツールボックスの `common/` があれば、その共通UIを使います。

起動は `reciplate.py`。補助コードは `lib/`、テストは `tests/` です。

## セットアップ

```text
copy config.example.json local\config.json
```

`recipes_root` を自分のレシピフォルダに設定します（例の `~/Recipes` は展開されます）。`template_tex` と `sections` のパスは、そのルートからの相対パスで書けます。別のJSONを使う場合は、任意で `RECIPLATE_CONFIG` を指定します。

```text
pip install -r requirements.txt
python reciplate.py
```

`local/config.json` は gitignore 済みです。コミットするのは `config.example.json` だけです（個人パスは入れない）。手元のPDFには `pypdf` が必要です（`requirements.txt` に含まれます）。

## レシピごとに残るもの

`[3][nn]slug/` の中身:

- `{folder}.de.tex` / `{folder}.en.tex`
- `{folder}.de.pdf` / `{folder}.en.pdf`（LuaLaTeXがある場合）
- 動画（`{folder}.mp4` など）
- `{folder}.jpg`（Instagramのサムネイル、または動画の1フレーム）

補助ファイル（`.aux`、`.log`、ステッカー、`source.json`、`img/`）は消します。ステッカーは共有テンプレートの `img/` を `\graphicspath` で参照します。

## 手順

1. InstagramのURLを貼るか、**PDF…** で手元のファイルを選びます（ダウンロードが弾かれるときは Firefox / Chrome / Edge のクッキー）。
2. Fetch metadata — キャプション（またはPDFのテキスト）を材料と手順に分けます。ウィンドウで直してください。
3. Create folder — テンプレートをコピーし、もう一方の言語に翻訳し、メディアを落としてPDFをコンパイルします。
4. 同じURLをもう一度 → 警告のあと Cancel か Update。Update は番号（`[3][36]`）を保ち、フォルダとファイルを今のタイトルに合わせ、セクション（Kochen / Backen）間の移動もできます。新しい番号は、選んだセクションだけでなく、全セクションの次の `[3][n]` です。

Fetch、ダウンロード、翻訳、コンパイルはバックグラウンドで走るので、ウィンドウはそのまま使えます。Instagramのリンクは追跡用クエリ（`?igsh=…`）なしで保存します。

言語は本文から判定し、両方のシートに印字します（`Video: Deutsch (Original)` など）。

翻訳は MyMemory、だめなら Google Translate（`deep-translator` があればそれ、なければ公開HTTP API）。

## EXE（Windows）

```text
.\Build.ps1
```

`Reciplate.exe` を `config.json` の隣に置きます。`yt-dlp` は同梱です。作り直す前に起動中のEXEを閉じるか、`dist\Reciplate.exe` を使ってください。

LuaLaTeX（TeX Live または MiKTeX）は別途、そのマシンに入れておく必要があります。

## テスト

```text
python -m unittest discover -s tests -t .
```

## GitHub

このフォルダはすでに単独のリポジトリです。`local/`、`*.last`、`build/`、`dist/`、`Reciplate.exe` はローカルのまま。親の `functional_programs` は push しないでください。
