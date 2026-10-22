# Security review: monarch (public copy)

Read-only review. Nothing was run, installed, fetched or tested. Every value that might be private is written as `<REDACTED>`, and key-shaped strings are described in words.

## Summary

- **Commit reviewed:** `594e99b6e4db` (12-character short form of `git rev-parse HEAD` on `origin/master` after `git fetch origin` on 2026-10-22; the full 40-character form is left out so the report holds no long hex run).
- **Scope read:** 339 tracked files and 29 commits.
  - Pattern sweeps covered all 339 files and the full `git log -p` of all 29 commits (about 56,000 patch lines).
  - Read in full or in the relevant part: about 30 files (listed under "Checked and found sound").
- **Counts by severity:** critical 0, high 1, medium 4, low 5, info 0.
- **Most important finding (F1):** the web front end's shipped Vite dev config sets `host: true`. Running `npm run dev` therefore binds the dev server to every network interface and proxies `/api` to the backend.
  - The backend's read surface and Web Push subscribe endpoint have no token by default, so anyone on the same network can read the operator state, vault notes and supervisor answers.
  - They can also register their own device to receive the operator's alerts.
- **Publication question:** no credential, token, private key, DSN, private IP, real hostname or personal email turned up in the tree or in any of the 29 commits.
  - The author/committer identity on every commit is neutral.
  - The one gap against the README's promise is environmental detail: a live-derived state fixture and some absolute home paths (F7).

## What the README promises is absent

The README says "hosts, addresses, credentials, and the operator's environment are deliberately omitted". `loki/docs/MEMORY_ARCHITECTURE.md` adds "ports".

| Promised absent | How searched (tree = `git grep` on HEAD; history = grep over added and removed lines of `git log -p origin/master`, plus `git log --diff-filter=D`) | Result |
|---|---|---|
| Hosts (private hostnames, tailnet names) | `ts.net`, `tailnet`, `tailscale`, `.local`, `.lan`, `.internal`, `.home`; every `https?://host` and every `word.tld` token in history | **Absent.** Only placeholder names (the "your-tailnet" / "example-tailnet" style), `localhost`, `tauri.localhost`, `.invalid`, `example.com`, and public hosts (github.com, huggingface.co, healthchecks.io, fcm.googleapis.com). The updater endpoint has been a `.invalid` placeholder since it was added (49b5711). The tailnet origin is injected at build time from a git-ignored `.env`. |
| Addresses (IPs) | dotted-quad regex in tree and history; `100.x` CGNAT range | **Absent.** Only `127.0.0.1` and `0.0.0.0`. |
| Credentials (tokens, keys, DSNs, passwords, VAPID/push keys) | `token`, `secret`, `passw`, `api_key`, `vapid`, `PRIVATE KEY`, provider prefixes for cloud, chat and git tokens, JWT prefix, base64/hex runs of 32+ characters, UUIDs, `postgres://` / `redis://` with userinfo | **Absent.** All credentials are read at runtime from env vars or files outside the repo. One long base64 string exists: the Tauri updater's **public** minisign key in `command-center/desktop/src-tauri/tauri.conf.json:22` (public by design; see "Checked and found sound"). The only "PRIVATE KEY" hit is a test assertion string. |
| Emails | email regex in tree and history; commit author and committer fields | **Absent.** Only `example.com` / `example.invalid` fixtures. Every commit is authored as a neutral project identity. Some commit messages carry an AI co-author trailer (not personal). |
| Operator's environment (personal paths, machine details, ports) | `/home/<name>`, `/Users/<name>`, `C:\Users\`; the state fixture; binary asset metadata (`.glb`, `.mp4`, `.png`, `.icns`, `.ico`) searched for paths and emails | **Partly present (F7).** One consistent home-directory name appears 42 times in tree and history. A test fixture derived from the live daemon state carries hardware model strings, a service inventory with loopback ports, cron commands and backup log paths. Binary asset metadata is clean. |
| Deleted-then-public files | `git log --diff-filter=D --name-only` | 4 files deleted in 594e99b (a nested desktop-build workflow, a stores reader and its test, a React component). None holds a secret. |

## Findings

### F1

