# llm-trader-battle

LLM（GPT / Gemini / Claude / Grok など）が週初に日本株を2銘柄ずつピックし、その週のリターンを比較するゲーム用ツールです。実際の売買は行いません。ピック対象の銘柄は LLM が自分で考えて選びます。

## 仕様ハイライト
- **データ取得**: `yfinance` を使用。日本株ティッカーは `7203.T` のようにコード+取引所を使用します。
- **マーケットカレンダー**: 平日かつ `jpholiday` 非対象日のみ取引日とみなし、さらに `data/calendar/manual_closed_dates.json` に列挙した半休日・臨時休場日もスキップします。月曜が祝日の場合は次の取引日に始値を取り、金曜が休場なら次の取引日に終値を取ります。
- **タイムゾーン**: 内部では `Asia/Tokyo` を基準に計算し、記録時刻は UTC へ変換します（JSON に ISO 8601 で保存）。
- **LLMピック**: 各 LLM クライアントを実際に呼び出してピックを生成します。銘柄ユニバースは固定せず、LLM が自ら選びます。
- **データ保存**: GitHub リポジトリ内にファイルとして保存（DB 不使用）。週次ピック/日次価格/日次結果はいずれもフラットな日付付きファイル名（JSON・Markdown）で管理。
- **GitHub Actions**: uv を使って3本の定期バッチを実行し、自動コミット/Pushします。

## ディレクトリ構成（主要）
- `src/llm_trader_battle/` : アプリ本体
- `data/picks/picks-<week>.json` : ピック（model ごとに銘柄・理由を含むオブジェクト形式）
- `data/prices/prices-<YYYY-MM-DD>.json` : その日1日の OHLC ロング形式
- `data/result/result-<YYYY-MM-DD>.json` : 日次リザルト（llm_avg と銘柄別リターン）
- `data/result/result-<YYYY-MM-DD>.md` : 日次リザルト（Markdown）
- `reports/<YYYYMM>/summary.md` : 月次サマリ（summary.png を埋め込み）
- `.github/workflows/weekly-picks.yml` : 週末ピック（手動時は week_start を任意指定可）
- `.github/workflows/daily-prices.yml` : 日次価格取得（手動時は date を任意指定可）
- `.github/workflows/daily-aggregate.yml` : 日次集計（手動時は date を任意指定可）

## コマンド（uv 経由）
- 週次ピック（週末実行）: `uv run llm-trader-battle predict --week-start 2025-01-06`（省略時は次の月曜を自動推定）
- 日次価格取得（16:00以降・取引日だけ実行）: `uv run llm-trader-battle fetch-daily --date 2025-01-06`
- 日次集計（17:00以降・取引日だけ実行）: `uv run llm-trader-battle aggregate-daily --date 2025-01-06`

### `uv sync` が失敗する場合（開発環境向け）
一部の環境（例: Codespaces / Dev Container のワークスペースマウント）では、`.venv` をリポジトリ直下に作ると
ファイルシステムの都合で `uv sync` が `No such file or directory (os error 2)` で失敗することがあります。

その場合は、仮想環境の作成先をホームディレクトリ側に逃がすと解消します:

- `export UV_PROJECT_ENVIRONMENT="$HOME/.venv-llm-trader-battle"`
- `uv sync`

### LLMを1つだけ動かす方法
- `predict` 実行時に `--llms` で1件だけ指定します（例: GPT だけ動かす）:
	- `uv run llm-trader-battle predict --week-start 2025-12-15 --llms gpt`
	- 同様に `--llms gemini` / `--llms claude` / `--llms grok` で単体実行できます。

### 週の決め方
- 週IDは **月曜日の日付（JST）** を `YYYY-MM-DD` で用います（週末のピック時に翌週の月曜を自動算出）。

### マーケットカレンダー仕様
- 取引日: 平日かつ `jpholiday` で祝日判定されない日。
- 追加の休場日: `data/calendar/manual_closed_dates.json` に ISO 日付 (`YYYY-MM-DD`) の配列で記述すると、その日も非取引日扱いになります（半休日や臨時休場日を想定）。
- 週内の最初に取得できた始値を「購入価格」とみなし、以降の日次終値でリターンを算出。

## GitHub Actions スケジュール（UTC / JST）
- 週末ピック: `0 23 * * SAT` （JST 日曜 08:00）
- 日次価格取得: `0 7 * * *` （JST 16:00）
- 日次集計: `0 8 * * *` （JST 17:00）

すべて `contents: write` 権限で自動コミット/Pushします。失敗時は GitHub Actions の通知に任せます。

## レポート出力仕様
- 日次レポート (`data/result/result-<date>.md` / `.json`): 当日の始値（週内の初回取引日）と終値から銘柄別リターン・LLM平均を掲載。
- 月次サマリ (`reports/<YYYYMM>/summary.md`): 日ごと×LLMごとの平均リターン表、折れ線グラフ（`summary.png`）、週ごとのホールディング一覧（週初→週末の銘柄）が含まれます。

## 今後差し替えるポイント
- **LLM 呼び出しロジック**: `src/llm_trader_battle/llm_clients/` 配下の各クライアントを運用環境に合わせて調整してください（プロンプトやフォーマット変更など）。
- **レポート形式**: 必要に応じてチャートやより詳細な指標（勝率、ドローダウン等）を追加してください。

- GPT (Azure OpenAI Responses API): `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT_GPT` (例: `gpt-5.1-thinking`)
- Grok (公式SDK/Responses互換): `GROK_ENDPOINT`, `GROK_API_KEY`, `GROK_MODEL` (例: `grok-4`) — 別名として `XAI_ENDPOINT`, `XAI_API_KEY` も使用可。
- Gemini (Google Generative AI SDK): `GEMINI_API_KEY`, optional `GEMINI_MODEL` (例: `gemini-2.5-pro`)
- Claude (Anthropic SDK): `ANTHROPIC_API_KEY`, optional `CLAUDE_MODEL` (例: `claude-4.5-sonnet`)
いずれか欠けた場合はエラーになります。

### 環境変数の読み込み
開発時はリポジトリ直下の `.env` に上記キーを記載すれば、自動で読み込まれます（`python-dotenv` を利用）。

