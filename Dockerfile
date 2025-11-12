# syntax=docker/dockerfile:1.4

# Python 3.12-slim 公式イメージを使用
FROM python:3.12-slim AS builder

WORKDIR /app

# 1) 依存ファイルのみ先にコピー
COPY requirements.txt .

# 2) BuildKitのcacheマウント機能を使ってインストール
#    pipによるダウンロードキャッシュを /root/.cache/pip に保持し、次回以降のbuildを高速化
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install -r requirements.txt && \
    pip3 install python-multipart


# 3) ソースコードをまとめてコピー
COPY . .

# ---- Final ステージ ----
FROM python:3.12-slim AS final

WORKDIR /app

# builderステージから /usr/local と /app をコピー
COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app

# finalステージの apt-get は削除（前段で済ませている＆python同梱イメージのため）
# ENV PATH="/usr/local/bin:${PATH}" は必須なので再度指定
ENV PATH="/usr/local/bin:${PATH}"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