- **Title:** Shipped Vite dev server binds all interfaces and forwards to an ungated read surface and push-subscribe endpoint.
- **Area:** 4, Shipped defaults and exposure.
- **Location:** `command-center/web/vite.config.js:183-195`; `command-center/server/config.py:94`; `command-center/server/control/auth.py:139-140`; `command-center/server/api/routes.py:198`. Introduced in 35668b9.
- **Severity:** high. A default that anyone gets with `npm run dev` puts the console's sensitive read surface, and a write that redirects operator alerts, on every network the machine is attached to, with no token.
- **Status:** proven by the code quoted. Not seen: whether the operator actually runs the dev server on untrusted networks.
- **Attack path or exposure:**
  1. A developer or fork user runs the backend (it binds loopback, correctly) and `npm run dev` for the front end. Vite listens on all interfaces because of `host: true`.
  2. A stranger on the same Wi-Fi, LAN or tailnet browses to the machine's IP on the Vite port. Vite allows raw IP hosts, and every `/api` request is proxied to `127.0.0.1:8780`.
  3. With the default `CC_REQUIRE_TOKEN_FOR_READS=0`, `require_read_token` returns immediately. The stranger can then:
     - read `/api/state`, `/api/stream`, vault notes, docs search and codebase projects;
     - drive `/api/supervisor/ask`, which spins the GPU model;
     - `POST /api/push/subscribe` with their own push endpoint, which adds them to the list of devices that receive the operator's interrupt alerts (security alerts, spend bursts and others).
  4. Control actions stay behind the control token, so the stranger cannot actuate.
- **Proof:**
  ```js
  // command-center/web/vite.config.js
  183    // Dev server binds all interfaces so it's reachable over Tailscale during
  184    // local development. (Prod posture stays loopback + Tailscale; the FastAPI
  185    // backend it proxies to remains 127.0.0.1-only.)
  186    host: true,
  ...
  195      "/api": { target: process.env.CC_API_TARGET || "http://127.0.0.1:8780", changeOrigin: true },
  ```
  ```python
  # command-center/server/config.py
  94 REQUIRE_TOKEN_FOR_READS = _env("CC_REQUIRE_TOKEN_FOR_READS", "0") in ("1", "true", "True", "yes")
  # command-center/server/control/auth.py
  139    if not config.REQUIRE_TOKEN_FOR_READS:
  140        return
  # command-center/server/api/routes.py
  198 @router.post("/push/subscribe", dependencies=[Depends(require_read_token)])
  ```
- **Suggested fix:** Remove `host: true`, so Vite's default is loopback only. Have anyone who wants tailnet access opt in with `--host` or an env var. Separately, consider defaulting `CC_REQUIRE_TOKEN_FOR_READS` to on (see F2).

### F2

- **Title:** The loopback backend does not validate the `Host` header, and reads are ungated by default, so DNS rebinding from any web page can read the console.
- **Area:** 4, Shipped defaults and exposure.
- **Location:** `command-center/server/main.py:59-99` (middleware list; no host check); `command-center/server/config.py:94`.
- **Severity:** medium. It needs the operator to run the backend and visit an attacker's page while it is up. The payoff is the same read and alert-routing access as F1.
- **Status:** suspected.
  - Proven by the code: there is no `TrustedHostMiddleware` or other `Host` check, and reads are open by default.
  - Not seen: how well the operator's browser blocks rebinding to loopback (some browsers block it partly), and whether the operator sets `CC_REQUIRE_TOKEN_FOR_READS=1` in their private unit file.
- **Attack path or exposure:**
  1. The operator, or anyone who cloned and started the server with defaults, opens a stranger's web page.
  2. The page's domain is re-resolved to `127.0.0.1`, so the browser treats requests to `127.0.0.1:8780` as same-origin with the attacker's page. CORS does not apply.
  3. The page's script makes the same calls as in F1 step 3 and sends the results back to the attacker. The control endpoints still need the token.
- **Proof:**
  ```python
  # command-center/server/main.py — the only middleware are CORS and security headers
  59 app.add_middleware(
  60     CORSMiddleware,
  61     allow_origins=[
  ...
  91 @app.middleware("http")
  92 async def security_headers(request, call_next):
  ```
  No `Host` allow-list appears anywhere in `command-center/server` (searched for `TrustedHost` and `allowed_hosts`).
- **Suggested fix:** Add a `Host` allow-list containing `127.0.0.1:<port>`, `localhost:<port>` and the operator's tailnet name from an env var. Reject anything else. Defaulting the read gate on closes this as well.

