进入 ScholarOutboundManager Phase Web-0：secure web panel foundation.

当前项目背景：

ScholarOutboundManager 是 Google Scholar 专用出口节点管理器。它管理敏感数据：

- subscription URL
- proxy raw_uri
- UUID / public_key / password / auth
- candidates.json
- passed_candidates.json
- selected_candidate.json
- runtime Xray config
- sidecar systemd lifecycle

当前项目主线：

fetch -> probe -> select -> sidecar/systemd sidecar -> localhost SOCKS -> downstream Xray/XrayR manual integration

Web 面板的目的：

- 不是代理机场后台
- 不是 XrayR 管理器
- 不是远程 shell
- 不是生产 Xray/XrayR/x-ui 配置编辑器
- 只是 ScholarOutboundManager 的安全操作台

本阶段目标：

构建 Web 面板安全基础层，但不实现业务 dashboard。

必须实现：

1. 登录面板 + cookie session + TOTP 二次认证。
2. HTTP 抑制：除 localhost / 127.0.0.1 / ::1 / explicitly trusted proxy 情况外，拒绝非 HTTPS。
3. 登录日志，格式适配 fail2ban。
4. Web panel 专用用户权限模型，禁止 root 登录和 root 运行。
5. 输入边界收紧：非必要不输入；必要输入必须做 allowlist validation。
6. API 接口防护：认证、CSRF、method allowlist、content-type validation、rate limit、redacted response。

本阶段不做：

- dashboard
- candidate table
- node selection
- fetch/probe buttons
- sidecar stage/restart
- systemd operation execution
- production Xray/XrayR mutation
- Tailscale automation
- public deployment
- database migration beyond minimal local auth store
- OAuth/OIDC
- multi-user RBAC beyond minimal role scaffold

技术方向：

- FastAPI / Starlette-based app is acceptable.
- Web dependencies must be optional extra:
  ScholarOutboundManager[web]
- Do not import FastAPI at core package import time.
- Web app must lazy-load web dependencies.
- Default bind host: 127.0.0.1
- Default port: 8790
- Public bind requires explicit --allow-public-bind and must still enforce HTTPS/trusted proxy.

Security references to align with:

- OWASP Session Management Cheat Sheet:
  - session ID must have enough entropy
  - session ID must not contain sensitive data
  - cookies should use Secure, HttpOnly, SameSite
- OWASP Authentication Cheat Sheet:
  - login throttling / lockout
  - authentication logging and monitoring
- OWASP MFA Cheat Sheet:
  - TOTP is an accepted software OTP approach
- OWASP REST Security Cheat Sheet:
  - HTTPS for protected endpoints
  - API keys alone are not enough for critical resources
  - restrict HTTP methods
  - avoid credentials in URLs

一、依赖与入口

修改 pyproject.toml：

新增 optional extra：

[project.optional-dependencies]
web = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
    "itsdangerous>=2.2",
    "passlib[argon2]>=1.7",
    "pyotp>=2.9",
]

如 passlib[argon2] 在环境中有兼容问题，可改用 argon2-cffi + 自封装。

新增 CLI：

scholar-outbound-manager web serve

参数：

--host default 127.0.0.1
--port default 8790
--config PATH default web_panel_config.json
--allow-public-bind false
--trusted-proxy false
--dev-insecure-http false

行为：

1. 如果 web extra 未安装，输出：
   Web panel dependencies are not installed. Install with:
   pip install "ScholarOutboundManager[web]"
2. 默认只监听 127.0.0.1。
3. 如果 host 不是 127.0.0.1 / localhost / ::1 且未传 --allow-public-bind，拒绝启动。
4. 不启动业务操作。
5. 不读取 sensitive artifacts unless later pages need them. Web-0 不需要。

二、Web 配置

新增文件：

scholar_outbound_manager/web/config.py

dataclass:

WebPanelConfig

字段：

