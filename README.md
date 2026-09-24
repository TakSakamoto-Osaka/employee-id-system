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

PowerShell:
```powershell
$env:DATABASE_URL="<.env.productionのDATABASE_URLの値>"; python -m alembic upgrade head
```

bash(Git Bash等):
```bash
DATABASE_URL="<.env.productionのDATABASE_URLの値>" python -m alembic upgrade head
```

### 5-2. マスターデータ投入

`app.seed`は`DATABASE_URL`環境変数を見て接続先を切り替えるので、同様に実行できます。

PowerShell:
```powershell
$env:DATABASE_URL="<.env.productionのDATABASE_URLの値>"; python -m app.seed
```

bash(Git Bash等):
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
3. マスターデータ投入用のSQLも同様にSQL Editorで実行する

以下は、現時点のスキーマ(初期マイグレーション`85bb9bf67302`)にそのまま対応する、コピーしてすぐ使えるSQLです。モデルを変更した場合は上記1の手順で最新のSQLを生成し直してください。

#### テーブル作成SQL

```sql
CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

CREATE TABLE audit_logs (
    id VARCHAR(36) NOT NULL, actor VARCHAR(100) NOT NULL, action VARCHAR(100) NOT NULL,
    target_type VARCHAR(50) NOT NULL, target_id VARCHAR(100), details JSON NOT NULL,
    request_id VARCHAR(100), created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, PRIMARY KEY (id)
);

CREATE TABLE companies (
    id VARCHAR(36) NOT NULL, code VARCHAR(50) NOT NULL, name VARCHAR(200) NOT NULL,
    active BOOLEAN NOT NULL, PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_companies_code ON companies (code);

CREATE TABLE counters (
    name VARCHAR(50) NOT NULL, value BIGINT NOT NULL, PRIMARY KEY (name)
);

CREATE TABLE employee_batches (
    id VARCHAR(36) NOT NULL, caller_id VARCHAR(100) NOT NULL, status VARCHAR(20) NOT NULL,
    total_count INTEGER NOT NULL, created_count INTEGER NOT NULL, existing_count INTEGER NOT NULL,
    review_required_count INTEGER NOT NULL, error_count INTEGER NOT NULL, cancelled_count INTEGER NOT NULL,
    cancel_requested BOOLEAN NOT NULL, created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    started_at TIMESTAMP WITHOUT TIME ZONE, finished_at TIMESTAMP WITHOUT TIME ZONE, PRIMARY KEY (id)
);

CREATE TABLE employees (
    id VARCHAR(36) NOT NULL, unified_employee_number VARCHAR(9) NOT NULL,
    english_name_original VARCHAR(200) NOT NULL, english_name_normalized VARCHAR(200) NOT NULL,
    normalization_version INTEGER NOT NULL, date_of_birth DATE NOT NULL, status VARCHAR(20) NOT NULL,
    version INTEGER NOT NULL, created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, created_by VARCHAR(100), updated_by VARCHAR(100),
    PRIMARY KEY (id)
);
CREATE INDEX ix_employees_name_dob ON employees (english_name_normalized, date_of_birth);
CREATE UNIQUE INDEX ix_employees_unified_employee_number ON employees (unified_employee_number);

CREATE TABLE idempotency_records (
    id VARCHAR(36) NOT NULL, caller_id VARCHAR(100) NOT NULL, idempotency_key VARCHAR(200) NOT NULL,
    request_hash VARCHAR(64) NOT NULL, endpoint VARCHAR(100) NOT NULL, status_code INTEGER NOT NULL,
    response_body JSON NOT NULL, created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, PRIMARY KEY (id),
    CONSTRAINT uq_idem_caller_key UNIQUE (caller_id, idempotency_key)
);

CREATE TABLE import_jobs (
    id VARCHAR(36) NOT NULL, file_reference VARCHAR(500) NOT NULL, original_filename VARCHAR(255) NOT NULL,
    executed_by VARCHAR(100) NOT NULL, company_scope VARCHAR(50), status VARCHAR(20) NOT NULL,
    total_count INTEGER NOT NULL, created_count INTEGER NOT NULL, existing_count INTEGER NOT NULL,
    review_count INTEGER NOT NULL, error_count INTEGER NOT NULL, cancelled_count INTEGER NOT NULL,
    cancel_requested BOOLEAN NOT NULL, preview_new_count INTEGER NOT NULL, preview_existing_count INTEGER NOT NULL,
    preview_review_count INTEGER NOT NULL, created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    started_at TIMESTAMP WITHOUT TIME ZONE, finished_at TIMESTAMP WITHOUT TIME ZONE, PRIMARY KEY (id)
);

CREATE TABLE match_locks (
    key VARCHAR(64) NOT NULL, PRIMARY KEY (key)
);

CREATE TABLE employee_number_aliases (
    id VARCHAR(36) NOT NULL, alias_number VARCHAR(9) NOT NULL, target_employee_id VARCHAR(36) NOT NULL,
    reason TEXT NOT NULL, performed_by VARCHAR(100) NOT NULL, performed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id), FOREIGN KEY(target_employee_id) REFERENCES employees (id), UNIQUE (alias_number)
);

CREATE TABLE identity_reviews (
    id VARCHAR(36) NOT NULL, input_data JSON NOT NULL, candidate_employee_id VARCHAR(36),
    company_id VARCHAR(36), reason VARCHAR(50) NOT NULL, status VARCHAR(20) NOT NULL,
    resolution_employee_id VARCHAR(36), resolved_by VARCHAR(100), resolved_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, PRIMARY KEY (id),
    FOREIGN KEY(candidate_employee_id) REFERENCES employees (id),
    FOREIGN KEY(company_id) REFERENCES companies (id),
    FOREIGN KEY(resolution_employee_id) REFERENCES employees (id)
);

CREATE TABLE organizations (
    id VARCHAR(36) NOT NULL, company_id VARCHAR(36) NOT NULL, code VARCHAR(50) NOT NULL,
    name VARCHAR(200) NOT NULL, parent_organization_id VARCHAR(36), active BOOLEAN NOT NULL,
    PRIMARY KEY (id), FOREIGN KEY(company_id) REFERENCES companies (id),
    FOREIGN KEY(parent_organization_id) REFERENCES organizations (id),
    CONSTRAINT uq_org_company_code UNIQUE (company_id, code)
);

CREATE TABLE employee_affiliations (
    id VARCHAR(36) NOT NULL, employee_id VARCHAR(36) NOT NULL, company_id VARCHAR(36) NOT NULL,
    organization_id VARCHAR(36), existing_employee_number VARCHAR(100), job_title VARCHAR(200),
    remarks TEXT, effective_start_date DATE, effective_end_date DATE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    PRIMARY KEY (id), FOREIGN KEY(company_id) REFERENCES companies (id),
    FOREIGN KEY(employee_id) REFERENCES employees (id),
    FOREIGN KEY(organization_id) REFERENCES organizations (id)
);
CREATE UNIQUE INDEX uq_affiliation_company_existing_number ON employee_affiliations (company_id, existing_employee_number) WHERE existing_employee_number IS NOT NULL;

CREATE TABLE employee_batch_records (
    id VARCHAR(36) NOT NULL, batch_id VARCHAR(36) NOT NULL, record_index INTEGER NOT NULL,
    client_record_id VARCHAR(100) NOT NULL, input_data JSON NOT NULL, status VARCHAR(20) NOT NULL,
    employee_id VARCHAR(36), unified_employee_number VARCHAR(9), review_id VARCHAR(36),
    error_code VARCHAR(50), error_message VARCHAR(500), processed_at TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id), FOREIGN KEY(batch_id) REFERENCES employee_batches (id),
    FOREIGN KEY(employee_id) REFERENCES employees (id),
    FOREIGN KEY(review_id) REFERENCES identity_reviews (id),
    CONSTRAINT uq_batch_client_record_id UNIQUE (batch_id, client_record_id),
    CONSTRAINT uq_batch_record_index UNIQUE (batch_id, record_index)
);

CREATE TABLE import_rows (
    id VARCHAR(36) NOT NULL, job_id VARCHAR(36) NOT NULL, row_number INTEGER NOT NULL,
    input_data JSON NOT NULL, status VARCHAR(20) NOT NULL, employee_id VARCHAR(36),
    unified_employee_number VARCHAR(9), review_id VARCHAR(36), error_code VARCHAR(50),
    error_message VARCHAR(500), processed_at TIMESTAMP WITHOUT TIME ZONE, PRIMARY KEY (id),
    FOREIGN KEY(employee_id) REFERENCES employees (id), FOREIGN KEY(job_id) REFERENCES import_jobs (id),
    FOREIGN KEY(review_id) REFERENCES identity_reviews (id),
    CONSTRAINT uq_import_job_row UNIQUE (job_id, row_number)
);

INSERT INTO alembic_version (version_num) VALUES ('85bb9bf67302');
```