### F3

- **Title:** CI installs unpinned Python packages and upgrades pip on every push and pull request.
- **Area:** 5, Install and supply chain (it also affects area 3).
- **Location:** `.github/workflows/ci.yml:32,36`; `loki/requirements.txt:1-2`. Introduced in dbeba97.
- **Severity:** medium. The install takes whatever versions PyPI serves at run time: pip itself, `pytest`, `hypothesis`, `pydantic>=2.0.0` and `croniter>=2.0.0`. A compromised or typo-squatted release runs in CI. On `push` to `master` that code holds the job's `GITHUB_TOKEN`.
- **Status:** proven by the code quoted for the unpinned installs. Not seen: the repository's default `GITHUB_TOKEN` permission setting (see F4).
- **Attack path or exposure:**
  1. An attacker publishes a malicious release of one of the floating dependencies, or takes over one.
  2. The next CI run installs it and runs its code.
  3. On a fork pull request the token is read-only and no secrets exist, so the payoff is small. On a push to `master` the code runs with the default token, which may have write rights depending on the repository setting.
  4. A reader who copies the install line (`pip install -r loki/requirements.txt`) gets the same floating set.
- **Proof:**
  ```yaml
  # .github/workflows/ci.yml
  32           python -m pip install --upgrade pip
  36           pip install -r loki/requirements.txt pytest hypothesis
  ```
  ```text
  # loki/requirements.txt
  1 pydantic>=2.0.0
  2 croniter>=2.0.0   # cron listener schedule parsing (loki/listeners/cron.py)
  ```
  `command-center/server/requirements.txt` pins exact versions; that part is sound.
- **Suggested fix:** Pin `loki/requirements.txt` and the CI test tools to exact versions. Better, use a hashed lock file with `pip install --require-hashes`. Drop `--upgrade pip` or pin pip.

### F4

- **Title:** CI uses actions on floating major tags and declares no `permissions:` block.
- **Area:** 3, The CI workflow.
- **Location:** `.github/workflows/ci.yml:10-18,24,26`. Pins changed in 5861a96.
- **Severity:** low. Both actions are first-party (`actions/*`). The trigger is `pull_request`, not `pull_request_target`, so fork code never gets secrets or write rights. The issue is hardening against tag movement and against a permissive repository default.
- **Status:** suspected for the token scope. Not seen: the repository's "Workflow permissions" setting. If it is "read and write", the push job's token can write contents.
- **Attack path or exposure:**
  1. If an action's `v5` or `v6` tag were moved to malicious code, every run would execute it with the job token.
  2. Because no `permissions:` block exists, the token's scope is whatever the repository default is.
  3. `actions/checkout` also persists the token in `.git/config` for the remaining steps, which run repository test code.
- **Proof:**
  ```yaml
  # .github/workflows/ci.yml
  10 on:
  11   push:
  12     branches: [master]
  13   pull_request:
  ...
  24       - uses: actions/checkout@v5
  ...
  26       - uses: actions/setup-python@v6
  ```
  The file contains no `permissions:` key.
- **Suggested fix:**
  - Add `permissions: contents: read` at workflow level.
  - Pin both actions to full commit SHAs, with the tag kept as a comment.
  - Set `persist-credentials: false` on checkout.

### F5

- **Title:** The wake-word training script clones unpinned repositories, pip-installs them, downloads a checkpoint without verifying it, and loads it with pickle enabled.
- **Area:** 5, Install and supply chain.
- **Location:** `loki/loki/voice/training/run_training.sh:33,36-37,45,48,52-54,102-103,141-147`. Added in a9886fe.
- **Severity:** medium. Anyone who follows `TRAINING.md` runs whatever is at the head of two third-party repositories at that moment, including `setup.py` during `pip install -e`. They also execute a downloaded `.pt` file as a full pickle.
- **Status:** proven by the code quoted.
- **Attack path or exposure:**
  1. A reader or fork user runs `run_training.sh`.
  2. `git clone --depth 1` takes the current default branch of each repository, with no tag or commit.
  3. `pip install -e` runs that repository's build code.
  4. A model checkpoint is fetched with `curl -L` and no checksum. The script then patches the loader to `torch.load(..., weights_only=False)`, so whoever controls that release asset, or anything along the path, can run code on the reader's machine.
  5. Six training packages are installed with no versions, and errors are hidden by `|| true`.
