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

【必要なGitHub Variables または環境変数(このファイル内で直接設定)】
- START_DATE      : 投稿を開始した基準日 (YYYY-MM-DD)
- INTERVAL_DAYS    : 投稿間隔(日数) 例: 3
- REPO_OWNER      : GitHubのユーザー名
- REPO_NAME       : リポジトリ名 (例: car-images)
- REPO_BRANCH     : ブランチ名 (通常 "main")
- IMAGES_DIR      : リポジトリ内の画像フォルダ名 (例: "images")
"""

import os
import re
import sys
import time
import base64
import datetime
import urllib.parse

import requests

ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"

# ============ 設定項目 (ここを編集してください) ============
START_DATE = "2026-09-20"      # 投稿を開始する基準日 (YYYY-MM-DD形式)
INTERVAL_DAYS = 3              # 何日おきに投稿するか (2〜3日に1回なら 3 を推奨)
REPO_OWNER = "tokumeikibouni-bit"   # GitHubのユーザー名
REPO_NAME = "car-images"            # リポジトリ名
REPO_BRANCH = "main"                 # ブランチ名
IMAGES_DIR = "."                      # 画像が入っているフォルダ名 (リポジトリのルート直下の場合は ".")
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


def describe_image_with_ai(image_path: str) -> str:
    """
    Anthropic APIを使い、画像の内容を見て日本語の一言説明文を生成する。
    ANTHROPIC_API_KEYが未設定、またはAPI呼び出しに失敗した場合は
    空文字を返す(その場合キャプションは説明文なしで投稿される)。
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[情報] ANTHROPIC_API_KEY未設定のため、AI説明文はスキップします。")
        return ""

    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        ext = image_path.lower().rsplit(".", 1)[-1]
        media_type = "image/png" if ext == "png" else "image/jpeg"

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 100,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "この写真に写っている車の様子やシーン(場所・時間帯・"
                                    "構図など)を、Instagram投稿のキャプションに使う一言として"
                                    "日本語で20〜30文字程度で簡潔に説明してください。"
                                    "説明文だけを出力し、前置きや記号は不要です。"
                                ),
                            },
                        ],
                    }
                ],
            },
            timeout=60,
        )
        data = response.json()
        text = data["content"][0]["text"].strip()
        print(f"[情報] AI生成の説明文: {text}")
        return text
    except Exception as e:
        print(f"[警告] AI説明文の生成に失敗しました(スキップします): {e}")
        return ""


def build_caption(filename: str) -> str:
    """ファイル名から「メーカー_車種_年式」を抜き出し、AI生成の説明文と組み合わせてキャプションを作る"""
    base = filename.rsplit(".", 1)[0]   # 拡張子を除去
    base = base.split(" (")[0]           # " (1)" のような連番部分を除去
    parts = base.split("_")

    maker = parts[0] if len(parts) > 0 else ""
    model = parts[1] if len(parts) > 1 else ""
    year = parts[2] if len(parts) > 2 else ""

    image_path = os.path.join(IMAGES_DIR, filename)
    description = describe_image_with_ai(image_path)

    lines = [f"{maker} {model}", f"{year}年式"]
    if description:
        lines.append("")
        lines.append(description)
    lines.append("")
    lines.append(f"#{maker} #{model} #旧車 #自動車 #車好き")

    return "\n".join(lines)


def calc_today_index(total_images: int):
    """
    今日が投稿日かどうか、投稿するなら何番目の画像かを計算する。
    投稿日でなければ None を返す。
    """
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
    return cycle_position  # 0始まりのインデックス


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
        return  # 投稿日ではないので終了

    filename = image_files[index]
    image_url = build_image_url(filename)
    caption = build_caption(filename)

    print(f"[情報] 投稿対象: {filename}")
    print(f"[情報] 画像URL: {image_url}")
    print(f"[情報] キャプション:\n{caption}")

    creation_id = create_media_container(ig_user_id, access_token, image_url, caption)
    # Instagram側での画像取得・処理に少し時間がかかることがあるため待機
    time.sleep(5)
    publish_media(ig_user_id, access_token, creation_id)


if __name__ == "__main__":
    main()