- bind_host: str = "127.0.0.1"
- bind_port: int = 8790
- session_secret_path: str = "state_data/web/session_secret"
- auth_db_path: str = "state_data/web/users.json"
- login_log_path: str = "state_data/web/auth.log"
- session_cookie_name: str = "__Host-som_session"
- session_ttl_minutes: int = 30
- absolute_session_ttl_hours: int = 8
- require_totp: bool = True
- allow_insecure_localhost_http: bool = True
- trusted_proxy_headers: bool = False
- failed_login_limit: int = 5
- failed_login_window_seconds: int = 300
- lockout_seconds: int = 900

要求：

1. Config path under state_data by default, ignored.
2. session_secret generated with CSPRNG if missing.
3. session secret file chmod 600.
4. auth_db chmod 600.
5. login log chmod 600 or 640.

三、用户模型与权限

新增：

scholar_outbound_manager/web/auth.py

dataclass:

WebUser

字段：

- username: str
- password_hash: str
- totp_secret: str | None
- role: str = "admin"
- enabled: bool = True
- created_at: str
- last_login_at: str | None = None

Rules:

1. username cannot be root.
2. username allowlist regex:
   ^[a-zA-Z][a-zA-Z0-9_.-]{2,31}$
3. role currently allow:
   - viewer
   - operator
   - admin
4. No user can have role "root".
5. Web panel process should warn/refuse if running as UID 0 unless --allow-root-process is explicitly passed.
6. Even with --allow-root-process, UI login username "root" remains forbidden.

新增 CLI：

scholar-outbound-manager web user-init

参数：

--username
--password-stdin
--totp-secret-output PATH optional
--auth-db PATH default state_data/web/users.json

行为：

1. Reads password from stdin.
2. Hashes password with Argon2 or strong password hasher.
3. Generates TOTP secret.
4. Writes user DB.
5. Prints setup summary but not password.
6. If TOTP secret printed, only print once and warn user to store it.
7. Better: write otpauth URI or QR payload to file if requested.
8. username root forbidden.

TOTP:

- Login requires password step then TOTP step.
- TOTP uses pyotp.
- Accept small clock window, e.g. valid_window=1.
- Do not log TOTP code.
- Do not store recovery codes in plaintext. If implemented, hash them. Web-0 may defer recovery codes.

四、Session cookie

Implement server-side session store:

- state_data/web/sessions.json or in-memory for first version.
- Prefer file-backed JSON for restart persistence only if safe.
- Each session record:
  - session_id_hash
  - username
  - role
  - created_at
  - last_seen_at
  - mfa_verified
  - csrf_token_hash
  - user_agent_hash optional
  - client_ip_hash optional

Cookie contains only opaque random session ID.

Cookie requirements:

- HttpOnly
- SameSite=Strict
- Secure when HTTPS
- For localhost HTTP dev tunnel, Secure may be omitted only when request host is localhost/127.0.0.1/::1.
- Path=/
- No sensitive data inside cookie.

OWASP 要求 session ID 有足够熵且不能包含敏感内容；Secure / HttpOnly / SameSite 是会话 cookie 基础防线。必须在测试中验证 cookie attributes。OWASP Session Management Cheat Sheet 明确要求 Secure cookie 只通过 HTTPS 发送，HttpOnly 防止脚本读取 cookie，SameSite 可用于 CSRF 防护。 

五、HTTPS / HTTP 抑制

新增 middleware：

RequireSecureRequestMiddleware

Rules:

1. If request scheme is https -> allow.
2. If Host is localhost / 127.0.0.1 / [::1] and config.allow_insecure_localhost_http -> allow.
3. If trusted_proxy_headers enabled:
   - accept X-Forwarded-Proto=https only when configured
   - do not trust proxy headers by default
4. Otherwise reject with 403:
   "HTTPS is required unless accessed via localhost."

Do not redirect HTTP to HTTPS automatically for non-localhost in this app, because wrong reverse proxy config could leak cookies. REST services carrying credentials should use HTTPS; OWASP REST Security notes HTTPS protects credentials in transit and gives integrity and service authentication. 

六、CSRF 防护

Because UI will use cookie sessions, POST actions need CSRF.

Implement:

- Generate csrf_token per session.
- Store hash server-side.
- Render token in forms.
- Require header or form field:
  csrf_token