- **Proof:**
  ```bash
  33   git clone --depth 1 https://github.com/dscripka/piper-sample-generator.git piper-sample-generator-dscripka
  36   curl -L -o piper-sample-generator-dscripka/models/en-us-libritts-high.pt \
  37     https://github.com/rhasspy/piper-sample-generator/releases/download/v1.0.0/en-us-libritts-high.pt \
  45   git clone --depth 1 https://github.com/dscripka/openWakeWord.git openWakeWord-src
  48 $PY -m pip install -e ./openWakeWord-src >/dev/null
  52 $PY -m pip install mmap_ninja torchinfo speechbrain audiomentations acoustics \
  ...
  103       "    model = torch.load(model_path, weights_only=False)  # trusted release; torch>=2.6\n",
  ```
- **Suggested fix:**
  - Clone at a fixed commit (`git -c advice.detachedHead=false checkout <sha>` after the clone).
  - Verify a SHA-256 of every downloaded file before using it.
  - Pin the pip packages.
  - Keep the `weights_only=False` patch only behind a verified checksum.

### F6

- **Title:** The voice service turns authentication off when `LOKI_VOICE_KEY` is unset, while its docs tell the operator to bind it to the LAN over plain HTTP.
- **Area:** 4, Shipped defaults and exposure.
- **Location:** `loki/loki/voice/config.py:26-28`; `loki/loki/voice/service.py:24-27,41-45`; `loki/loki/voice/edge/README.md:21`. Added in a9886fe.
- **Severity:** medium. The default bind is loopback, which is sound. The exposure needs the documented `0.0.0.0` bind plus a missing key, or an attacker on the LAN capturing the key, which travels in clear text.
- **Status:** proven by the code quoted.
- **Attack path or exposure:**
  1. A reader follows the edge README and starts the service with `LOKI_VOICE_HOST=0.0.0.0`.
  2. If the key is empty or unset, `_authed()` returns `True` for everyone. If it is set, it is compared with `==` (not constant-time) and sent in an `X-Voice-Key` header over plain HTTP, so a LAN observer can capture it.
  3. A stranger on the LAN posts audio and gets the supervisor's spoken and text answers about the live system, and spends GPU time.
  4. The handler reads `Content-Length` bytes with no upper bound, so one request can exhaust memory.
- **Proof:**
  ```python
  # loki/loki/voice/config.py
  26         host=os.environ.get("LOKI_VOICE_HOST", "127.0.0.1"),
  28         voice_key=os.environ.get("LOKI_VOICE_KEY") or None,
  # loki/loki/voice/service.py
  24         def _authed(self) -> bool:
  25             if cfg.voice_key is None:
  26                 return True
  27             return self.headers.get("X-Voice-Key") == cfg.voice_key
  ...
  43             n = int(self.headers.get("Content-Length", "0"))
  44             wav = self.rfile.read(n)
  ```
  ```text
  # loki/loki/voice/edge/README.md
  21     LOKI_VOICE_HOST=0.0.0.0 LOKI_VOICE_KEY=… loki-voice start
  ```
- **Suggested fix:**
  - Refuse to start on a non-loopback host when no key is set (fail closed).
  - Compare with `secrets.compare_digest`.
  - Cap `Content-Length`.
  - Point the docs at the tailnet IP or `tailscale serve` instead of `0.0.0.0`.

### F7

- **Title:** Operator environment details are published in a live-derived test fixture and in absolute home paths, contrary to the README.
- **Area:** 1 (tree) and 2 (history); the claim mismatch is area 7.
- **Location:**
  - `command-center/server/tests/fixtures/state.sample.json`: hardware model strings at lines 1694 and 1701; the service list with loopback ports, for example lines 1773, 1800, 1845 and 1863; cron commands and log paths at lines 2166-2251.
  - The same home-directory name in `command-center/README.md:68`, `command-center/desktop/Dockerfile.build:16-20`, `command-center/web/scripts/gen_splash.py:8-9`, `command-center/web/src/deepdive.test.jsx:22`, `command-center/server/tests/test_deepdive2.py:103` and `loki/loki/listeners/tests/test_cron.py:70,120-133`.
  - History: the fixture was added in 2143fe3 and the paths are present from 2473313 and 35668b9 onward. Values are unchanged in later commits.
