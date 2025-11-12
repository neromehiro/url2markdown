# url2markdown API

公開されている任意のURL（通常のWebページ、Notion文書、Google Docsなど）をクリーンなMarkdownへ変換するFastAPIサービスです。  
内部的にはオープンソースの `url2markdown` プロジェクト（`newspaper3k` + `markdownify`）と、JSに依存するページ向けのHTTPオンリーなフォールバックを組み合わせています。

## ホスティング済みエンドポイント

Vercelにデプロイされた `https://url2markdown-seven.vercel.app` にアクセスできます。Swagger UI は `https://url2markdown-seven.vercel.app/docs` にあります。

> ⚠️ 便宜的に公開しているだけで可用性や継続提供を保証しません。URLは予告なく使えなくなる場合があります。

任意のページのMarkdownを取得するには、`/url/reader/` の直後に対象URL（必要に応じてURLエンコード済み）をそのまま付与してください。例:

```bash
curl -X GET \
  'https://url2markdown-seven.vercel.app/url/reader/https%3A%2F%2Fwww.notion.so%2Fdify-Aimsales-2a99c708e4d880159321d1f2f87f64a3%3Fsource%3Dcopy_link' \
  -H 'accept: application/json'
```

## クイックスタート

```bash
# Dockerでビルド＆起動
docker compose up --build

# ホスト上で直接実行する場合（Python 3.9+ 必須）
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Vercelへのデプロイ

リポジトリには `vercel.json` と `api/index.py`（`main.py` のFastAPIアプリをインポートするサーバレスエントリ）が含まれています。通常のVercelワークフローでデプロイしてください:

```bash
npm i -g vercel          # 初回のみ
vercel login             # マシンごとに1回
vercel link              # リポジトリ内で実行してVercelプロジェクトに紐付け
vercel deploy --prod     # FastAPIのサーバレス関数をビルドして本番デプロイ
```

`vercel dev` をローカルで動かせば、Dockerと同じFastAPIルートを通るリクエストを再現できます。

## API

| メソッド | パス | 説明 |
| -------- | ---- | ---- |
| `GET` | `/url/reader/{target_url}` | 指定URLのMarkdownを返します。パス以降に完全なURLを入れると、FastAPIが残りのパスをすべて取り込みます。 |

リクエスト例:

```
GET /url/reader/https://www.notion.so/dify-Aimsales-2a99c708e4d880159321d1f2f87f64a3?source=copy_link
```

レスポンス例（一部省略）:

```json
{
  "source_url": "https://www.notion.so/dify-Aimsales-…",
  "final_url": "https://www.notion.so/dify-Aimsales-…?pvs=4",
  "title": "【dify読み込み用】Aimsales概要",
  "word_count": 240,
  "metadata": {
    "normalizer": "notion-reader-mode",
    "renderer": "notion-api"
  },
  "markdown": "# Heading…"
}
```

## 仕組み

- **url2markdownパイプライン** – `newspaper3k` で記事を抽出し、`markdownify` で整形済みHTMLをMarkdown化。
- **HTMLサニタイズ** – スクリプトやスタイル、ナビ/フッター、フォームなどのボイラープレートを除去してから変換。
- **動的レンダリング** – すべてHTTP経由で完結。Notionページは `notion-api.splitbee.io` 経由、Google Docsは `export?format=html` へ書き換え、難しいページは `https://r.jina.ai/<original_url>` のスナップショットにフォールバック。
- **特殊URL処理** – Google Docsは自動で `export?format=html` へ、Notionリンクには印刷向けの `?pvs=4` を付与。

## ローカルテスト

```bash
# example.comに対する簡単なスモークテスト
python - <<'PY'
import asyncio
from services.url_reader import convert_url_to_markdown
async def main():
    result = await convert_url_to_markdown("https://example.com")
    print(result.title, result.word_count)
asyncio.run(main())
PY
```

サーバーを起動した状態で `http://localhost:8000/docs` にアクセスすれば、Swagger UIから手動でAPIを試せます。