- All state-changing endpoints must require CSRF.
- GET must not change state.

Even though SameSite=Strict helps, do not rely on SameSite alone. Cookie session + state-changing POST requires CSRF token.

七、登录流程

Routes:

GET /login
POST /login/password
GET /login/totp
POST /login/totp
POST /logout
GET /

Flow:

1. Anonymous user visits / -> redirect /login.
2. Password step validates username/password.
3. If valid and TOTP required:
   - create temporary pre-auth challenge state
   - do not create full session yet, or create session with mfa_verified=False
4. TOTP step validates code.
5. On success:
   - renew session ID
   - set cookie
   - redirect /
6. On logout:
   - delete server-side session
   - expire cookie

Authentication failure messages must be generic:

- "Invalid credentials"
- Do not reveal whether username exists.
- Do not reveal whether password or TOTP failed.

Add throttling:

- Track failed attempts by username hash + client IP hash.
- failed_login_limit / window / lockout_seconds.
- Account lockout or temporary IP lockout.
- OWASP Authentication Cheat Sheet recommends login throttling/account lockout and logging authentication failures.

八、登录日志与 fail2ban

新增:

scholar_outbound_manager/web/audit.py

Function:

write_auth_log(event)

Log format must be line-oriented and fail2ban-friendly.

Example:

SOMWEB_AUTH event=login_failed user=alice src=203.0.113.5 reason=invalid_credentials ts=2026-05-27T...

Events:

- login_failed
- login_success
- totp_failed
- logout
- lockout
- csrf_failed
- insecure_http_rejected
- api_unauthorized
- permission_denied

Rules:

1. Do not log password.
2. Do not log TOTP code.
3. Do not log session ID.
4. Do not log raw proxy secrets.
5. username can be logged, but sanitize.
6. IP can be logged for fail2ban.
7. All auth failures logged. OWASP Authentication Cheat Sheet explicitly recommends logging and reviewing authentication failures and password failures.

Add README sample fail2ban filter:

[Definition]
failregex = ^.*SOMWEB_AUTH event=(login_failed|totp_failed|csrf_failed|api_unauthorized).*src=<HOST>.*$

九、API protection

Web-0 should define API guard even if there are few APIs.

Rules:

