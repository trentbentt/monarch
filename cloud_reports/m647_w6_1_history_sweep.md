# M647 W6.1 — monarch history sweep

This repository is public, so anything ever committed here, including a value later deleted, is already exposed to anyone who reads it.

## Summary

- **Real hits: 0.**
- **Fixture, placeholder or non-secret hits: 5** (H1–H5 below). None is a secret.
- **Classes searched with no hit at all: 18** (listed under "Searched and found nothing").
- Started from `origin/master` at `594e99b6e4db614ac70c5d0872ef96fa3ba08896` (branch `cloud/m647-w6-1-monarch-history-sweep` created from it).
- `git rev-list --count origin/master` = 29; `git rev-list --count --remotes` = 32 (measured before this branch was pushed).
- Refs on GitHub at the start: 2 branches (`master`, `cloud/m647-w3-13-security-public`), 0 tags. Commits searched: 32 = every commit reachable from those two refs (29 on `master` plus 3 only on the security-review branch). This report's own commits are not part of the search.
- Clone complete: yes. `git fetch --unshallow` refused because the clone was already complete; `git fetch origin` then ran, and `git rev-parse --is-shallow-repository` printed `false`.
- Report content commit: see the last line of this file.

## What I searched for

Every class was searched with `git grep -I -n -E` (most of them case-insensitive) over all 32 commits, so every blob in every tree was covered. Deleted files, file names and redactions were checked with `git log` over the same two refs. When I looked at a hit, I printed only its commit, path and line number, with the matched text masked.

| # | Class | How (in words) |
|---|-------|----------------|
| 1 | Cloud access key IDs | One cloud provider's four-letter key-ID prefixes followed by 16 upper-case alphanumerics |
| 2 | Cloud secret access keys | The words "aws", "secret" and an assignment within a short distance |
| 3 | Source-host tokens | Source-host personal, OAuth, user, server and refresh token prefixes, and the fine-grained-token prefix, followed by 20 or more characters |
| 4 | LLM provider keys | Two LLM providers' key prefixes followed by 10–20 or more key characters |
| 5 | Search/cloud API keys and OAuth | One search provider's API-key prefix followed by 35 characters; its OAuth access-token prefix; its OAuth client-ID domain shape |
| 6 | Chat-app tokens and webhooks | One chat app's token prefixes; its incoming-webhook URL path; another chat app's webhook URL path; a messaging bot's numeric-ID-colon-token shape |
| 7 | Payment keys | Live/test secret, restricted and publishable key prefixes followed by 16 or more characters |
| 8 | SMS/email provider keys | Two-letter prefix followed by 32 hex characters (two shapes); one email provider's dotted three-part key shape |
| 9 | Model-hub, package-registry and code-host tokens | Their documented token prefixes followed by the documented length |
| 10 | JWTs | Three dot-separated base64url segments, the first two starting with the encoded opening brace |
| 11 | Private key blocks | A PEM private-key header of any type, an OpenSSH header, a PuTTY key-file header, a minisign secret-key comment, a Tauri signing private-key variable |
| 12 | Connection strings with passwords | Any URL scheme, then `user:password@` |
| 13 | Password assignments | password / passwd / pwd, then `=` or `:` and a quoted value |
| 14 | Authorization headers | An "Authorization:" header with Bearer, Basic or token and a value |
| 15 | Generic secrets | api key / secret / token / auth key / access key / client secret / push key / webhook names assigned a quoted value of 16 or more key characters; then a looser pass with no quotes and 20 or more characters; then a short pass with any quoted value of 4 or more characters (this pass found H2–H4) |
| 16 | Web-push (VAPID) keys | The word "vapid" near a 40-or-more-character base64url run, and the VAPID private-key names |
| 17 | Push/alert service keys | A push-notification service's topic URL shape, a mobile-push service name, and its token prefix |
| 18 | High-entropy strings anywhere | Every run of 24 or more base64/hex characters outside lockfiles, kept when it mixed upper case, lower case and digits or was 32 or more hex characters, then read one by one |
| 19 | Private hosts, IPs, emails, home paths in removed lines | Every removed line in every diff, checked for private-network hostnames, IPv4 addresses (classified as loopback, private or other), email addresses and home-directory paths |
| 20 | Deleted files (area 2) | `git log --diff-filter=D --name-only`; read the last version of each deleted file |
| 21 | Credential-shaped file names (area 3) | Every path ever committed, matched against env files, pem/key/p12/pfx, SSH key names, credentials, secret, service-account JSON, keystores, htpasswd, netrc/npmrc/pypirc, token |
| 22 | Redactions (area 4) | Commit messages mentioning redact/secret/token/key/password/credential/scrub/leak/rotate/neutralize; their removed lines; and the full history of each placeholder file |

