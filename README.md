# CAAMS Enterprise — Unified Audit Platform

A self-hosted, multi-user GRC platform. Select a security framework, map your tool stack, and run an auditor-ready compliance assessment — with full lifecycle management, evidence collection, findings tracking, RFIs, audit log, and multi-format exports.

> **Version 1.1.0** · Python 3.11+ · FastAPI · PostgreSQL · Docker Compose

---

## Contents

- [Features](#features)
- [Quick Start — Docker Compose](#quick-start--docker-compose-recommended)
- [Quick Start — Local / Bare-metal](#quick-start--local--bare-metal)
- [Upgrading](#upgrading)
- [First Login](#first-login)
- [User Management & Invites](#user-management--invites)
- [Usage Guide](#usage-guide)
- [Authentication & Roles](#authentication--roles)
- [Environment Variables](#environment-variables)
- [Exports](#exports)
- [API Reference](#api-reference)
- [Adding Frameworks](#adding-frameworks)
- [Adding Tools](#adding-tools)
- [Production Checklist](#production-checklist)
- [Data Storage & Migrations](#data-storage--migrations)
- [Logging](#logging)
- [Project Structure](#project-structure)
- [Supported Frameworks](#supported-frameworks)
- [Support](#support)
- [Legal](#legal)
- [Roadmap](#roadmap)

---

## Features

| Feature | Details |
|---|---|
| **Framework coverage mapping** | Map your tool stack against CIS Controls v8, NIST CSF v2, SOC 2 (2017), PCI DSS v4.0, and HIPAA Security Rule |
| **Assessment lifecycle** | Draft → In Review → Approved → Archived, with signed-off stage transitions and full history |
| **Evidence management** | Upload files per-control; approve, reject (with reason), and download evidence packages as ZIP |
| **Findings tracker** | Log findings with severity (critical/high/medium/low/informational), remediation owner, and target date |
| **RFIs** | Create Requests for Information with priority levels, assignments, and structured response threads |
| **Compensating control overrides** | Manually set a control's status with a justification and optional expiry date |
| **Ownership tracking** | Assign owner, team, and evidence owner per control |
| **Control review workflow** | Mark controls as not_reviewed / in_review / approved / rejected |
| **Statement of Applicability (SOA)** | Mark controls as not applicable with exclusion reasons; included in all exports |
| **Executive dashboard** | Org-wide compliance posture across all frameworks — scores, open findings, overdue controls, pipeline |
| **Framework crosswalk** | Tag-based automatic overlap mapping between any two loaded frameworks |
| **Multi-framework coverage** | Show which other frameworks are already satisfied by an assessment's tools |
| **Assessment clone** | Duplicate any assessment including tools, ownership, and notes |
| **Tool recommendations** | Ranked list of tools that would close the most coverage gaps |
| **XLSX export** | Summary, Coverage Report, Evidence Checklist, SOA, Findings, and Recommendations sheets |
| **PDF export** | Branded cover page, executive summary, tools table, and per-control coverage table |
| **Evidence ZIP package** | PDF report + all evidence files + manifest CSV in a single download |
| **API tokens** | Generate long-lived API tokens with optional expiry for CI/CD or external integrations |
| **Auditor shares** | Create scoped, time-limited share links for external auditors (no login required) |
| **User invite flow** | Admins invite new users by email — new users set their own password via a secure link |
| **Immutable audit log** | Every state-changing action is recorded with user, timestamp, IP, and detail payload |
| **Role-based access** | Admin / Contributor / Viewer roles enforced on every endpoint |
| **Rate limiting** | Per-IP rate limits on login, uploads, and exports |
| **REST API** | Full FastAPI backend with optional Swagger docs at `/docs` |

---

## Quick Start — Docker Compose (recommended)

**Prerequisites:** Docker 24+ with Compose v2 (`docker compose version`).

### One-command setup

```bash
bash setup.sh
```

`setup.sh` handles everything automatically:

1. Verifies Docker is installed and the current user can reach the daemon (explains the fix if not)
2. Generates a `.env` file with secure random secrets — no manual key generation needed
3. Builds images and starts the stack
4. Applies the database schema
5. Seeds frameworks and the tool catalog
6. Prints the app URL when ready

**First visit?** Navigate to **http://localhost:8000** — you'll be prompted to create the initial admin account.

> **Note:** `setup.sh` is idempotent — safe to re-run after upgrades or if the first run is interrupted. It will not overwrite an existing `.env`.

---

### Manual steps (if you prefer)

<details>
<summary>Expand for step-by-step instructions</summary>

#### 1. Create your environment file

```bash
# .env
CAAMS_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
DB_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
```

#### 2. Start the stack

```bash
docker compose up -d
```

This starts three containers: `postgres` (database), `caams` (application on port 8000), and `pg_backup` (daily `pg_dump` sidecar that retains the last 7 compressed backups). Postgres health-checks gate the app container so there's no race condition.

#### 3. Apply the database schema

```bash
docker compose exec caams alembic upgrade head
```

#### 4. Seed frameworks and tool catalog

```bash
docker compose exec caams python seed.py
```

Safe to re-run at any time — skips data that already exists.

#### 5. Open the app

Navigate to **http://localhost:8000** (or your server's IP/hostname). On first visit you'll be prompted to create the initial admin account.

</details>

---

## Quick Start — Local / Bare-metal

Use this path for local development or systemd-managed installs without Docker.

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set the secret key

```bash
export CAAMS_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
```

Add this to your shell profile or a `.env` file for persistent dev setups.

### 3. Seed the database

```bash
python seed.py
```

For local dev the app uses SQLite automatically — no database server required. For production, set `DATABASE_URL` to a PostgreSQL connection string and run `alembic upgrade head` first.

### 4. Start the server

**With HTTPS** (recommended, requires certs):

```bash
mkdir -p certs
openssl req -x509 -newkey rsa:4096 \
  -keyout certs/key.pem -out certs/cert.pem \
  -sha256 -days 3650 -nodes \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

bash start.sh
```

Open **https://localhost:8443** and accept the self-signed cert warning.

**Plain HTTP** (dev only, no certs needed):

```bash
uvicorn app.main:app --reload --port 8000
```

Then open **http://localhost:8000**.

**Systemd (production bare-metal):**

```bash
sudo bash install_service.sh
```

The installer creates a `caams` system user, installs a virtualenv, generates a secret key, and registers a systemd service. See the script header for full details.

---

## Upgrading

Both install methods are idempotent — the same command used for the initial install handles upgrades safely.

### Docker Compose

```bash
git pull
bash setup.sh
```

`setup.sh` will:
1. Rebuild the image with the new code
2. Restart the containers (`docker compose up -d --build`)
3. Run `alembic upgrade head` to apply any new schema migrations
4. Re-run `seed.py` to add any new frameworks or tools (existing data is never overwritten)

Your `.env` file, uploaded evidence (`caams_uploads` volume), and database (`caams_db` volume) are all preserved.

> **Tip:** Pull latest before running setup.sh so the build always uses current code: `git pull && bash setup.sh`

### Bare-metal / systemd

```bash
git pull
sudo bash install_service.sh
```

`install_service.sh` will:
1. Sync the updated code to `/opt/caams`
2. Re-install any new Python dependencies into the existing virtualenv
3. Leave `/etc/caams.env` and your TLS certificates untouched
4. Restart the `caams` systemd service automatically

Then apply migrations manually (the installer does not run Alembic):

```bash
cd /opt/caams
sudo -u caams venv/bin/alembic upgrade head
sudo systemctl restart caams
```

Re-seeding is optional but safe if new frameworks or tools were added:

```bash
sudo -u caams /opt/caams/venv/bin/python seed.py
```

---

## First Login

On first visit the app shows a setup screen. Create the initial admin account there, or via the API:

```bash
curl -X POST http://localhost:8000/auth/setup \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "YourStrongPassword!"}'
```

The setup endpoint is disabled automatically once any user exists.

---

## User Management & Invites

### Creating users via the web UI

Go to **Admin → Users → Add User**, enter a username, password, role, and optionally a full name and email. The user can log in immediately with those credentials.

### Creating users via the API

```bash
curl -X POST http://localhost:8000/auth/users \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"username": "viewer1", "password": "TempPass123!", "role": "viewer"}'
```

### Invite flow

The invite flow lets admins create accounts without setting a password. The invited user receives a token and sets their own password:

```bash
# 1. Admin creates the invite
curl -X POST http://localhost:8000/auth/users/invite \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"username": "jsmith", "role": "contributor", "full_name": "Jane Smith", "email": "jsmith@company.com"}'

# Response includes invite_token, invite_url (if CAAMS_APP_BASE_URL is set), and email_sent
```

If SMTP is configured (see [Environment Variables](#environment-variables)), the invite email is sent automatically. Otherwise, share the `invite_token` manually — the new user POSTs it to `/auth/invite/accept`:

```bash
# 2. New user accepts and sets their password
curl -X POST http://localhost:8000/auth/invite/accept \
  -H "Content-Type: application/json" \
  -d '{"token": "<invite_token>", "password": "TheirOwnPassword!"}'

# Returns a JWT pair — user is immediately logged in
```

Invite tokens are valid for 72 hours (configurable via `CAAMS_INVITE_TOKEN_HOURS`) and are single-use.

---

## Usage Guide

### Creating an assessment

1. Click **Assessments → New Assessment**
2. Enter a name (e.g. `Q1 2026 SOC 2 Review`), pick a framework, add scope notes, and optionally set a recurrence schedule
3. Click **Submit** — the assessment opens in **Draft** status

From the assessment detail view, switch to the **Controls** tab and click **Edit** on any control to set notes, evidence links, ownership, and override status.

### Assessment lifecycle

| Action | Allowed by | Transition |
|---|---|---|
| Submit for Review | Contributor | Draft → In Review |
| Approve | Admin | In Review → Approved |
| Return to Draft | Admin / Contributor | In Review → Draft |
| Archive | Admin | Any → Archived |

Each transition creates a signed-off record visible on the **Audit Log** tab.

### Reading coverage results

- **Covered** — all required capability tags are satisfied by selected tools
- **Partial** — some required tags are present but not all
- **Not Covered** — no required tags are satisfied
- **N/A** — excluded from scope (with justification)

Coverage score = `(covered + 0.5 × partial) / applicable_total × 100`

### Evidence

Upload files on the **Evidence** tab. Files can be associated with a specific control, given a description and expiry date, and approved or rejected by contributors. Full evidence packages (PDF report + all files + manifest CSV) are downloadable as a ZIP.

### Findings

Log issues on the **Findings** tab. Each finding has severity (`critical` → `informational`), status (`open` → `in_progress` → `remediated` → `accepted` → `closed`), and a remediation owner + target date. Closing a finding automatically stamps the close date.

### RFIs

Create **Requests for Information** with priority levels and due dates. Assignees respond inline; the RFI auto-advances to `responded` on first reply. Admins close RFIs when resolved.

### External auditor access

Create a scoped share link under **Auditor Shares** — no login required, optionally limited to specific controls, with a configurable expiry date. External auditors can view coverage results, evidence metadata, open findings, and add comments through the share link.

### Dashboard

The **Dashboard** shows org-wide posture across all active assessments:
- Overall compliance score
- Per-framework scores (bar chart)
- Open findings by severity (doughnut chart)
- Overdue controls count
- Assessments due for renewal in the next 30 days
- Assessment pipeline (draft / in_review / approved count)

---

## Authentication & Roles

CAAMS Enterprise uses JWT-based authentication. All API endpoints (except `/health`, `/health/ready`, and `/auth/setup`) require a valid bearer token.

### Roles

| Role | Permissions |
|---|---|
| `admin` | Full access — manage users, approve lifecycle transitions, create API tokens |
| `contributor` | Create/edit assessments, update notes, ownership, evidence, findings, and RFIs |
| `viewer` | Read-only access to all assessments and results |

### Logging in

```bash
curl -X POST http://localhost:8000/auth/login \
  -d "username=admin&password=YourPassword"
# returns {"access_token": "...", "refresh_token": "...", "token_type": "bearer", "role": "admin"}
```

Pass the access token in the `Authorization` header for all subsequent requests:

```bash
curl http://localhost:8000/assessments \
  -H "Authorization: Bearer <access_token>"
```

**Token lifetimes:**
- Access token: **30 minutes** (configurable via `CAAMS_ACCESS_TOKEN_MINUTES`)
- Refresh token: **7 days** (configurable via `CAAMS_REFRESH_TOKEN_DAYS`)

Exchange a refresh token for a new access token:

```bash
curl -X POST http://localhost:8000/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "<refresh_token>"}'
```

Login is rate-limited to **10 attempts per minute** per IP.

### API Tokens (machine-to-machine)

For CI/CD pipelines and external integrations, create long-lived API tokens via **Admin → API Tokens** or:

```bash
curl -X POST http://localhost:8000/api-tokens \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "ci-pipeline"}'
```

The plaintext token is returned **once** at creation. Store it securely in your secrets manager.

---

## Environment Variables

### Required

| Variable | Description |
|---|---|
| `CAAMS_SECRET_KEY` | 32+ character random string used to sign JWTs. Generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`. The app refuses to start without it. |

### Database

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///caams.db` | SQLAlchemy connection string. Set to `postgresql://user:pass@host:5432/caams` for production. SQLite is used automatically for local dev. |

### Application

| Variable | Default | Description |
|---|---|---|
| `CAAMS_HOST` | `0.0.0.0` | Bind address |
| `CAAMS_PORT` | `8443` | Port (Docker Compose maps this to 8000 externally) |
| `CAAMS_ENABLE_DOCS` | `false` | Set to `true` to enable Swagger UI at `/docs` and `/redoc` |
| `CAAMS_CORS_ORIGIN` | _(none)_ | Your frontend origin (e.g. `https://caams.corp.local`). Required for browser-based API access. If unset, cross-origin requests are blocked. |
| `CAAMS_USE_HSTS` | `false` | Set to `true` to send `Strict-Transport-Security` headers (enable only when behind TLS) |
| `CAAMS_MAX_UPLOAD_MB` | `50` | Maximum evidence file size in MB |
| `CAAMS_LOG_LEVEL` | `INFO` | Log verbosity. `DEBUG` logs may expose sensitive detail — use only while debugging. |

### Tokens

| Variable | Default | Description |
|---|---|---|
| `CAAMS_ACCESS_TOKEN_MINUTES` | `30` | JWT access token lifetime in minutes |
| `CAAMS_REFRESH_TOKEN_DAYS` | `7` | JWT refresh token lifetime in days |

### User invites

| Variable | Default | Description |
|---|---|---|
| `CAAMS_INVITE_TOKEN_HOURS` | `72` | How long an invite link remains valid |
| `CAAMS_APP_BASE_URL` | _(none)_ | Frontend base URL used to construct invite links (e.g. `https://caams.corp.local`). If unset, the raw token is returned in the API response for manual sharing. |

### SMTP (optional — enables automatic invite emails)

SMTP can be configured in two ways — the database always takes precedence over environment variables:

- **Web UI (recommended):** Go to **Admin → System → Email** and fill in the form. Settings are saved to the database and take effect immediately with no restart.
- **Environment variables:** Set the variables below before starting the service. Use this for automated deployments or when you want config managed outside the app.

Leave `CAAMS_SMTP_HOST` unset (and no DB config saved) to disable email entirely. The invite flow works without it — the admin manually shares the token.

| Variable | Default | Description |
|---|---|---|
| `CAAMS_SMTP_HOST` | _(none)_ | SMTP server hostname. Omit to disable email. |
| `CAAMS_SMTP_PORT` | `587` | SMTP port |
| `CAAMS_SMTP_FROM` | _(none)_ | From address for outbound email (e.g. `caams@corp.local`) |
| `CAAMS_SMTP_USER` | _(none)_ | SMTP username. Leave blank for anonymous relay. |
| `CAAMS_SMTP_PASSWORD` | _(none)_ | SMTP password |
| `CAAMS_SMTP_USE_TLS` | `true` | `true` = STARTTLS (recommended), `false` = plain SMTP |

### OIDC / SSO (optional)

Leave `CAAMS_OIDC_ISSUER` unset to disable SSO. When configured, users can log in via your IdP and are auto-provisioned on first login.

| Variable | Default | Description |
|---|---|---|
| `CAAMS_OIDC_ISSUER` | _(none)_ | IdP issuer URL (e.g. `https://accounts.google.com`). Omit to disable SSO. |
| `CAAMS_OIDC_CLIENT_ID` | _(none)_ | OAuth2 client ID |
| `CAAMS_OIDC_CLIENT_SECRET` | _(none)_ | OAuth2 client secret |
| `CAAMS_OIDC_DEFAULT_ROLE` | `viewer` | Role assigned to auto-provisioned SSO users (`viewer`, `contributor`, or `admin`) |
| `CAAMS_APP_BASE_URL` | _(none)_ | Base URL used to construct the OIDC redirect URI (e.g. `https://caams.corp.local`). Required when SSO is enabled. |

---

## Exports

### XLSX (`GET /assessments/{id}/export`)

| Sheet | Contents |
|---|---|
| Summary | Assessment name, framework, status, and aggregate metrics |
| Coverage Report | All controls with status, override, owners, covered-by tools, missing tags, notes, evidence URL, finding counts |
| Evidence Checklist | One row per required evidence item, with owners and status |
| SOA | Statement of Applicability — applicable flag, exclusion reason, override, reviewer per control |
| Findings | All findings with severity (color-coded), status, remediation owner, and dates |
| Recommendations | Tools not in scope ranked by number of controls they would improve |

### SOA XLSX (`GET /assessments/{id}/export/soa`)

Standalone Statement of Applicability with a formatted title block.

### PDF (`GET /assessments/{id}/export/pdf`)

Cover page, executive summary, tools-in-scope table, and color-coded per-control coverage table, plus a findings table.

### Evidence ZIP (`GET /assessments/{id}/export/evidence-package`)

ZIP archive containing the PDF report, all evidence files grouped by control, and a manifest CSV.

---

## API Reference

Enable interactive Swagger UI by setting `CAAMS_ENABLE_DOCS=true` and visiting `/docs`.

### Auth & Users

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/auth/setup-needed` | None | Returns `{"needed": true}` if no admin exists yet |
| `POST` | `/auth/setup` | None | Create the first admin account (disabled after first use) |
| `POST` | `/auth/login` | None | Exchange credentials for a JWT pair (form-encoded, rate-limited) |
| `POST` | `/auth/refresh` | None | Exchange a refresh token for a new access token |
| `GET` | `/auth/me` | Any | Current user profile |
| `GET` | `/auth/users` | Admin | List all users |
| `GET` | `/auth/directory` | Any | Lightweight user list for owner dropdowns (id, username, full_name) |
| `GET` | `/auth/notifications/my` | Any | Items assigned to the current user (overdue RFIs, findings, controls) |
| `POST` | `/auth/users` | Admin | Create a user (admin sets password) |
| `POST` | `/auth/users/invite` | Admin | Invite a user — they set their own password via a secure link |
| `POST` | `/auth/invite/accept` | None | Accept an invite token and activate the account |
| `PATCH` | `/auth/users/{id}` | Admin | Update role, password, full name, email, or active flag |
| `DELETE` | `/auth/users/{id}` | Admin | Delete user |

### Frameworks & Tools

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/frameworks` | Viewer | List frameworks |
| `GET` | `/frameworks/{id}/controls` | Viewer | List controls for a framework |
| `GET` | `/tools` | Viewer | List tools |
| `POST` | `/tools` | Admin | Add a tool |
| `DELETE` | `/tools/{id}` | Admin | Remove a tool |
| `POST` | `/tools/upload` | Admin | Bulk-import tools from JSON _(API only — no web UI yet)_ |
| `GET` | `/tools/template/download` | Admin | Download JSON import template _(API only — no web UI yet)_ |

### Assessments

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/assessments` | Contributor | Create assessment |
| `GET` | `/assessments` | Viewer | List assessments |
| `GET` | `/assessments/history` | Viewer | List with pre-computed metrics |
| `GET` | `/assessments/{id}` | Viewer | Get metadata |
| `DELETE` | `/assessments/{id}` | Admin | Delete |
| `POST` | `/assessments/{id}/clone` | Contributor | Clone with tools, notes, and ownership |
| `POST` | `/assessments/{id}/lifecycle` | Contributor / Admin | Submit / approve / return / archive |
| `GET` | `/assessments/{id}/signoffs` | Viewer | Lifecycle sign-off history |
| `GET` | `/assessments/{id}/results` | Viewer | Full coverage results |
| `GET` | `/assessments/{id}/tools` | Viewer | Tools in scope |
| `PATCH` | `/assessments/{id}/tools` | Contributor | Update tool selection |
| `GET` | `/assessments/{id}/recommendations` | Viewer | Tool recommendations |
| `PATCH` | `/assessments/{id}/controls/{cid}/notes` | Contributor | Upsert notes, evidence URL, override |
| `PATCH` | `/assessments/{id}/controls/{cid}/review` | Contributor | Set review status |
| `PATCH` | `/assessments/{id}/controls/{cid}/ownership` | Contributor | Set owner / team / evidence owner |

### Evidence, Findings & RFIs

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/assessments/{id}/evidence` | Viewer | List evidence files (excludes expired) |
| `POST` | `/assessments/{id}/evidence` | Contributor | Upload a file (multipart) |
| `PATCH` | `/assessments/{id}/evidence/{fid}/approval` | Contributor | Approve or reject |
| `GET` | `/assessments/{id}/evidence/{fid}/download` | Viewer | Download file |
| `DELETE` | `/assessments/{id}/evidence/{fid}` | Contributor | Delete file |
| `GET` | `/assessments/{id}/findings` | Viewer | List findings |
| `POST` | `/assessments/{id}/findings` | Contributor | Create finding |
| `GET` | `/assessments/{id}/findings/{fid}` | Viewer | Get finding |
| `PATCH` | `/assessments/{id}/findings/{fid}` | Contributor | Update finding |
| `DELETE` | `/assessments/{id}/findings/{fid}` | Contributor | Delete finding |
| `GET` | `/assessments/{id}/risk-acceptances` | Viewer | List risk acceptances |
| `POST` | `/assessments/{id}/risk-acceptances` | Contributor | Create risk acceptance |
| `GET` | `/assessments/{id}/rfis` | Viewer | List RFIs |
| `POST` | `/assessments/{id}/rfis` | Contributor | Create RFI |
| `PATCH` | `/assessments/{id}/rfis/{rid}` | Contributor | Update RFI status |
| `POST` | `/assessments/{id}/rfis/{rid}/responses` | Contributor | Submit RFI response |

### Auditor Shares & Comments

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/assessments/{id}/auditor-shares` | Viewer | List share links |
| `POST` | `/assessments/{id}/auditor-shares` | Contributor | Create a share link |
| `DELETE` | `/assessments/{id}/auditor-shares/{sid}` | Contributor | Revoke a share link |
| `GET` | `/assessments/{id}/auditor-view?token=…` | Share token | Read-only view for external auditors _(API only — no web UI destination yet; the share token is returned when creating a share but the link itself has no SPA route)_ |
| `GET` | `/assessments/{id}/comments` | Viewer | List comments _(API only — no web UI yet)_ |
| `POST` | `/assessments/{id}/comments` | Any logged-in | Add a comment _(API only — no web UI yet)_ |
| `POST` | `/assessments/{id}/comments/external?token=…` | Share token | External auditor adds a comment _(API only — no web UI yet)_ |

### MFA

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/auth/mfa/setup` | Any | Generate a TOTP secret and QR code URI to enrol an authenticator app |
| `POST` | `/auth/mfa/confirm` | Any | Verify a TOTP code and enable MFA for the current user |
| `POST` | `/auth/mfa/disable` | Any | Disable MFA for the current user (requires current TOTP code) |
| `DELETE` | `/auth/mfa/admin/{user_id}` | Admin | Reset MFA for any user (admin recovery action) |
| `POST` | `/auth/mfa/verify-login` | None | Exchange a temporary MFA challenge token + TOTP code for a full JWT pair |

### SSO / OIDC

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/auth/oidc/status` | None | Returns whether SSO is configured; safe to call from the login page |
| `GET` | `/auth/oidc/authorize` | None | Redirects the browser to the IdP authorization endpoint (rate-limited: 20/hour) |
| `GET` | `/auth/oidc/callback` | None | Handles the IdP callback, provisions the user, and issues a CAAMS JWT pair (rate-limited: 20/hour) |

Configure SSO via the [OIDC environment variables](#oidc--sso-optional). Leave `CAAMS_OIDC_ISSUER` unset to disable.

### Admin

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/admin/smtp/status` | Admin | Returns effective SMTP configuration (password omitted) with source indicator (`db` or `env`) |
| `GET` | `/admin/smtp/config` | Admin | Same as status but includes `has_password` flag; used to pre-populate the settings form |
| `PUT` | `/admin/smtp/config` | Admin | Save SMTP settings to the database — takes effect immediately, no restart required |
| `DELETE` | `/admin/smtp/config` | Admin | Clear DB-stored SMTP settings, reverting to environment variables |
| `POST` | `/admin/smtp/test` | Admin | Send a test email to a specified address to verify SMTP connectivity |
| `GET` | `/admin/backup/list` | Admin | List available database backup files with timestamps and sizes |
| `GET` | `/admin/backup/download/{filename}` | Admin | Download a specific backup file (`.sql.gz`) |

### Exports, Dashboard & Misc

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/assessments/{id}/export` | Viewer | Download XLSX workbook |
| `GET` | `/assessments/{id}/export/soa` | Viewer | Download SOA XLSX _(API only — no web UI button yet)_ |
| `GET` | `/assessments/{id}/export/pdf` | Viewer | Download PDF report |
| `GET` | `/assessments/{id}/export/evidence-package` | Viewer | Download evidence ZIP _(API only — no web UI button yet)_ |
| `GET` | `/dashboard` | Viewer | Org-wide compliance dashboard |
| `GET` | `/crosswalk?source_framework_id=…&target_framework_id=…` | Viewer | Tag-based crosswalk between two frameworks |
| `GET` | `/crosswalk/multi-framework?assessment_id=…` | Viewer | Coverage of all other frameworks |
| `GET` | `/audit-log` | Admin | Global audit log (paginated) |
| `GET` | `/audit-log/assessment/{id}` | Viewer | Per-assessment audit log |
| `GET` | `/api-tokens` | Admin | List API tokens |
| `POST` | `/api-tokens` | Admin | Create API token |
| `DELETE` | `/api-tokens/{id}` | Admin | Revoke API token |
| `POST` | `/import/cis-xlsx` | Admin | Import CIS Controls from XLSX _(API only — no web UI yet)_ |
| `GET` | `/health` | None | Liveness check |
| `GET` | `/health/ready` | None | Readiness check (verifies DB connectivity) |

---

## Adding Frameworks

1. Create a JSON file in `app/data/`:

```json
{
  "name": "My Framework",
  "version": "v1.0",
  "description": "Optional description.",
  "controls": [
    {
      "control_id": "MF-1",
      "title": "Control Title",
      "description": "What this control requires.",
      "required_tags": ["tag-a", "tag-b"],
      "optional_tags": ["tag-c"],
      "evidence": [
        "Evidence item 1",
        "Evidence item 2"
      ]
    }
  ]
}
```

2. Add the filename to `FRAMEWORK_FILES` in `seed.py`
3. Re-run `python seed.py` — existing data is not affected

Tags must match capability tags in `app/data/tools_catalog.json`. To list all available tags:

```bash
python3 -c "
import json
data = json.load(open('app/data/tools_catalog.json'))
tags = sorted({t for tool in data for t in tool['capabilities']})
print('\n'.join(tags))
"
```

---

## Adding Tools

Edit `app/data/tools_catalog.json` and add an entry:

```json
{
  "name": "My Tool",
  "category": "EDR",
  "description": "Endpoint detection and response.",
  "capabilities": ["endpoint-protection", "malware-detection", "EDR"]
}
```

Re-run `python seed.py` to load it. Or use the **Tools → Add Tool** form in the UI, or `POST /tools/upload` with a JSON array.

---

## Production Checklist

Before going live, verify each item:

- [ ] `CAAMS_SECRET_KEY` is a 32+ character random value — never a default or a dictionary word
- [ ] `CAAMS_ENABLE_DOCS=false` (default) — keeps `/docs`, `/redoc`, and `/openapi.json` inaccessible
- [ ] `CAAMS_CORS_ORIGIN` is set to your frontend's exact origin
- [ ] `DATABASE_URL` points to PostgreSQL; `alembic upgrade head` has been run
- [ ] `CAAMS_USE_HSTS=true` if TLS terminates at this container
- [ ] Uploaded evidence (`uploads/`) and logs (`logs/`) are on a persistent volume
- [ ] The PostgreSQL `DB_PASSWORD` is strong and not reused elsewhere
- [ ] Log output is shipped to a SIEM or centralized log store (see [Logging](#logging) for ingestion options)
- [ ] `CAAMS_APP_BASE_URL` is set if OIDC SSO is enabled — required for the redirect URI to resolve correctly
- [ ] The `caams` service user has no shell and no home directory (handled by `install_service.sh`)

---

## Data Storage & Migrations

### Database

CAAMS Enterprise uses **PostgreSQL** in production (configured via `DATABASE_URL` in Docker Compose). For local development without Docker, the app automatically falls back to SQLite (`caams.db` in the project root) — no setup required.

### Migrations

Schema changes are managed by [Alembic](https://alembic.sqlalchemy.org/). Always run migrations before starting the app after an upgrade:

```bash
# Docker Compose
docker compose exec caams alembic upgrade head

# Bare-metal
alembic upgrade head
```

To check the current migration state:

```bash
docker compose exec caams alembic current
```

SQLite (local dev only) auto-creates the schema on first startup — no migration step needed.

### Uploaded evidence files

Evidence files are stored under `uploads/` (relative to the project root), grouped by UUID filename. The original filename and metadata are stored in the database. In Docker Compose, `uploads/` is a named volume (`caams_uploads`) — it persists across container restarts and upgrades.

### Resetting a local dev database

```bash
rm caams.db && python seed.py
```

---

## Logging

Two rotating log files are written to `logs/` (10 MB per file, 5 backups). All entries also stream to stdout / `journalctl -u caams`. Logs are emitted as **structured JSON** — one object per line — for drop-in compatibility with Splunk HEC, Elastic/Filebeat, Datadog, Fluentd, and other SIEM ingestion pipelines.

### `logs/access.log` — every HTTP request

```json
{"ts": "2026-02-21T12:34:56+00:00", "level": "INFO", "logger": "caams.access", "msg": "POST /auth/login 200"}
{"ts": "2026-02-21T12:34:57+00:00", "level": "INFO", "logger": "caams.access", "msg": "GET /assessments/5/results 200"}
```

### `logs/app.log` — application events

```json
{"ts": "2026-02-21T12:34:55+00:00", "level": "INFO",    "logger": "caams.app",  "msg": "STARTUP | CAAMS Enterprise v1.1.0 | database ready"}
{"ts": "2026-02-21T12:34:56+00:00", "level": "WARNING", "logger": "caams.auth", "msg": "LOGIN failed | username=badguy | ip=10.0.0.3"}
{"ts": "2026-02-21T12:34:57+00:00", "level": "INFO",    "logger": "caams.auth", "msg": "LOGIN success | user=admin | role=admin | ip=10.0.0.1"}
{"ts": "2026-02-21T12:35:10+00:00", "level": "INFO",    "logger": "caams.email","msg": "Invite email sent to jsmith@company.com"}
```

### SIEM integration

The structured log format is designed for zero-config ingestion:

- **Docker log driver:** `docker logs caams` streams JSON to stdout. Configure your log driver (`json-file`, `syslog`, `fluentd`) in `docker-compose.yml`.
- **Filebeat / Fluentd:** Point at `logs/app.log` and `logs/access.log` (mount the volume) — no parsing rules needed.
- **Splunk HEC:** Use the Splunk Universal Forwarder or Fluentd Splunk output plugin pointing at the mounted log directory.
- **Elastic:** Filebeat with the `log` input and `json.keys_under_root: true` parses these logs automatically.

In addition to application logs, the **audit log** (all user actions with user, IP, timestamp, and detail) is stored in the database and queryable via `GET /audit-log`. Your SIEM can poll this endpoint directly or via a cron-based export.

**Log level** is controlled by `CAAMS_LOG_LEVEL` (default `INFO`). Never set `DEBUG` in production — debug output may include sensitive request details.

---

## Project Structure

```
caams/
├── app/
│   ├── data/                       # Framework JSON files and tool catalog
│   │   ├── cis_v8.json
│   │   ├── nist_csf_v2.json
│   │   ├── soc2_2017.json
│   │   ├── pci_dss_v4.json
│   │   ├── hipaa_security.json
│   │   └── tools_catalog.json
│   ├── engine/
│   │   └── mapper.py               # Coverage computation engine
│   ├── importers/
│   │   └── cis_xlsx.py             # CIS Controls XLSX importer
│   ├── routers/
│   │   ├── api_tokens.py           # Long-lived API token management
│   │   ├── assessments.py          # Assessment CRUD, lifecycle, notes, clone
│   │   ├── audit_log.py            # Immutable audit log read endpoints + log_event()
│   │   ├── auditor_shares.py       # Scoped external auditor share links + comments
│   │   ├── auth.py                 # Login, setup, user management, invite flow
│   │   ├── crosswalk.py            # Framework crosswalk and multi-framework coverage
│   │   ├── dashboard.py            # Org-wide executive dashboard
│   │   ├── evidence.py             # Evidence file upload, approval, download
│   │   ├── export.py               # XLSX export (coverage, SOA, findings)
│   │   ├── findings.py             # Findings and risk acceptance tracker
│   │   ├── frameworks.py           # Framework and control list endpoints
│   │   ├── importers_router.py     # CIS Controls XLSX import endpoint
│   │   ├── pdf_export.py           # PDF report + evidence ZIP export
│   │   ├── rfi.py                  # Request for Information endpoints
│   │   └── tools.py                # Tool catalog endpoints
│   ├── auth.py                     # JWT, password hashing, role dependencies
│   ├── database.py                 # SQLAlchemy engine + session factory
│   ├── email.py                    # Optional SMTP connector for invite emails
│   ├── jwt_utils.py                # Pure-Python HS256 JWT (no C dependencies)
│   ├── limiter.py                  # Shared slowapi rate limiter
│   ├── logging_config.py           # Rotating file handler (access.log + app.log)
│   ├── main.py                     # FastAPI app, middleware, CORS, lifespan
│   ├── models.py                   # SQLAlchemy ORM models
│   └── schemas.py                  # Pydantic v2 request/response schemas
├── migrations/                     # Alembic migration scripts
│   └── versions/
├── static/
│   ├── index.html                  # Single-page app shell and all view templates
│   ├── privacy.html                # Privacy Policy
│   ├── terms.html                  # Terms of Service
│   ├── app.js                      # Alpine.js application — all state and API calls
│   └── app.css                     # Custom styles
├── tests/                          # pytest test suite (132 tests)
├── logs/                           # Runtime logs (git-ignored, created on first start)
├── uploads/                        # Evidence files (git-ignored, created on first start)
├── alembic.ini                     # Alembic configuration
├── caams.service                   # systemd unit file (bare-metal installs)
├── docker-compose.yml              # Docker Compose stack (app + postgres)
├── Dockerfile
├── install_service.sh              # Production bare-metal installer (systemd)
├── setup.sh                        # Docker Compose setup script (idempotent, non-root friendly)
├── seed.py                         # Database seeder (frameworks + tool catalog)
├── start.sh                        # HTTPS dev start script
└── requirements.txt
```

---

## Supported Frameworks

| Framework | Version | Controls |
|---|---|---|
| CIS Controls | v8 | 18 |
| NIST Cybersecurity Framework | v2.0 | 6 functions / 22 categories |
| SOC 2 Trust Services Criteria | 2017 | 9 |
| PCI DSS | v4.0 | 12 requirements |
| HIPAA Security Rule | 45 CFR Part 164 | 16 standards |

Additional frameworks can be added by dropping a JSON file into `app/data/` — see [Adding Frameworks](#adding-frameworks).

---

## Tech Stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2, Alembic
- **Database:** PostgreSQL 16 (production) · SQLite (local dev, zero-config)
- **Exports:** openpyxl (XLSX), ReportLab (PDF)
- **Frontend:** Alpine.js, Tailwind CSS (CDN), Chart.js — no build step required
- **Auth:** Pure-Python HS256 JWT, PBKDF2-HMAC-SHA256 password hashing (no compiled dependencies)
- **Email:** stdlib `smtplib` — optional SMTP connector, no extra packages required

---

## Support

Support is provided on a best-effort basis via the GitHub issue tracker:

**[github.com/naterohrer/caams-enterprise-prod/issues](https://github.com/naterohrer/caams-enterprise-prod/issues)**

When filing a bug, include: CAAMS version, deployment method (Docker Compose / bare-metal), OS, and relevant log lines from `logs/app.log` (redact any sensitive values).

Enterprise support arrangements (SLA, private advisory, onboarding) are available — open an issue to discuss.

---

## Legal

- **License:** CAAMS Enterprise is released under the [GNU Affero General Public License v3.0 (AGPL-3.0)](https://www.gnu.org/licenses/agpl-3.0.html). See the [`LICENSE`](LICENSE) file for the full license text.
- **[Privacy Policy](/privacy)** — what data the Software collects and how it is used
- **[Terms of Service](/terms)** — permitted use, disclaimer of warranties, limitation of liability

Both documents are served at `/privacy` and `/terms` within your deployment. The linked versions above apply to the Software as distributed; your organization is the data controller for all data processed in your instance.

---

## Roadmap

### Near-term

#### LDAP / Active Directory

On-premise shops that cannot expose an OIDC endpoint need LDAP bind authentication against an existing AD or OpenLDAP server.

**Planned env vars:** `CAAMS_LDAP_HOST`, `CAAMS_LDAP_PORT`, `CAAMS_LDAP_BASE_DN`, `CAAMS_LDAP_BIND_DN`, `CAAMS_LDAP_BIND_PASSWORD`, `CAAMS_LDAP_GROUP_MAP`

#### Webhook / notification scheduler

Automated alerts for time-sensitive events (RFI past due, finding target date passed, share link expiring, assessment approaching renewal). Planned as a background task with configurable SMTP and optional Slack/Teams webhook.

### Longer-term

- **SAML 2.0** — for legacy PingFederate / ADFS environments
- **Multi-tenancy** — partition data by organisation on a single instance
- **Advanced reporting** — trend charts, control coverage heatmap, findings aging report