- **Severity:** low.
  - No address, hostname or credential is exposed.
  - What a stranger learns is a map of the private stack: CPU and GPU models, which services run, their loopback ports, backup locations, cron schedule and script names. That helps an attacker who already has a foothold, and it contradicts "the operator's environment [is] deliberately omitted".
  - It would be high only if the home-directory name is the operator's real login.
- **Status:** suspected. I could not tell whether the home-directory name is a placeholder (tests also use other obviously fake names) or the operator's real Unix username. `scripts/make_fixture.py` scrubs only session IDs, input timestamps and the daemon PID, so the rest of the fixture is the live state as it was on the capture date.
- **Attack path or exposure:**
  1. A stranger reads the fixture.
  2. They learn the hardware, the service inventory with ports, the backup script paths and the cron cadence of the operator's real machine.
  3. If the home-directory name is real, they also learn the operator's login name.
- **Proof:** paraphrased, because quoting the values would publish them:
  - `state.sample.json:1694` and `:1701` hold a `"model"` key whose value is a specific consumer CPU or GPU model string.
  - Lines 2170-2251 hold `"command"` and `"log_path"` keys whose values are absolute paths under `/home/<REDACTED>/`.
  - `command-center/README.md:68` shows a systemd `Environment=` line mapping repository keys to absolute paths under `/home/<REDACTED>/projects/`.
  - `scripts/make_fixture.py:21-28` shows the scrub covers only `operator.active_session_id`, `last_input_detected`, `updated_at` and `daemon_pid`.
- **Suggested fix:**
  - Regenerate the fixture with a scrub that also replaces hardware strings, absolute paths, cron commands and PIDs with neutral placeholders. Replace the home paths in docs and scripts with `~` or `$HOME`.
  - **No rotation is needed**, since nothing secret is involved.
  - A history rewrite is needed only if the owner decides the username or hardware detail must not be public. The values are readable at 2143fe3, so a forward commit alone leaves them public.

### F8

- **Title:** When the read gate is on, the SSE stream accepts the control token as a `?token=` query parameter.
- **Area:** 4, Shipped defaults and exposure.
- **Location:** `command-center/server/control/auth.py:145-163`.
- **Severity:** low. This is only reachable after the operator turns on `CC_REQUIRE_TOKEN_FOR_READS`. The token is the same one that authorises control actions, and URLs end up in access logs, proxy logs and browser history.
- **Status:** proven by the code quoted. Not seen: whether uvicorn or Tailscale access logs are kept in the operator's deployment.
- **Attack path or exposure:**
  1. Anyone who can read the uvicorn access log, a reverse-proxy log, or the browser history on a shared device recovers the full control token.
  2. With it they can `POST /api/control/<action>`.
- **Proof:**
  ```python
  147     token: str | None = Query(default=None),
  ...
  161     if token and _same(token, get_token()):
  162         return
  ```
- **Suggested fix:** Use a separate, read-only and short-lived stream ticket, issued by an authenticated POST, instead of the control token in the URL. Or use a fetch-based SSE client that can send headers.

### F9

- **Title:** README security claims overstate the default read posture.
- **Area:** 7, README claims versus the tree.
- **Location:** `README.md:22,45-50,65`.
- **Severity:** low. This is a documentation mismatch that steers readers toward a false sense of a token-gated console. The code itself is honest about it (`config.py:89-94`).
- **Status:** proven by the code quoted.
- **Attack path or exposure:** A reader who clones and runs the console because the README says it has "a token read-gate" gets an open read surface plus open push subscription. Combined with F1 and F2, that surface reaches the network or a malicious page.
- **Proof:**
  ```text
  README.md:49-50  ...constant-time token compare, a global dry-run, an append-only audit log, and a token read-gate.
  ```
  ```python
  # command-center/server/config.py
  91 # token — not just mutations. Default off keeps the tailnet as the read trust
  94 REQUIRE_TOKEN_FOR_READS = _env("CC_REQUIRE_TOKEN_FOR_READS", "0") in ("1", "true", "True", "yes")
  ```
- **Suggested fix:** Say in the README that the read gate is opt-in and off by default, or turn it on by default.

### F10

