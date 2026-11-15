import json
import os
import re
import sqlite3
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Review Lens | AIレビュー分析", page_icon="🔎", layout="wide")

YAHOO_URL = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"
DB_PATH = os.getenv("REVIEW_LENS_DB_PATH", "review_lens_clicks.db")

POSITIVE_WORDS = [
    "良い", "よい", "便利", "満足", "快適", "使いやすい", "簡単", "軽い", "静か", "速い", "丈夫",
    "長持ち", "高品質", "きれい", "美しい", "コスパ", "おすすめ", "買ってよかった", "気に入", "最高",
    "問題ない", "期待以上", "素晴らしい", "おいしい", "安い",
]
NEGATIVE_WORDS = [
    "悪い", "不満", "壊れ", "故障", "不具合", "使いにくい", "うるさい", "重い", "遅い", "高い", "残念",
    "返品", "交換", "すぐに", "耐久性", "傷", "汚れ", "臭い", "におい", "痛い", "合わない", "期待外れ",
    "最悪", "おすすめしない", "説明書", "初期不良", "接続できない",
]
TOPIC_WORDS = [
    "耐久性", "バッテリー", "電池", "音質", "画質", "使いやすさ", "操作", "サイズ", "重さ", "価格", "コスパ",
    "配送", "梱包", "サポート", "説明書", "接続", "性能", "デザイン", "静音性", "臭い", "肌触り", "装着感",
    "初期不良", "保証",
]


def get_secret(name: str) -> str:
    try:
        value = st.secrets.get(name, "")
        if value:
            return str(value).strip()
    except Exception:
        pass
    return os.getenv(name, "").strip()


def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tracked_links (
                token TEXT PRIMARY KEY,
                product_name TEXT NOT NULL,
                shop_name TEXT NOT NULL,
                destination_url TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL,
                clicked_at TEXT NOT NULL,
                FOREIGN KEY(token) REFERENCES tracked_links(token)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clicks_clicked_at ON clicks(clicked_at)")


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def valid_affiliate_url(url: str) -> bool:
    """Yahoo APIから返ったURLのみを対象にし、危険なスキームを拒否する。"""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        allowed = (
            host == "shopping.yahoo.co.jp"
            or host.endswith(".shopping.yahoo.co.jp")
            or host == "ck.jp.ap.valuecommerce.com"
            or host.endswith(".valuecommerce.com")
        )
        return parsed.scheme == "https" and allowed
    except Exception:
        return False


def save_tracked_link(product: dict) -> str:
    token = uuid.uuid4().hex
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO tracked_links(token, product_name, shop_name, destination_url, created_at) VALUES (?, ?, ?, ?, ?)",
            (token, product.get("name", "商品名不明"), product.get("shop", "Yahoo!ショッピング"),
             product["url"], datetime.now(timezone.utc).isoformat()),
        )
    return token


def process_outbound_click():
    token = st.query_params.get("out")
    if not token:
        return
    if isinstance(token, list):
        token = token[0] if token else ""
    if not re.fullmatch(r"[a-f0-9]{32}", str(token)):
        st.error("リンク情報が正しくありません。商品検索からやり直してください。")
        st.stop()
    with db_connect() as conn:
        row = conn.execute(
            "SELECT product_name, destination_url FROM tracked_links WHERE token = ?", (token,)
        ).fetchone()
        if not row or not valid_affiliate_url(row["destination_url"]):
            st.error("リンクが見つからないか、安全性を確認できませんでした。")
            st.stop()
        conn.execute(
            "INSERT INTO clicks(token, clicked_at) VALUES (?, ?)",
            (token, datetime.now(timezone.utc).isoformat()),
        )
        destination = row["destination_url"]
    st.title("購入先へ移動しています")
    st.write(f"{row['product_name']} の販売ページを開いています。")
    components.html(
        "<script>window.top.location.href = " + json.dumps(destination) + ";</script>",
        height=0,
    )
    st.markdown(f"[自動で移動しない場合はこちら]({destination})")
    st.stop()