## Hits

No real hits. The five below are all fixtures, placeholders or public-by-design values. Each is described in words and none of its value is reproduced.

### H1
- **Kind:** other: a public key, namely the desktop app's updater signature-verification key (a base64 minisign public key).
- **Real or fixture:** Not a secret. Decoded locally, its first line is the standard minisign *public*-key comment, and the desktop README says only the public half is committed and the private half lives in CI secrets. No matching private key or signing password exists anywhere in history (class 11 found nothing).
- **Where:** `49b5711 command-center/desktop/src-tauri/tauri.conf.json:22` (still at that line on `master`).
- **Still reachable from:** `origin/master`, `origin/cloud/m647-w3-13-security-public`; no tags (`git branch -r --contains`, `git tag --contains`).
- **Removed in:** not removed.

### H2
- **Kind:** token (test fixture): the command-center control/read token used by the server test suite.
- **Real or fixture:** Fixture. It is a short readable phrase made of the words "test" and "token" and a three-digit counting number, it is passed only to the in-process test client, and the server's real token is generated at runtime with a secure random generator or read from configuration.
- **Where (lines at `master`):** `2143fe3 command-center/server/tests/test_api.py:21`, `:41`; `2143fe3 command-center/server/tests/test_security.py:22`, `:34`, `:121`, `:189`, `:442` (more uses added in `feae477`).
- **Still reachable from:** `origin/master`, `origin/cloud/m647-w3-13-security-public`; no tags.
- **Removed in:** not removed.

### H3
- **Kind:** other (test fixture): the voice-service shared key used by the voice tests.
- **Real or fixture:** Fixture. It is the word "secret" with one letter swapped for a digit, set only inside test config objects and compared against a request header in the tests. The real value comes from an environment variable.
- **Where (lines at `master`):** `a9886fe loki/loki/voice/tests/test_config.py:21`, `:25`; `a9886fe loki/loki/voice/tests/test_service.py:92`, `:99` (it was at lines 42 and 50 before `4f3f12d` moved it).
- **Still reachable from:** `origin/master`, `origin/cloud/m647-w3-13-security-public`; no tags.
- **Removed in:** not removed.

### H4
- **Kind:** provider key (placeholder): an LLM-router master key written into a temporary env file by one test.
- **Real or fixture:** Placeholder. The value is an LLM provider's two-letter key prefix, a hyphen, and then the plain word "secret", with no random part. It is written to a pytest temporary directory to check that the env-file parser reads the variable.
- **Where:** `1f5208c command-center/server/tests/test_supervisor_bridge.py:28`, `:31`.
- **Still reachable from:** `origin/master`, `origin/cloud/m647-w3-13-security-public`; no tags.
- **Removed in:** not removed.

### H5
- **Kind:** other (placeholder): a backend URL in an example env file. It is a credential-shaped file name (`.env*`), so area 3 lists it.
- **Real or fixture:** Placeholder. The only value is an HTTPS URL on a private-network host whose subdomain is literally the words "your tailnet". Both versions of the file (`5db84f5`, `49b5711`) hold only comments and that placeholder. Across all history the only private-network hostnames are this one and another whose subdomain is literally "example tailnet".
- **Where:** `5db84f5 command-center/desktop/.env.example` (last line), and `49b5711 command-center/desktop/.env.example` (last line on `master`).
- **Still reachable from:** `origin/master`, `origin/cloud/m647-w3-13-security-public`; no tags.
- **Removed in:** not removed (`49b5711` reworded the comments only).