- **Title:** Install docs use `curl | sh` and unpinned `pip install`.
- **Area:** 5, Install and supply chain.
- **Location:** `command-center/desktop/README.md:76`; `loki/loki/voice/edge/README.md:9`; `loki/deploy.sh:61`.
- **Severity:** low. The `curl | sh` target is the official rustup installer over HTTPS, and the pip lines install well-known packages. This is hardening.
- **Status:** proven by the code quoted.
- **Attack path or exposure:** A reader copying these lines runs whatever the remote serves at that moment, with no version or hash check.
- **Proof:**
  ```text
  command-center/desktop/README.md:76  - **Rust** (stable): `curl https://sh.rustup.rs -sSf | sh`
  loki/loki/voice/edge/README.md:9         pip install openwakeword sounddevice requests torch numpy
  loki/deploy.sh:61                     pip install "pydantic>=2.0.0" --quiet
  ```
- **Suggested fix:** Pin the versions, and point the Rust step at the distro or rustup docs rather than an inline pipe-to-shell.

## Checked and found sound

1. **Secrets in tree:**
   - All 339 files were swept for credential, key, DSN, IP, email and tailnet patterns.
   - Credentials are only ever read at run time:
     - `config.py:35,43` (env or a file outside the repo);
     - `loki/listeners/memory.py:58-66,134,171` and `loki/supervisor/retrieval.py:86-90,171-189` (Postgres password from `~/monarch-stack/.env`);
     - `loki/supervisor/client.py:45` (LiteLLM key from the environment);
     - `push/vapid.py` (VAPID key generated at run time into a git-ignored runtime directory).
   - `desktop/.env.example` holds only a placeholder name.
   - The Tauri updater value is a public verification key, which is meant to be public. Its private signing key is not in the repository.
   - `.gitignore` excludes `.env`, `*.key`, `*.pem`, `*secret*` and `.hypothesis/`.
2. **Secrets in history:**
   - Grepped all 29 commits' added and removed lines, the 4 deleted files (594e99b), and the redaction-style commits a3c66ac, 88e8568, 1d217ac and feae477.
   - No value was removed in a later commit that is readable in an earlier one.
   - No `.hypothesis/`, `.env`, `.pem`, `.db` or runtime file was ever committed.
   - The build-time endpoint script history (5db84f5, 49b5711) only ever used placeholders.
   - Commit identities are neutral.
   - Binary assets carry no path or email metadata.
3. **CI:**
   - The `pull_request` trigger (not `pull_request_target`) means fork code gets a read-only token and no secrets.
   - No `secrets.*` is referenced in `ci.yml`, and no `github.event.*` text is interpolated into a shell.
   - `${{ github.workspace }}` is the only expression in a step.
   - The deleted `command-center/.github/workflows/desktop-build.yml` (05553bd to 594e99b) sat outside the root `.github/workflows`, so GitHub never ran it. It had `permissions: contents: read` and used a secret only on tag or manual triggers.
4. **Defaults:**
   - The backend binds `127.0.0.1:8780` (`config.py:30-31`).
   - CORS is a fixed allow-list with no credentials (`main.py:59-67`).
   - Strict CSP and security headers are set (`main.py:77-96`).
   - Control endpoints always require the token, compared in constant time (`auth.py:60-75,120-128`).
   - The token is generated with `secrets.token_urlsafe(32)` and written with mode 0600, and only a fingerprint is logged (`main.py:29-33`).
   - The control dry-run and `confirm` requirement are in place (`routes.py:256-280`).
   - The SPA static handler blocks path traversal (`main.py:118-125`).
   - The realmic recorder binds loopback, mints a token and fails closed when it is unset (`server.py:120-124`).
   - Redis and Postgres default to loopback.
   - The Tauri capability set is minimal (`capabilities/default.json`).
5. **Supply chain:**
   - `command-center/server/requirements.txt` pins exact versions.
   - Both `package-lock.json` files and `Cargo.lock` are committed, with registry URLs only.
   - No install-from-URL in any requirements file.
6. **Injection:**
   - Every `subprocess` call is list-form with a fixed program: `control/registry.py:147-149`, `codebase_bridge.py:34` (request data passed as one JSON argv element), `reader/lokiq.py:34`, the loki actions, `listeners/memory.py:200,209` and `realmic_recorder/server.py:16`.
   - No `shell=True`, `eval`, `exec`, `pickle` (except F5), `yaml.load` or `os.system` in shipped code.
   - SQL is parameterised or built with `psycopg2.sql.Identifier` from fixed candidates: `pg_reader.py`, `listeners/quota.py:162-210` and `supervisor/retrieval.py`.
   - Vault path joins are resolved and checked for prefix and suffix (`vault_reader.py:34-52`).
   - Workflow triggers are a closed allow-list with no arbitrary URLs (`registry.py:120-124`).
   - `MarkdownLite.jsx` avoids `dangerouslySetInnerHTML`.
   - The one `innerHTML` (`realmic_recorder/static/app.js:30`) renders fixed labels and numbers.
7. **README claims:**
   - "Supervisor is structurally floored to an operator-gated tier": **supported**. `authority.py:419-420` returns Tier 3 for non-rule origin, `:460-461` forces a blocking ask, `:629` keeps it off the ladder, and `supervisor/proposals.py:118-122` forces `origin` on drain.
   - "Closed-enum, argv-list, no shell, constant-time compare, dry-run, append-only audit": **supported**.
   - "Token-gated control surface": **supported**.
   - "Token read-gate": **opt-in, off by default** (F9).
   - "Credentials omitted": **supported**.
   - "Hosts, addresses omitted": **supported**.
   - "Operator's environment omitted": **contradicted in part** (F7).
   - `MEMORY_ARCHITECTURE.md:9-10` "omits ... ports": **contradicted in part**. Loopback ports appear in `config.py` defaults and the fixture (F7).
   - "Backend binds 127.0.0.1": **supported**, but the Vite dev server does not (F1).
   - `docs/ARCHITECTURE.md` makes no security claim beyond the authority model, which is supported.

## Not reviewed

- **Front end:** the `.jsx`, `.js`, `.ts`, `.tsx` and `.css` files under `command-center/web/src` were covered only by pattern searches (HTML sinks, `eval`, token storage, URLs), not read line by line. `control.js` was read for token storage.
- **Desktop app:** the Rust sources (`desktop/src-tauri/src/*.rs`) were read only for the navigation-guard test strings. `Cargo.lock` and the npm lock files were checked for registry URLs only. Without network access, no advisory database could be checked for the pinned versions, for example Vite 6.4.3 or the Python pins.
- **Withheld from this copy:** the embedded terminal ("Atlas C3a"; `config.py:175-183`, `command-center/README.md:58-70`, a WebSocket mentioned at `App.jsx:216`). Its server route is not in the tree, so its authentication and cwd allow-list could not be reviewed.
- **Loki modules:** listener and rules modules other than `memory.py`, `quota.py` and `cron` tests; `loki/bin/*` beyond a pattern search; and the voice training Python files (`train.py`, `gen_samples.py`, `build_eval_set.py`, `evaluate.py`), which were pattern-searched only.
- **Contracts:** `contracts/` was pattern-searched only (no network, process or secret hits).
- **Outside the checkout (by rule):** GitHub repository settings (default workflow token permissions, branch protection, secrets) and the operator's private unit files.

## Guessed

- I assume the home-directory name used throughout is a curation placeholder rather than the operator's real username, because the tests use other obviously fake names in the same position. I did not verify it (F7).
- I assume no Actions secrets are configured on this repository, because `ci.yml` references none. Repository settings were not visible.
- I assume the operator runs the production backend behind `tailscale serve`, as the docs say, and not the Vite dev server. F1 matters most for readers and forks, whatever the operator does.
- I assume the `stc_activity.json` brain-activity data comes from a public MNE sample dataset (its loader says "MNE source estimate data") and is not personal data. I did not check its origin.

## Noticed, not in scope

1. `command-center/README.md:111` says port 8770 while `config.py:31` and `vite.config.js:195` use 8780 (documentation drift).
2. `/api/control/actions` is unauthenticated and lists the allow-listed n8n workflow names (`routes.py:239-242`).
3. The voice service returns raw exception text in a 500 body (`service.py:47-48`).
4. The Tauri build overrides the committed CSP at build time (`build-desktop.sh`), so the committed `tauri.conf.json` CSP is not what ships.
5. `command-center/README.md:71-72` points at an installer under `vault/_artifacts/...`, which is not in this repository.
6. Third-party 3D and video assets (`head_woman_basemesh.glb`, brain meshes, `brain-intro.mp4`) carry no licence note.

---
Report content commit: see the commit that last changed this file on `cloud/m647-w3-13-security-public`; its SHA is recorded in the final chat message.
