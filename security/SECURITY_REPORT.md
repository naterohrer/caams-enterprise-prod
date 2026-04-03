# CAAMS Enterprise — Comprehensive Security Analysis Report

**Date:** 2026-03-06
**Application:** CAAMS Enterprise v1.1.0
**Scope:** Full source code, dependencies, infrastructure configuration
**Branch:** `claude/unified-audit-platform-CwYxR`

---

## Executive Summary

CAAMS Enterprise is a FastAPI-based compliance audit management platform. The codebase demonstrates strong security awareness in several areas: PBKDF2-SHA256 password hashing at 600,000 iterations, a custom JWT implementation that explicitly prevents algorithm-confusion attacks, token versioning for instant session revocation, file upload magic-byte validation, and a structured immutable audit log. No hardcoded production secrets, backdoors, or intentionally malicious code patterns were identified.

However, several medium-to-high risk issues require remediation before production hardening is complete, the most critical being: **JWT tokens stored in localStorage** (XSS extractable), **rate limiting bypass behind reverse proxies**, and **plaintext HTTP exposure without TLS**.

---

## Findings Summary by Category

### 1. Dependency Vulnerabilities (SCA)

| ID | Package | CVE | CVSS | Status |
|----|---------|-----|------|--------|
| VULN-001 | starlette (transitive) | CVE-2024-47874 | 7.5 | ✅ PATCHED (v0.45.3) |
| VULN-002 | python-multipart | CVE-2024-53981 | 7.5 | ✅ PATCHED (v0.0.22) |
| VULN-003 | reportlab | CVE-2023-33733 | 9.8 | ✅ PATCHED (v4.4.10) |
| VULN-004 | mako (transitive) | CVE-2024-36844 | 5.4 | ⚠️ RISK ACCEPTED (alembic use only) |
| VULN-005 | h11 (transitive) | CVE-2025-43859 | 6.5 | ✅ PATCHED — h11>=0.16.0 pinned in requirements.txt |

**Key Observation:** All direct dependency CVEs are patched in installed versions. The outstanding issue is `h11` (HTTP/1.1 library used by uvicorn) which may be vulnerable to HTTP request smuggling. Upgrade uvicorn to obtain h11 ≥ 0.16.0.

**Supply Chain Gap:** No lock file exists. Add `pip-compile` or `uv lock` to CI to prevent silent transitive upgrades.

### 2. Static Code Analysis (SAST)

| ID | Severity | CWE | Title |
|----|----------|-----|-------|
| CF-001 | HIGH | CWE-307 | ~~Rate limiter bypassed behind reverse proxy~~ ✅ REMEDIATED |
| CF-002 | HIGH | CWE-922 | JWT tokens stored in localStorage (OIDC flow) |
| CF-003 | HIGH | CWE-916 | ~~API tokens hashed with unsalted SHA-256~~ ✅ REMEDIATED |
| CF-004 | MEDIUM | CWE-200 | Unauthenticated version disclosure via /health |
| CF-005 | MEDIUM | CWE-284 | SMTP password stored in plaintext in DB |
| CF-006 | MEDIUM | CWE-345 | OIDC state uses truncated 24-char HMAC |
| CF-007 | MEDIUM | CWE-601 | OIDC redirect to unvalidated IdP endpoint |
| CF-008 | MEDIUM | CWE-330 | TOTP lacks replay attack prevention |
| CF-009 | LOW | CWE-434 | File upload: shallow MIME validation for ZIP/Office |
| CF-010 | LOW | CWE-779 | X-Forwarded-For header logged unsanitized |
| CF-011 | LOW | CWE-598 | Auditor share token in URL query string |
| CF-012 | MEDIUM | CWE-749 | XLSX importer lacks defensive parsing limits |
| CF-013 | LOW | CWE-732 | Log directory created with default permissions |
| CF-014 | MEDIUM | CWE-287 | API token type detection uses fragile dot-heuristic |
| CF-015 | MEDIUM | CWE-269 | Assessment lifecycle accessible to any contributor |

### 3. Infrastructure as Code (IaC)