Matches that were judged noise and are not counted as hits:
- `command-center/desktop/src-tauri/Cargo.lock`: 1,441 matches of the two-letter-plus-32-hex shape, all inside crate `checksum = "<sha256>"` lines (case-insensitive matching made the hex digests fit).
- `command-center/scripts/deadman-ping.sh:20`: a comment naming notification services, with no value.
- High-entropy pass: the remaining matches are Python/JS identifiers (test function names, a base64-to-bytes helper name), environment-variable names and a public dataset file name and URL.
- Two IPv4 addresses appear in history, both loopback or the any-address.

## Searched and found nothing

1. Cloud access key IDs: none.
2. Cloud secret access keys: none.
3. Source-host tokens (classic and fine-grained): none.
4. LLM provider keys with a real random body: none. H4 is the only provider-prefix string, and it is a placeholder word.
5. Search/cloud API keys, OAuth tokens and client IDs: none.
6. Chat-app tokens, chat webhooks, messaging-bot tokens: none.
7. Payment provider keys: none.
8. SMS/email provider keys: none outside lockfile checksums.
9. Model-hub, package-registry and code-host tokens: none.
10. JWTs: none.
11. Private key blocks (PEM, OpenSSH, PuTTY, minisign secret key, Tauri signing private key): none. The Tauri signing variables appear only as names in a README and in the deleted workflow, referencing CI secrets.
12. Connection strings with an embedded password: none.
13. Password assignments with a quoted value: none.
14. Authorization headers with a literal value: none.
16. Web-push (VAPID) private or public key literals: none. Keys are generated at runtime by `vapid.py`; only function names match.
17. Push/alert service topic URLs or tokens: none.
19. Private IPs, real private hostnames, email addresses or home-directory paths in removed lines: none. Only loopback, the any-address and two placeholder tailnet hosts.
20. Deleted files: four, all deleted in `594e99b`: `command-center/.github/workflows/desktop-build.yml`, `command-center/server/reader/stores.py`, `command-center/server/tests/test_stores.py`, `command-center/web/src/components/MemoryQueues.jsx`. In their last versions, the workflow refers to CI secrets by name only and holds no values; the other three hold no credentials.
21. Credential-shaped file names: only `command-center/desktop/.env.example` (placeholder, H5) and `command-center/web/src/design/tokens.css` (design tokens, i.e. CSS colour and spacing variables, not credentials). No `.env`, pem, key, p12, pfx, SSH key, credentials, secret-named file or service-account JSON was ever committed.
22. Redactions: none found that hide a value. The commits whose messages mention neutralizing or withholding (`a3c66ac`, `49b5711`, `2264be6`) removed an internal model alias, comments and file contents. None of their removed lines matched any class above. No earlier version of any file holds a secret that was later replaced.

## Not searched

- The local tracking ref `origin/claude/beautiful-heisenberg-kqm612`: it no longer exists on GitHub, and it points at `594e99b`, which is already in `master`, so no commit was missed.
- Binary blobs: `git grep -I` skips binary files, so secrets inside images, archives or compiled files were not checked.
- GitHub-side objects that no ref reaches: closed or merged pull-request refs, dangling commits, forks, Actions logs, issue or PR text and release assets. Only branch and tag refs were fetched, and the brief forbids other network calls.
- Secrets with no recognisable shape or keyword nearby (for example a short random password in a variable with an unusual name) could be missed by pattern search. The "short quoted value next to a credential word" pass in class 15 reduces this but does not remove it.

## Guessed

- I assumed the ref list printed by `git ls-remote origin` is the complete set of refs on GitHub. That command contacts the remote, which is network access beyond the two `git fetch` commands section 2 allows. I disclose it here as a deviation. It was read-only.
- I assumed the H1 public key has no matching private key elsewhere. I can only show that no private key is in this repository's history.
- I assumed H2–H4 are not reused as real values in a deployment. They read as test placeholders, but I cannot check the real environment.
- I judged the high-entropy matches to be identifiers or file names from their masked shape and the surrounding code, not from their full values.

Report content commit: `eeb53f31bcdbfdbe5407bedb3d5e03cd58ab8839` (this line itself is added by the commit after it).
