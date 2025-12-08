# llm-trader-battle

LLM（GPT / Gemini / Claude / Grok など）が週初に日本株を2銘柄ずつピックし、その週のリターンを比較するゲーム用ツールです。実際の売買は行いません。

## 仕様ハイライト
- **データ取得**: `yfinance` を使用。日本株ティッカーは `7203.T` のようにコード+取引所を使用します。
- **マーケットカレンダー**: 平日かつ `jpholiday` 非対象日のみ取引日とみなします。月曜が祝日の場合は次の取引日に始値を取り、金曜が休場なら次の取引日に終値を取ります。
- **タイムゾーン**: 内部では `Asia/Tokyo` を基準に計算し、記録時刻は UTC へ変換します（JSON に ISO 8601 で保存）。
- **LLMピック**: 現状はダミー（決め打ち）で生成。実際の LLM 呼び出しロジックを差し替えて運用してください。
- **データ保存**: GitHub リポジトリ内にファイルとして保存（DB 不使用）。週次ごとに `data/weeks/<YYYY-MM-DD>/` 配下へ蓄積、レポートは `reports/` に Markdown で出力。
- **GitHub Actions**: uv を使って3本の定期バッチを実行し、自動コミット/Pushします。

## ディレクトリ構成（主要）
- `src/llm_trader_battle/` : アプリ本体
- `data/weeks/<YYYY-MM-DD>/` : ピック・価格・週次レポート
- `reports/summary.md` : 累積サマリ
- `.github/workflows/` : 週次バッチ（ピック、始値、終値+レポート）

## コマンド（uv 経由）
- ピック生成: `uv run llm-trader-battle generate-picks --week 2025-01-06`
- 始値取得: `uv run llm-trader-battle fetch-open --week 2025-01-06`
- 終値取得: `uv run llm-trader-battle fetch-close --week 2025-01-06`
- レポート生成: `uv run llm-trader-battle report --week 2025-01-06`

### 週の決め方
- 週IDは **月曜日の日付（JST）** を `YYYY-MM-DD` で用います。
- `--week` を省略した場合、現在日時（JST）を含む週の月曜日が自動で採用されます。

### マーケットカレンダー仕様
- 取引日: 平日かつ `jpholiday` で祝日判定されない日。
- 始値取得日: 週の月曜日が休場なら、次の取引日を使用。
- 終値取得日: 週の金曜日が休場なら、次の取引日を使用。

## GitHub Actions スケジュール（UTC / JST）
- `Weekly Picks`: `0 23 * * SUN` （JST 月曜 08:00）
- `Fetch Open`: `10 0 * * MON` （JST 月曜 09:10）
- `Fetch Close & Report`: `30 6 * * FRI` （JST 金曜 15:30）

すべて `contents: write` 権限で自動コミット/Pushします。失敗時は GitHub Actions の通知に任せます。

## レポート出力仕様
- 週次レポート (`data/weeks/<week>/result.md`): LLMごとに2銘柄の始値・終値・リターンと、その2銘柄の平均リターンを掲載。LLM別平均リターンのバーグラフ（`llm_week.png`）を同ページに埋め込み。
- サマリ (`reports/summary.md`): 週ごと×LLMごとの平均リターンを表形式で掲載（欠損は `N/A`）。週ID（日付）を横軸にした折れ線グラフ（`summary.png`）でLLM別推移を埋め込み。

## 今後差し替えるポイント
- **LLM 呼び出しロジック**: `src/llm_trader_battle/picks.py` の `generate_stub_picks` を実際の LLM API 呼び出しに置き換え、環境変数や Secrets を参照してください。
- **レポート形式**: 必要に応じてチャートやより詳細な指標（勝率、ドローダウン等）を追加してください。