| ID | Severity | File | Title |
|----|----------|------|-------|
| IAC-001 | HIGH | docker-compose.yml | Port 8000 exposed without TLS |
| IAC-002 | HIGH | download-vendor.sh | ~~Vendored JS downloaded without SRI hash verification~~ ✅ REMEDIATED |
| IAC-003 | HIGH | docker-compose.yml | ~~Backup service runs as root~~ ✅ REMEDIATED |
| IAC-004 | MEDIUM | docker-compose.yml | ~~No resource limits on containers~~ ✅ REMEDIATED |
| IAC-005 | MEDIUM | docker-compose.yml | ~~No network segmentation between services~~ ✅ REMEDIATED |
| IAC-006 | MEDIUM | Dockerfile | ~~Base image not pinned to digest~~ ✅ REMEDIATED |
| IAC-007 | MEDIUM | docker-compose.yml | CORS default silently broken |
| IAC-008 | MEDIUM | Dockerfile | Container filesystem not read-only |
| IAC-009 | MEDIUM | ci.yml | Hardcoded test secret key in CI YAML |
| IAC-010 | LOW | docker-compose.yml | HSTS disabled by default |
| IAC-011 | LOW | docker-compose.yml | API docs unauthenticated when enabled |
| IAC-012 | LOW | docker-compose.yml | Backups unencrypted |
| IAC-013 | LOW | Dockerfile | curl installed and purged in builder stage |
| IAC-014 | LOW | alembic.ini | Alembic may log DB URL with credentials |

---

## Positive Security Controls Observed

The following security controls were implemented correctly and should be preserved:

| Control | Location | Notes |
|---------|----------|-------|
| PBKDF2-SHA256 at 600,000 iterations | `app/auth.py:24` | Meets OWASP 2023 recommendation |
| Algorithm-confusion attack prevention | `app/jwt_utils.py:47` | Explicitly rejects non-HS256 algorithms including "none" |
| Token version revocation | `app/auth.py:162` | Allows instant invalidation of all user sessions |
| Timing-safe password comparison | `app/auth.py:43` | Uses `hmac.compare_digest` throughout |
| MIME type allowlist + magic byte checks | `app/routers/evidence.py:52-73` | Rejects executable magic bytes |
| Path traversal guard on downloads | `app/routers/evidence.py:194-196` | Resolves path and checks prefix |
| Path traversal guard on backups | `app/routers/admin.py:176-180` | Same pattern for backup downloads |
| Non-root container user | `Dockerfile:26,49` | Dedicated `caams` user with no login shell |
| LIKE injection prevention | `app/routers/audit_log.py:70-75` | Escapes `%` and `_` in filter values |
| Rate limiting on sensitive endpoints | Multiple routers | Login, invite, MFA endpoints all rate-limited |
| Security response headers | `app/main.py:125-135` | X-Frame-Options, X-Content-Type-Options, etc. |
| Content-Length guard | `app/main.py:149-161` | Rejects oversized requests before body is read |
| Single-use invite tokens | `app/routers/auth.py:252` | Tokens invalidated after first use |
| Invite account inactive until accepted | `app/models.py:182` | `is_active=False` until password is set |
| No self-deactivation/deletion | `app/routers/auth.py:290-327` | Admins cannot lock themselves out |
| Structured JSON audit log | `app/logging_config.py` | Machine-parseable SIEM-ready format |

---

## Backdoor / Insider Threat Review

No backdoors, hidden authentication bypasses, or malicious code patterns were identified. Specifically:

- **No hardcoded credentials** in application source code or configuration templates
- **No debug/hidden routes** — the `/auth/setup-needed` endpoint is correctly guarded (`count == 0` check) and is the only unprotected bootstrapping route
- **No time bombs or conditional logic** that activates under specific time/environment conditions
- **The `_INVITE_PENDING` sentinel** (`"invite-pending"`) is a legitimate design pattern for uninitialised accounts, not a bypass — login is explicitly rejected for accounts in this state
- **The `hashed_password = "oidc-only"` sentinel** for SSO-only accounts is similarly legitimate — no code path accepts this string as a valid password
- **No obfuscated code, encoded payloads, or unexplained external connections** beyond explicitly documented OIDC and SMTP integrations
- **CI pipeline** is straightforward: checkout → install → test → lint → pip-audit; no artifact upload or deployment steps that could exfiltrate secrets