#### マスターデータ投入SQL

```sql
INSERT INTO companies (id, code, name, active) VALUES
  ('e513d4a8-e668-4f14-b050-f579f0b7d164', 'JP001', 'Example Japan K.K.', true),
  ('69894f48-eefc-452c-8f69-8d41beb03f08', 'US001', 'Example US Inc.', true);

INSERT INTO organizations (id, company_id, code, name, active) VALUES
  ('5cb3b5d7-9ca0-4938-a341-e3b829ede544', 'e513d4a8-e668-4f14-b050-f579f0b7d164', 'SALES01', 'Sales Division', true),
  ('9b2ba67f-7ae4-4982-ab23-e53cfa200d9c', 'e513d4a8-e668-4f14-b050-f579f0b7d164', 'HR01', 'Human Resources', true),
  ('786ddd8e-b2ae-435b-8f3e-48e0d856616d', '69894f48-eefc-452c-8f69-8d41beb03f08', 'HR01', 'Human Resources', true),
  ('a9a5d9f0-8caf-4883-b5e3-801025862c58', '69894f48-eefc-452c-8f69-8d41beb03f08', 'ENG01', 'Engineering', true);
```

### `git push`で権限エラー(403)になる

複数のGitHubリモートが設定されている場合、意図しないリモートにpushしようとしていることがあります。以下で設定を確認してください。

```bash
git remote -v
```

Vercelと連携しているリポジトリのURLに対応するリモート名を指定してpushしてください(例: `git push origin main`)。
