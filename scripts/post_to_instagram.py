# -*- coding: utf-8 -*-
"""
Instagram自動投稿スクリプト
GitHub Actionsから定期実行され、GitHubリポジトリ内の画像を
Instagram Graph API経由で自動投稿する。

【仕組み】
- 状態(どこまで投稿したか)をファイルに保存せず、日付計算だけで
  「今日が投稿日か」「何枚目を投稿するか」を決定する(ステートレス設計)。
- そのため、実行に失敗しても次回リトライで整合性が崩れない。

【必要なGitHub Secrets】
- IG_USER_ID      : InstagramのユーザーID (Meta for Developersで確認した数字)
- IG_ACCESS_TOKEN : Instagram Graph APIのアクセストークン
"""

import os
import re
import sys
import time
import datetime
import urllib.parse

import requests

# ============ 設定項目 (ここを編集してください) ============
START_DATE = "2026-09-23"      # 投稿を開始する基準日 (YYYY-MM-DD形式)
INTERVAL_DAYS = 1              # 何日おきに投稿するか (2〜3日に1回なら 3 を推奨)
REPO_OWNER = "tokumeikibouni-bit"   # GitHubのユーザー名
REPO_NAME = "car-images"            # リポジトリ名
REPO_BRANCH = "main"                 # ブランチ名
IMAGES_DIR = "."                      # 画像が入っているフォルダ名 (ルート直下なので ".")
# =========================================================

GRAPH_API_VERSION = "v21.0"


def get_env_or_exit(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"[エラー] 環境変数 {name} が設定されていません。")
        sys.exit(1)
    return value


def list_image_files() -> list:
    """リポジトリ内の画像フォルダから、番号付きファイルを取得し順番に並べる"""
    if not os.path.isdir(IMAGES_DIR):
        print(f"[エラー] 画像フォルダ '{IMAGES_DIR}' が見つかりません。")
        sys.exit(1)

    files = []
    for filename in os.listdir(IMAGES_DIR):
        if not filename.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        match = re.search(r"\((\d+)\)", filename)
        number = int(match.group(1)) if match else 0
        files.append((number, filename))

    if not files:
        print(f"[エラー] '{IMAGES_DIR}' フォルダ内に画像が見つかりません。")
        sys.exit(1)

    files.sort(key=lambda x: x[0])
    return [f[1] for f in files]


def build_caption(filename: str) -> str:
    """ファイル名から「メーカー_車種_年式」を抜き出してキャプションを作る"""
    base = filename.rsplit(".", 1)[0]
    base = base.split(" (")[0]
    parts = base.split("_")

    maker = parts[0] if len(parts) > 0 else ""
    model = parts[1] if len(parts) > 1 else ""
    year = parts[2] if len(parts) > 2 else ""

    caption = f"{maker} {model}\n{year}年式\n\n#{maker} #{model} #旧車 #自動車 #車好き"
    return caption


def calc_today_index(total_images: int):
    """今日が投稿日かどうか、投稿するなら何番目の画像かを計算する"""
    start = datetime.date.fromisoformat(START_DATE)
    today = datetime.date.today()
    days_since_start = (today - start).days

    if days_since_start < 0:
        print("[情報] まだ開始日に達していません。投稿をスキップします。")
        return None

    if days_since_start % INTERVAL_DAYS != 0:
        print("[情報] 今日は投稿日ではありません。スキップします。")
        return None

    cycle_position = (days_since_start // INTERVAL_DAYS) % total_images
    return cycle_position


def build_image_url(filename: str) -> str:
    if IMAGES_DIR in (".", ""):
        relative_path = filename
    else:
        relative_path = f"{IMAGES_DIR}/{filename}"
    encoded_path = urllib.parse.quote(relative_path)
    return (
        f"https://raw.githubusercontent.com/"
        f"{REPO_OWNER}/{REPO_NAME}/{REPO_BRANCH}/{encoded_path}"
    )


def create_media_container(ig_user_id: str, access_token: str, image_url: str, caption: str) -> str:
    url = f"https://graph.instagram.com/{GRAPH_API_VERSION}/{ig_user_id}/media"
    payload = {
        "image_url": image_url,
        "caption": caption,
        "access_token": access_token,
    }
    response = requests.post(url, data=payload, timeout=60)
    data = response.json()
    if "id" not in data:
        print(f"[エラー] メディアコンテナの作成に失敗しました: {data}")
        sys.exit(1)
    return data["id"]


def publish_media(ig_user_id: str, access_token: str, creation_id: str) -> None:
    url = f"https://graph.instagram.com/{GRAPH_API_VERSION}/{ig_user_id}/media_publish"
    payload = {
        "creation_id": creation_id,
        "access_token": access_token,
    }
    response = requests.post(url, data=payload, timeout=60)
    data = response.json()
    if "id" not in data:
        print(f"[エラー] 投稿の公開に失敗しました: {data}")
        sys.exit(1)
    print(f"[成功] 投稿が公開されました。メディアID: {data['id']}")


def main():
    ig_user_id = get_env_or_exit("IG_USER_ID")
    access_token = get_env_or_exit("IG_ACCESS_TOKEN")

    image_files = list_image_files()
    index = calc_today_index(len(image_files))

    if index is None:
        return

    filename = image_files[index]
    image_url = build_image_url(filename)
    caption = build_caption(filename)

    print(f"[情報] 投稿対象: {filename}")
    print(f"[情報] 画像URL: {image_url}")
    print(f"[情報] キャプション:\n{caption}")

    creation_id = create_media_container(ig_user_id, access_token, image_url, caption)
    time.sleep(5)
    publish_media(ig_user_id, access_token, creation_id)


if __name__ == "__main__":
    main()