def search_yahoo(keyword: str, limit: int = 10) -> tuple[list[dict], str | None]:
    app_id = get_secret("YAHOO_APP_ID")
    vc_affiliate_id = get_secret("YAHOO_VC_AFFILIATE_ID")
    if not app_id:
        return [], "YAHOO_APP_ID が未設定です。READMEの設定手順を確認してください。"
    if not vc_affiliate_id:
        return [], "YAHOO_VC_AFFILIATE_ID が未設定です。ValueCommerceで作成したURLを設定してください。"

    params = {
        "appid": app_id,
        "query": keyword,
        "results": min(max(limit, 1), 50),
        "sort": "-review_count",
        "condition": "new",
        "affiliate_type": "vc",
        "affiliate_id": vc_affiliate_id,
        "image_size": 300,
    }
    try:
        response = requests.get(YAHOO_URL, params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()
        hits = payload.get("hits", [])
        normalized = []
        for item in hits:
            review = item.get("review") or {}
            image = item.get("image") or {}
            affiliate_url = item.get("url", "")
            normalized.append({
                "site": "Yahoo!ショッピング",
                "name": item.get("name", "商品名不明"),
                "price": safe_int(item.get("price")),
                "rating": review.get("rate"),
                "review_count": safe_int(review.get("count")),
                "url": affiliate_url if valid_affiliate_url(affiliate_url) else "",
                "image": image.get("medium", ""),
                "shop": (item.get("seller") or {}).get("name", ""),
            })
        return normalized, None
    except requests.RequestException as exc:
        return [], f"Yahoo!ショッピングAPIへの接続に失敗しました: {exc}"
    except (ValueError, TypeError) as exc:
        return [], f"Yahoo!ショッピングAPIの応答を読み取れませんでした: {exc}"


def split_reviews(raw: str) -> list[str]:
    chunks = re.split(r"(?:\r?\n){1,}|(?<=[。！？!?])\s*", raw)
    return [x.strip(" ・-　\t") for x in chunks if len(x.strip()) >= 8]


def analyze_reviews(raw: str) -> dict:
    reviews = split_reviews(raw)
    positive, negative, neutral = [], [], []
    topic_counts = Counter()
    for review in reviews:
        pos_hits = [w for w in POSITIVE_WORDS if w in review]
        neg_hits = [w for w in NEGATIVE_WORDS if w in review]
        for topic in TOPIC_WORDS:
            if topic in review:
                topic_counts[topic] += 1
        if len(pos_hits) > len(neg_hits):
            positive.append(review)
        elif len(neg_hits) > len(pos_hits):
            negative.append(review)
        else:
            neutral.append(review)
    return {
        "reviews": reviews, "positive": positive, "negative": negative,
        "neutral": neutral, "topics": topic_counts.most_common(8),
    }


def render_products(products: list[dict]):
    if not products:
        st.info("商品が見つかりませんでした。別のキーワードでもお試しください。")
        return
    for product in products:
        with st.container(border=True):
            cols = st.columns([1, 4])
            with cols[0]:
                if product.get("image"):
                    st.image(product["image"], use_container_width=True)
                else:
                    st.markdown("🛍️")
            with cols[1]:
                st.markdown(f"**{product['name']}**")
                price = f"¥{product['price']:,}" if product["price"] else "価格情報なし"
                rating = product["rating"] if product["rating"] not in (None, "") else "未掲載"
                st.write(f"{price}　｜　評価：{rating}　｜　レビュー件数：{product['review_count']:,}")
                if product.get("shop"):
                    st.caption(f"販売店：{product['shop']}")
                if product.get("url"):
                    token = product.get("_tracking_token")
                    if not token:
                        token = save_tracked_link(product)
                        product["_tracking_token"] = token
                    tracked_url = f"?out={token}"
                    st.link_button("Yahoo!ショッピングで購入先を見る", tracked_url, use_container_width=False)
                    st.caption("※このリンクはアフィリエイトリンクです。購入により運営者に報酬が発生する場合があります。")
                else:
                    st.warning("アフィリエイトURLを確認できなかったため、購入リンクを表示していません。")
                st.caption("取得元：Yahoo!ショッピングAPI。価格・評価・件数は掲載時点の情報です。")


def render_admin_metrics():
    admin_key = get_secret("ADMIN_DASHBOARD_KEY")
    if not admin_key:
        return
    with st.sidebar.expander("管理者用クリック集計"):
        entered = st.text_input("管理キー", type="password", key="admin_key_input")
        if entered and entered == admin_key:
            with db_connect() as conn:
                total = conn.execute("SELECT COUNT(*) AS n FROM clicks").fetchone()["n"]
                today = datetime.now(timezone.utc).date().isoformat()
                today_count = conn.execute(
                    "SELECT COUNT(*) AS n FROM clicks WHERE substr(clicked_at, 1, 10) = ?", (today,)
                ).fetchone()["n"]
                top = conn.execute("""
                    SELECT t.product_name, t.shop_name, COUNT(c.id) AS clicks
                    FROM clicks c JOIN tracked_links t ON t.token = c.token
                    GROUP BY t.product_name, t.shop_name ORDER BY clicks DESC LIMIT 10
                """).fetchall()
            st.metric("累計クリック", total)
            st.metric("本日クリック（UTC基準）", today_count)
            st.markdown("**クリック上位商品**")
            if top:
                for item in top:
                    st.write(f"{item['product_name']}：{item['clicks']}回")
            else:
                st.caption("まだクリックはありません。")
        elif entered:
            st.error("管理キーが違います。")


init_db()
process_outbound_click()

st.title("🔎 Review Lens")
st.subheader("買う前に、口コミを読み解く。")
st.write("商品情報を検索し、レビュー本文の良い点・気になる点を整理します。")

with st.sidebar:
    st.header("検索設定")
    limit = st.slider("商品表示数", 3, 20, 10)
    st.caption("現在の購入先連携：Yahoo!ショッピング × ValueCommerce")
    st.divider()
    st.caption("レビュー本文の自動取得には対応していません。")
    render_admin_metrics()

tab_search, tab_analysis, tab_about = st.tabs(["🛒 商品検索", "📝 レビュー分析", "ℹ️ このアプリについて"])

with tab_search:
    st.markdown("### 商品を探す")
    keyword = st.text_input("商品名・型番", placeholder="例：Anker Soundcore Liberty 5")
    if st.button("商品を検索", type="primary", use_container_width=True):
        if len(keyword.strip()) < 2:
            st.warning("商品名を2文字以上入力してください。")
        else:
            with st.spinner("Yahoo!ショッピングを検索しています..."):
                items, error = search_yahoo(keyword.strip(), limit)
            st.session_state["last_products"] = items
            st.session_state["last_keyword"] = keyword.strip()
            if error:
                st.warning(error)
            if not items:
                st.info("取得できた商品情報がありません。APIキー・ValueCommerce設定と検索語を確認してください。")
            else:
                st.success(f"{len(items)}件の商品情報を取得しました。")
                render_products(items)
    elif st.session_state.get("last_products"):
        st.caption(f"前回の検索：{st.session_state.get('last_keyword', '')}")
        render_products(st.session_state["last_products"])

with tab_analysis:
    st.markdown("### レビュー本文を分析")
    st.write("利用条件に従って確認したレビュー本文を貼り付けてください。1レビューごとに改行すると分類しやすくなります。")
    review_text = st.text_area("レビュー本文", height=240, placeholder="例：\n音質が良く、装着感も快適です。\n数か月で充電できなくなりました。\n価格の割に機能が充実していて満足です。")
    if st.button("レビューを分析", type="primary", use_container_width=True):
        if len(review_text.strip()) < 20:
            st.warning("分析するレビューを20文字以上入力してください。")
        else:
            st.session_state["analysis_result"] = analyze_reviews(review_text)
    result = st.session_state.get("analysis_result")
    if result:
        total = len(result["reviews"])
        c1, c2, c3 = st.columns(3)
        c1.metric("良い評価", f"{len(result['positive'])}件")
        c2.metric("悪い評価", f"{len(result['negative'])}件")
        c3.metric("中立・判定保留", f"{len(result['neutral'])}件")
        st.caption(f"分析対象：{total}件（文章の区切りから推定）")
        left, right = st.columns(2)
        with left:
            st.markdown("##### 👍 良い評価")
            for item in result["positive"][:10]:
                st.write(f"・{item}")
            if not result["positive"]:
                st.write("明確なポジティブ表現は検出されませんでした。")
        with right:
            st.markdown("##### 👎 悪い評価")
            for item in result["negative"][:10]:
                st.write(f"・{item}")
            if not result["negative"]:
                st.write("明確なネガティブ表現は検出されませんでした。")
        st.markdown("##### よく登場する話題")
        st.write("、".join([f"{word}（{count}）" for word, count in result["topics"]]) or "頻出する話題を特定できませんでした。")
        st.info("これは辞書ベースの簡易分類です。文脈・皮肉・否定表現を完全には理解できず、AIによるサクラ判定ではありません。")

with tab_about:
    st.markdown("### Review Lensについて")
    st.write("Review Lensは、商品選びで見落としがちな不満点や注意点を整理するための試作サービスです。")
    st.markdown("**現在できること**")
    st.write("- Yahoo!ショッピングの商品検索APIから商品情報を取得")
    st.write("- ValueCommerce経由のアフィリエイト購入リンクを表示")
    st.write("- 購入リンクのクリック数を記録（試作版ではSQLite）")
    st.write("- 入力されたレビュー本文を簡易分類")
    st.markdown("**現在できないこと**")
    st.write("- Amazon・楽天・Yahoo!のレビュー本文を自動で一括取得")
    st.write("- 購入・成果報酬の確定（ValueCommerce管理画面で確認）")
    st.write("- サクラレビューの確定判定")
    st.caption("広告・アフィリエイトリンクを含みます。商品価格・在庫・掲載内容は販売サイトでご確認ください。")
    st.caption("試作版のクリックDBは実行環境のローカルSQLiteに保存されます。Streamlit Cloudでは再起動・再デプロイ等で消える可能性があるため、本番運用では永続DBへの移行が必要です。")