---

## Prioritised Remediation Roadmap

### P1 — Immediate (Before Production Launch)

1. **[IAC-001]** Deploy a TLS-terminating reverse proxy (Caddy recommended for auto-TLS). Remove direct port 8000 exposure.
2. **[CF-002]** Replace localStorage token storage in the OIDC callback with HttpOnly Secure cookies.
3. ~~**[CF-001]** Configure uvicorn with `--proxy-headers` and update slowapi to use real client IP from X-Forwarded-For.~~ ✅ REMEDIATED — `app/limiter.py` now extracts the real IP from `X-Forwarded-For`; uvicorn must be started with `--proxy-headers --forwarded-allow-ips=<proxy_cidr>` to complete the fix at the deployment layer.
4. ~~**[VULN-005]** Upgrade uvicorn to obtain h11 ≥ 0.16.0 to address HTTP request smuggling risk.~~ ✅ REMEDIATED — `h11>=0.16.0` explicitly pinned in `requirements.txt`; uvicorn 0.41.0 already ships h11 0.16.0.
5. ~~**[IAC-002]** Pin vendored JS asset SHA-256 hashes and enforce verification in the Docker build.~~ ✅ REMEDIATED — `scripts/download-vendor.sh` now sources all assets via `npm pack` from the npm registry (eliminating CDN trust), pins `@tailwindcss/browser` to `4.0.15`, and verifies SHA-256 hashes for all three assets before writing to the vendor directory.

### P2 — Short Term (Within 2 Weeks)

6. **[CF-005]** Encrypt the SMTP password column at-rest using Fernet encryption keyed from CAAMS_SECRET_KEY.
7. **[CF-008]** Implement TOTP replay prevention using a short-lived used-code cache (Redis or DB).
8. ~~**[IAC-003]** Set `user: postgres` on the pg_backup service.~~ ✅ REMEDIATED — `user: postgres` added to `pg_backup` in `docker-compose.yml`.
9. ~~**[CF-003]** Replace unsalted SHA-256 for API token hashing with HMAC-SHA256 keyed from the application secret.~~ ✅ REMEDIATED — `hash_api_token` and `generate_api_token` in `app/auth.py` now use `hmac.new(SECRET_KEY, raw, sha256)`.
10. **[IAC-012]** Encrypt backup files with age/GPG before storing on the backup volume.

### P3 — Medium Term (Within 1 Month)

11. **[CF-006]** Replace timestamp-based OIDC state with a full-entropy `secrets.token_urlsafe(32)` value stored server-side.
12. ~~**[IAC-004/5]** Add resource limits and network segmentation to docker-compose.yml.~~ ✅ REMEDIATED — CPU/memory limits added to all three services; `backend` and `backup` named networks isolate traffic. Also ~~**[IAC-006]**~~ — Dockerfile base images pinned to digest `sha256:d6e4d224…`.
13. **[CF-004]** Remove version from unauthenticated /health endpoint.
14. **[CF-012]** Add defensive parsing limits to XLSX importers (max rows, read-only mode, ZIP entry validation).
15. **[IAC-009]** Move CI test secret to GitHub Actions Secrets.

---

## Output Files

| File | Format | Contents |
|------|--------|---------|
| `security/sbom.cyclonedx.json` | CycloneDX 1.5 JSON | 31 components (direct + transitive) with PURL and license metadata |
| `security/vulnerabilities.json` | Custom JSON | 5 CVE findings with CVSS scores and patch status |
| `security/code_findings.csv` | CSV | 15 SAST findings with CWE IDs, file/line, and remediation |
| `security/iac_findings.json` | Custom JSON | 14 IaC findings mapped to CIS/NIST/PCI controls |
| `security/SECURITY_REPORT.md` | Markdown | This report |
