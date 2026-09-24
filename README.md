# employee-id-system バックエンド セットアップ手順

統一社員番号管理アプリケーションのFastAPIバックエンドです。開発環境はDocker上のPostgres、本番環境はVercel + Supabaseで動作します。

このドキュメントは、リポジトリを`git clone`した直後から、ローカル開発・本番デプロイまでを一通り再現できるようにまとめた手順書です。

## 前提条件

- Git
- Python(`.venv`で使う仮想環境用。3.12系を推奨)
- Docker Desktop
- GitHubアカウント
- Vercelアカウント
- Supabaseアカウント

## 1. リポジトリのクローン

```bash
git clone <このリポジトリのURL>
cd employee-id-system
```

## 2. ローカル開発環境のセットアップ

### 2-1. Python仮想環境の作成

```bash
python -m venv .venv
```

有効化(Windows):
```bash
.venv\Scripts\activate
```
有効化(Mac/Linux):
```bash
source .venv/bin/activate
```

依存パッケージのインストール:
```bash
pip install -r requirements.txt
```

### 2-2. 環境変数ファイルの作成

```bash
cp .env.example .env
```
デフォルト値のままでローカルDocker Postgresに接続できるようになっています。

### 2-3. ローカルPostgres(Docker)の起動

[docker-compose-dev.yml](docker-compose-dev.yml) はPostgresコンテナのみを起動します(アプリ本体は`.venv`側でこの後直接起動します)。

```bash
docker compose -f docker-compose-dev.yml up -d
```

### 2-4. マスターデータの投入

[app/seed.py](app/seed.py) が会社(`JP001`, `US001`)と組織のサンプルデータを投入します。

```bash
python -m app.seed
```

### 2-5. アプリの起動

```bash
uvicorn app.main:app --reload
```

`http://127.0.0.1:8000/docs` を開き、Swagger UIが表示されれば成功です。

## 3. Supabaseプロジェクトの作成(本番用)

1. [supabase.com](https://supabase.com) にGitHubアカウントでログイン
2. Organizationを作成(個人利用ならニックネーム等でよい)
3. 「New Project」でプロジェクトを作成
   - Region: 日本からの利用なら **Northeast Asia (Tokyo)** を推奨
   - Database password: 「Generate a password」で生成し、必ず控えておく
   - Security設定: このアプリはSupabaseの自動生成REST APIを使わず直接Postgresに接続するため、「Enable Data API」「Automatically expose new tables」「Enable automatic RLS」はいずれもチェックなしでよい

## 4. 本番用環境変数(`.env.production`)の作成

`.env.production`は`.gitignore`済みで、リポジトリにはコミットされません。[.env.production.example](.env.production.example) を参考に、リポジトリルートに`.env.production`を作成します。

1. Supabaseダッシュボード → プロジェクト → 右上「Connect」→「Direct」タブ →「**Transaction pooler**」(ポート**6543**。直接接続の5432番は使わない)の接続文字列をコピー
2. スキームを`postgresql://`から`postgresql+psycopg://`に変更し、`[YOUR-PASSWORD]`部分を実際のDBパスワードに置き換えて`DATABASE_URL`に設定
3. `AUTH_SECRET_KEY`は以下で生成した値を設定:
   ```bash
   openssl rand -hex 32
   ```
4. `CORS_ORIGINS`は本番フロントエンドのオリジン(未確定なら一旦`*`)
5. `IMPORT_STORAGE_DIR=/tmp/imports`

## 5. Supabaseへのスキーマ作成・マスターデータ投入

### 5-1. スキーマ作成(Alembicマイグレーション)

[alembic/versions/85bb9bf67302_initial_schema.py](alembic/versions/85bb9bf67302_initial_schema.py) に初期マイグレーションがあります。ローカルから、`.env.production`の`DATABASE_URL`を使って実行します。

```bash
DATABASE_URL="<.env.productionのDATABASE_URLの値>" python -m alembic upgrade head
```

### 5-2. マスターデータ投入

`app.seed`は`DATABASE_URL`環境変数を見て接続先を切り替えるので、同様に実行できます。

```bash
DATABASE_URL="<.env.productionのDATABASE_URLの値>" python -m app.seed
```

ネットワーク環境によって直接接続できない場合は、後述の「トラブルシューティング」を参照してください。

## 6. Vercelへのデプロイ

1. [vercel.com](https://vercel.com) にGitHubアカウントでログイン
2. ダッシュボードで「**Add New...**」→「**Project**」
3. 「Import Git Repository」の一覧からこのリポジトリを探し、「**Import**」をクリック(既存リポジトリをそのままリンクする。Deploy/Cloneのような新規リポジトリ作成フローは選ばないこと)
4. 「Environment Variables」を開き、`.env.production`の4項目を1つずつ入力:
   - `DATABASE_URL`
   - `AUTH_SECRET_KEY`
   - `CORS_ORIGINS`
   - `IMPORT_STORAGE_DIR`
5. 「**Deploy**」をクリック

## 7. 動作確認

1. デプロイ完了後、発行されたURL(例: `https://<project>.vercel.app`)の `/health` にアクセス → `{"status":"ok"}` が返ればアプリは正常起動
2. `/docs` にアクセス → Swagger UIが表示されればルーティングも正常
3. Supabase接続の確認:
   - `POST /api/v1/auth/dev-token` を実行(Request body例):
     ```json
     {"sub":"tester","display_name":"Test User","roles":["CENTRAL_ADMIN"],"companies":["*"]}
     ```
   - レスポンスの`access_token`をコピー
   - `GET /api/v1/companies` の「Parameters」にある`authorization`欄に `Bearer <access_token>` を入力して実行
   - `JP001`, `US001` が返ってくればSupabaseへの本番接続も含めて全て正常です

## トラブルシューティング

### ローカルPCからSupabaseに直接接続できない(DNSタイムアウト等)

社内ネットワーク等でDNS解決や特定ポートへの外部通信が制限されている場合、`alembic upgrade head`や`psql`での直接接続が失敗することがあります。この場合はSupabaseの「SQL Editor」(ブラウザ経由なので制限を受けにくい)を使います。

1. オフラインモードでマイグレーションSQLを生成(DB接続不要):
   ```bash
   python -m alembic upgrade head --sql > migration.sql
   ```
2. 生成された`migration.sql`の内容をSupabaseダッシュボードの「SQL Editor」に貼り付けて実行
3. マスターデータも同様に、必要なINSERT文を手動で作成してSQL Editorで実行する

### `git push`で権限エラー(403)になる

複数のGitHubリモートが設定されている場合、意図しないリモートにpushしようとしていることがあります。以下で設定を確認してください。

```bash
git remote -v
```

Vercelと連携しているリポジトリのURLに対応するリモート名を指定してpushしてください(例: `git push origin main`)。