1. All /api/* require authenticated session.
2. All mutating API methods require CSRF header.
3. Only allowlisted HTTP methods.
4. Reject unsupported methods with 405.
5. Validate Content-Type:
   - application/json for JSON APIs
   - application/x-www-form-urlencoded or multipart for forms
6. Reject unknown JSON fields for typed requests.
7. Pydantic models with strict validation.
8. No shell command input.
9. No path traversal:
   - user-supplied paths must resolve under approved roots, e.g. state_data.
10. Rate limit login and sensitive API endpoints.
11. API responses must use redacted view models only.
12. No API endpoint returns raw config.yaml / candidates.json / passed_candidates.json / runtime config.

OWASP REST Security recommends HTTPS for protected endpoints, API access control, method allowlists, request content-type validation, and avoiding credentials in URLs. API keys alone should not be the only protection for sensitive resources, so Web-0 must not rely on a static API token as the main defense. 

十、输入约束

Web-0 should avoid inputs except:

- username
- password
- TOTP code
- CSRF token

Validation:

- username allowlist regex
- TOTP exactly 6 digits
- no raw command strings
- no freeform file path inputs in Web-0
- no YAML/JSON editing textareas
- no subscription URL input in Web-0

Later phases can add controlled inputs through typed forms.

十一、Headers

Add security headers middleware:

- X-Content-Type-Options: nosniff
- Referrer-Policy: no-referrer
- Cache-Control: no-store for authenticated pages
- Content-Security-Policy:
  default-src 'self';
  frame-ancestors 'none';
  base-uri 'none';
  form-action 'self'
- X-Frame-Options: DENY
- Permissions-Policy minimal

Do not use external CDN assets in Web-0.

十二、Tests

新增测试：

tests/test_web_auth.py
tests/test_web_session.py
tests/test_web_security_middleware.py
tests/test_web_audit.py
tests/test_web_api_guard.py
tests/test_cli_web.py
tests/test_project_safety.py

Tests must not require real network or real systemd.

Cover:

1. core import works without web extra.
2. web serve without dependencies prints install hint.
3. user-init rejects root username.
4. user-init writes password hash, not plaintext password.
5. TOTP secret generated.
6. login with wrong password logs login_failed.
7. login with right password but wrong TOTP logs totp_failed.
8. login success sets cookie.
9. cookie is HttpOnly.
10. cookie SameSite=Strict.
11. cookie Secure on HTTPS.
12. localhost HTTP allowed when configured.
13. non-localhost HTTP rejected.
14. X-Forwarded-Proto ignored unless trusted_proxy_headers enabled.
15. CSRF required for POST.
16. GET cannot mutate state.
17. /api requires auth.
18. unknown method returns 405.
19. wrong content type rejected.
20. auth logs do not contain password/TOTP/session/proxy secret.
21. fail2ban log line includes src IP.
22. service refuses root process unless explicit allow flag.
23. no route returns raw sensitive artifact.
24. no template includes secret values.

十三、README

新增章节：

## Web panel security model

必须说明：

- Web panel is optional.
- Install with ScholarOutboundManager[web].
- Default listen is 127.0.0.1 only.
- Public bind is refused unless explicitly allowed.
- HTTP is allowed only for localhost, intended for SSH forwarding.
- For remote access, prefer SSH tunnel or Tailscale/reverse proxy with HTTPS.
- Login uses password + TOTP.
- Session cookies use HttpOnly/SameSite and Secure when HTTPS.
- Auth logs are fail2ban-friendly.
- Root web user is forbidden.
- Running web panel as root is refused by default.
- Web panel never displays raw sensitive artifacts.
- Web panel is not a production Xray/XrayR/x-ui editor.

Add examples:

scholar-outbound-manager web user-init --username admin --password-stdin
scholar-outbound-manager web serve --host 127.0.0.1 --port 8790

SSH tunnel:

ssh -L 8790:127.0.0.1:8790 oreoz

十四、验证

Run:

python -m pytest
git diff --check
git status --short
git diff --stat

Do not run live web server in tests.

十五、提交

Expected staged files:

git add \
  pyproject.toml \
  scholar_outbound_manager/cli.py \
  scholar_outbound_manager/web/__init__.py \
  scholar_outbound_manager/web/config.py \
  scholar_outbound_manager/web/auth.py \
  scholar_outbound_manager/web/session.py \
  scholar_outbound_manager/web/audit.py \
  scholar_outbound_manager/web/security.py \
  scholar_outbound_manager/web/app.py \
  scholar_outbound_manager/web/templates/login.html \
  scholar_outbound_manager/web/templates/totp.html \
  scholar_outbound_manager/web/templates/index.html \
  README.md \
  tests/test_web_auth.py \
  tests/test_web_session.py \
  tests/test_web_security_middleware.py \
  tests/test_web_audit.py \
  tests/test_web_api_guard.py \
  tests/test_cli_web.py \
  tests/test_project_safety.py

If some files are not needed, do not stage them.

Before commit, confirm staged files do not contain:

- config.yaml
- candidates.json
- passed_candidates.json
- selected_candidate.json
- state_data/
- generated/
- .runtime/
- live_test_data/
- subscription URL
- proxy URI
- UUID
- public key
- password
- token
- auth secret
- TOTP secret fixture with real value

Commit message:

feat: add secure web panel foundation

Commit body:

Add the security foundation for the optional web panel.

This change introduces the web extra entry point, login and TOTP authentication scaffolding, secure cookie sessions, HTTPS/localhost enforcement, fail2ban-friendly authentication logging, root-user suppression, CSRF protection, and API guard middleware. It establishes the web panel as a local or trusted-proxy-only admin surface without exposing sensitive artifacts or performing ScholarOutboundManager operations.

This phase intentionally keeps dashboards, candidate operations, probe controls, sidecar lifecycle actions, production Xray/XrayR mutation, live web deployment, and real network tests out of scope.