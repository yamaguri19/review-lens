# Review Lens MVP

商品検索、レビュー本文の簡易分類、ValueCommerce経由の購入リンク表示、クリック計測を行うStreamlitアプリです。

## 今回の実装範囲

- Yahoo!ショッピング商品検索API（V3）
- Yahoo! APIの `affiliate_type=vc` / `affiliate_id` によるValueCommerceアフィリエイトURL生成
- 購入先リンクをReview Lens内の計測URL経由で開く
- SQLiteでクリック日時・商品名・ショップを記録
- 管理者キーを設定した場合のみ、累計・当日・商品別クリック数を表示
- Amazon連携は未実装
- レビュー本文は利用条件に従って確認した文章を利用者が貼り付ける方式。自動取得・無断スクレイピングは行いません。

## 1. ローカル起動

Python 3.10以上を推奨します。

```bash
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# macOS / Linux
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## 2. APIキー・アフィリエイト設定

プロジェクト直下に `.streamlit` フォルダを作り、その中に `secrets.toml` を作成します。

```toml
YAHOO_APP_ID = "Yahoo!デベロッパーネットワークのClient ID"
YAHOO_VC_AFFILIATE_ID = "ValueCommerceの手順で作成したURLエンコード済みaffiliate_id"
ADMIN_DASHBOARD_KEY = "管理画面用の推測されにくいパスワード"
```

`ADMIN_DASHBOARD_KEY` は任意です。設定しない場合、アプリ内のクリック集計パネルは表示されません。

### Yahoo!ショッピング × ValueCommerceの設定手順

1. ValueCommerceに登録し、運営するReview Lensのサイトを登録・審査に出します。
2. ValueCommerce管理画面でYahoo!ショッピングと提携します（提携可能な状態・条件は管理画面で確認）。
3. 広告作成画面から「自由テキストリンク」のHTMLコードを作成します。
4. HTML内のリンクURL（`ck.jp.ap.valuecommerce.com/servlet/referral?...sid=...&pid=...`）をコピーします。
5. そのURLの末尾に `&vc_url=` を付け、URL全体をURLエンコードします。
6. エンコードした文字列を `YAHOO_VC_AFFILIATE_ID` に設定します。
7. Yahoo!デベロッパーネットワークで取得したClient IDを `YAHOO_APP_ID` に設定します。
8. アプリを再起動して商品検索を行い、表示された購入リンクを実際に開いて遷移を確認します。

重要：ValueCommerceのsid/pidは本人の管理画面で発行されたものを使ってください。他人の値を流用しないでください。提携審査や広告主側の条件が完了していない場合、成果対象にならないことがあります。

## 3. Streamlit Community Cloudで公開

1. プロジェクトをGitHubリポジトリへアップロード
2. Streamlit Community Cloudでリポジトリを選びデプロイ
3. アプリのSettings > Secretsに上記TOML設定を登録
4. GitHubへ `.streamlit/secrets.toml` をコミットしない

## 4. クリック計測の仕様と制約

- 購入ボタンの遷移先は、Yahoo! APIから返ったアフィリエイトURLです。アプリ側でsid/pidやURLを独自に組み立てません。
- `?out=<ランダムトークン>` の内部URLにアクセスした時点でクリックを1件記録し、販売ページへ転送します。
- この計測値はReview Lens上のクリック数であり、ValueCommerceの承認済み成果・報酬額ではありません。成果はValueCommerce管理画面で確認してください。
- SQLiteファイルは `REVIEW_LENS_DB_PATH` 環境変数で保存先を変更できます。
- Streamlit Community Cloudのローカルファイルは永続保存が保証されません。再起動・再デプロイで計測DBが消える可能性があります。本番公開前にSupabase/PostgreSQL等の永続DBへ移行してください。
- 現段階ではIPアドレスや個人を特定する情報は保存しません。

## 5. 商用公開前の確認事項

- ValueCommerceのサイト審査、Yahoo!ショッピングとの提携、広告表示条件
- Yahoo! APIの最新利用規約・商用利用条件・クレジット表示条件
- アフィリエイトであることの明瞭な表示（本アプリでは購入リンク付近に表示）
- プライバシーポリシー、問い合わせ先、免責事項
- 商品情報・画像・価格の表示条件、キャッシュ条件
- Streamlit Community Cloudの公開・商用利用条件
- 本番用の永続DB、バックアップ、エラー監視

## 6. 現時点の限界

- ValueCommerceの商品APIは、サイト審査、広告主との提携、トークン取得等が別途必要なため、このMVPでは利用していません。Yahoo!ショッピングAPIをValueCommerceアフィリエイト設定付きで呼び出す方式です。
- Amazon API・Amazonアソシエイトリンクは未実装です。
- 楽天APIは今回のASP方針に合わせて検索対象から外しています。
- レビュー平均・件数とレビュー本文は別データです。本文の自動取得は行いません。
