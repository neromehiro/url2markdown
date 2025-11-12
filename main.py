# main.py

from fastapi import FastAPI, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import os
import logging
from datetime import datetime, timedelta
from db import get_db_connection
import requests
from module.sample.proxy_rotate_check import get_rotating_proxy, check_ip_with_proxy_and_sleep
# main.py 

 

# ロギングの設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# FastAPIアプリケーションの初期化
app = FastAPI()

# CORS 設定
app.add_middleware( 
    CORSMiddleware,
    allow_origins=["*"],  # または特定のオリジンを指定
    allow_credentials=True,
    allow_methods=["*"],  # すべてのメソッドを許可（GET, POST, OPTIONS など）
    allow_headers=["*"],  # 任意のヘッダーを許可
)





###

# デプロイ情報の取得
APP_VERSION = os.environ.get("APP_VERSION", "Unknown")
DEPLOYMENT_TIME = os.environ.get("DEPLOYMENT_TIME", "Unknown")
COMMIT_MESSAGE = os.environ.get("COMMIT_MESSAGE", "No commit message")


@app.get("/")
def read_root():
    # JSONResponseを使用して明示的にJSONレスポンスを返す
    return JSONResponse(content={
        "アプリバージョン": APP_VERSION,
        "最終デプロイ日時": format_time(DEPLOYMENT_TIME),
        "コミットメッセージ": COMMIT_MESSAGE
    })
def format_time(time_str):
    if time_str and time_str != "Unknown":
        try:
            deploy_time = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ")
            deploy_time_jst = deploy_time + timedelta(hours=9)
            return deploy_time_jst.strftime("デプロイ : %-m/%-d %-H:%M")
        except ValueError:
            return time_str
    return "不明"


@app.get("/proxy-rotate-check")
async def proxy_rotate_check():
    """
    ローテーションプロキシ経由でIPアドレスを確認するエンドポイント
    """
    try:
        # Webshareの認証情報
        username = "oaghpvrh-rotate"
        password = "ak24ante1ua4"
        
        # プロキシ経由でIPアドレスを取得
        ip_address = await check_ip_with_proxy_and_sleep(username, password)
        
        # ローテーションプロキシのIPを取得（オプション）
        rotating_proxy_ip = get_rotating_proxy()
        
        return {
            "status": "success",
            "ip": ip_address,
            "rotating_proxy_ip": rotating_proxy_ip,
            "message": "プロキシローテーション経由の現在のIPアドレスです"
        }
    except Exception as e:
        logger.error("プロキシローテーション経由のIPアドレス取得エラー: %s", str(e))
        return {
            "status": "error",
            "message": f"エラーが発生しました: {str(e)}"
        }

# サーバー起動（開発環境用） 
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
