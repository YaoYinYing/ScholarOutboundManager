# ScholarOutboundManager

ScholarOutboundManager is a staged, fail-closed Google Scholar outbound manager for offline candidate review, sequential probing, safe inspection, and isolated SOCKS sidecar runtime preparation.

## Project Status

- `fetch` may download subscription content into a local sensitive `candidates.json` artifact.
- `fetch` can parse plain URI subscriptions and Clash-compatible YAML subscriptions.
- `fetch` requires explicit CLI opt-in with `--allow-network-fetch`.
- `fetch` does not probe Google Scholar and does not start Xray.
- Current inputs for `probe`, `sidecar`, and legacy `generate` can come from a locally fetched `candidates.json` file or other offline candidate artifacts.
- `probe` is protected by a two-key network safety gate.
- `probe.allow_network_probe` must be `true` in config.
- `--allow-network-probe` must also be passed on the CLI.
- Without both, `probe` fails before starting Xray or sending Scholar HTTP requests.
- `probe` runs sequentially.
- There is no concurrency.
- There is no retry or cache layer in the current CLI workflow.
- Scholar probe pass/fail is two-stage: Scholar home and a reference query must both pass.
- `select` builds a redacted candidate catalog and writes a sensitive selected-candidate artifact for stable manual choice.
- `select` can apply a geo-aware ranking heuristic from local cache before falling back to the first available candidate.
- `probe` and legacy `generate` apply configured candidate filters before probing or export.
- Passed-candidates artifacts may preserve `ProbeResult` evidence for later manifest generation.
- `generate` only writes offline JSON fragments and does not start Xray.
- `run` prepares one local runtime config and can optionally execute `xray run -test`, but it does not probe Google Scholar.
- `inspect` only performs safe local review of existing artifacts.

## Safety Model

### Review-safe artifacts

- Probe summary JSON
- Generated manifest JSON
- `inspect` command output

These artifacts are intended for review and should avoid raw proxy credentials.

### Sensitive local artifacts

- `passed_candidates.json`
- `candidates.json`
- `selected_candidate.json`
- `config.yaml`
- Runtime configs under `.runtime/`
- Geo cache files under `state_data/geo/`
- Any file containing proxy URI, UUID, public key, token, or subscription material

`passed_candidates.json` contains selected proxy credentials. It may also contain `ProbeResult` evidence used later by `generate`. It must not be committed.

`candidates.json` may contain downloaded subscription material, raw proxy URIs, UUIDs, and public keys. It must not be committed.

`config.yaml` must not be committed.

`state_data/` and `generated/` should remain local.

Geo cache files under `state_data/geo/` are local operational data. They should remain ignored and should not be committed by default.

`inspect` never prints selected proxy credentials from sensitive artifacts.

### Legacy generated Xray artifacts

- Generated outbounds JSON
- Generated routes JSON
- Generated manifest JSON

These artifacts are produced locally from offline candidate input and are retained for legacy export, debugging, or advanced downstream tooling. They are not the recommended production integration path.

### Network probe safety gate

Network probing is opt-in at both config and CLI layers.

- The config default should remain `allow_network_probe: false`.
- Users should only enable it in a local, ignored `config.yaml`.
- The CLI flag is an intentional second confirmation.

Subscription fetching is also explicit opt-in at the CLI layer.

- `fetch` may download remote subscription content.
- `--allow-network-fetch` is required before any subscription download starts.
- `--user-agent` may override the request User-Agent for local fetch smoke tests.
- `fetch` writes a sensitive local candidate artifact and should only be used with a local ignored output path.

## Runtime Backend Direction

- Subscription parsing may accept Clash YAML because subconverter can emit Clash-compatible YAML payloads.
- Only the top-level `proxies` list is parsed from Clash YAML subscriptions.
- Health-check URLs, provider URLs, and other non-proxy `url:` fields are ignored during parsing.
- Xray-compatible Clash YAML protocols now include VLESS, Trojan, Shadowsocks, and VMess when required fields are present.
- Unsupported protocols such as hysteria2, tuic, and wireguard still require a future `mihomo` probe backend.
- `mihomo` is a useful future probe backend for broader protocol coverage.
- Localhost SOCKS sidecar integration is the preferred production path.
- The project should not reimplement proxy protocol data planes directly.
- Xray binary availability is not assumed on the target machine.
- Future work may add explicit Xray binary acquisition or update support, but it must stay opt-in and checksum-aware.
- Fetch and parse workflows do not require Xray or `mihomo`.

## Xray Binary Preparation

- `probe` and `run` require an Xray-compatible binary path in local config.
- The project does not silently download Xray.
- You can inspect an existing binary:

```bash
scholar-outbound-manager xray inspect --path /usr/local/bin/xray
```

- You can explicitly install Xray into a local ignored runtime directory:

```bash
scholar-outbound-manager xray install \
  --install-dir .runtime/xray \
  --version latest \
  --allow-download
```

- Then point local `config.yaml` at the installed binary:

```yaml
xray:
  binary_path: ".runtime/xray/xray"
```

- Do not commit downloaded binaries.
- Do not commit `config.yaml`.
- Download is explicit opt-in.
- Tests do not download real binaries.
- Final VPS probing should use a known Xray binary version.

## Managed Xray Process Ownership

- ScholarOutboundManager never manages Xray by process name alone.
- It only terminates the `Popen` object it started or a PID recorded in a project-managed pid file.
- Managed ownership is defined by the expected Xray binary path and runtime config path.
- External Xray services such as `x-ui` are not blockers and are never killed by this project.
- Cleanup must match the expected binary path and may also require the expected runtime config path.
- Do not use `killall xray` or `pkill xray` for this project.
- For manual checks, use project-managed pid files under `.runtime/` instead of global process-name scans.

On a VPS, the recommended manual chain is:

```bash
scholar-outbound-manager environment
scholar-outbound-manager xray inspect --path .runtime/xray/xray
scholar-outbound-manager probe --config config.yaml --candidates candidates.json --allow-network-probe
scholar-outbound-manager inspect --probe-summary state_data/probe_summary.json
scholar-outbound-manager select choose --candidates state_data/passed_candidates.json --candidate-index 0 --output state_data/selected_candidate.json
scholar-outbound-manager sidecar service-stage --config config.yaml --selected-candidate state_data/selected_candidate.json
scholar-outbound-manager sidecar service-install --unit-name scholar-outbound-sidecar.service
scholar-outbound-manager sidecar service-start --unit-name scholar-outbound-sidecar.service
scholar-outbound-manager sidecar service-snippet --listen-host 127.0.0.1 --listen-port 19080 --tag scholar-sidecar-socks-out
```

Before a VPS probe:

- Do not block on `pgrep xray` globally.
- Check only project-owned pid files under `.runtime/`.
- External `/usr/local/x-ui` Xray may coexist.

After a VPS probe:

- Confirm no project-managed pid file remains alive.
- Ignore unrelated external Xray processes.

## Sidecar SOCKS Runtime Model

- ScholarOutboundManager does not modify production Xray or XrayR configuration.
- It can run an isolated runtime Xray sidecar.
- The sidecar exposes a localhost SOCKS endpoint such as `127.0.0.1:19080`.
- Production Xray or XrayR may manually use a SOCKS outbound pointing to that localhost port.
- This keeps production routing and user management isolated from ScholarOutboundManager.
- ScholarOutboundManager only manages the Xray process it starts and records in its PID file.
- It never kills Xray by process name.
- It never kills `x-ui` or external Xray or XrayR services.

Start a sidecar from a selected passed candidate:

```bash
scholar-outbound-manager sidecar start \
  --config config.yaml \
  --selected-candidate state_data/selected_candidate.json \
  --listen-host 127.0.0.1 \
  --listen-port 19080
```

Generate a production-reference SOCKS outbound snippet:

```bash
scholar-outbound-manager sidecar snippet \
  --listen-host 127.0.0.1 \
  --listen-port 19080 \
  --tag scholar-sidecar-socks-out
```

Example snippet:

```json
{
  "tag": "scholar-sidecar-socks-out",
  "protocol": "socks",
  "settings": {
    "servers": [
      {
        "address": "127.0.0.1",
        "port": 19080
      }
    ]
  }
}
```

- This snippet is not automatically written to production config.
- Users must integrate it manually or through their own deployment tooling.
- This phase does not install a systemd service.
- This phase does not implement auto failover.

## Production systemd sidecar

- For long-running production use, prefer `systemd` over PID-file manual mode.
- `systemd` manages restart policy, boot startup, logs, and lifecycle.
- ScholarOutboundManager stages sidecar runtime files for a dedicated user.
- It does not modify production Xray, XrayR, or `x-ui` configuration.
- It does not kill external Xray processes.
- It does not use Docker by default.
- The default multi-node expansion direction is one Xray process with multiple localhost SOCKS ports, not one systemd instance per node.

Example production flow:

1. Probe and keep passed candidates:

```bash
scholar-outbound-manager probe \
  --config config.yaml \
  --candidates candidates.json \
  --summary-output state_data/probe_summary.json \
  --passed-candidates-output state_data/passed_candidates.json \
  --parallel 4 \
  --keep-all-passed \
  --allow-network-probe
```

Use a conservative worker count such as `2` to `4` first. Each worker starts its own managed Xray runtime, and `--keep-all-passed` preserves every candidate that passes Scholar home and query classification before you choose a sidecar candidate.

2. Stage production sidecar files:

```bash
scholar-outbound-manager sidecar service-stage \
  --config config.yaml \
  --selected-candidate state_data/selected_candidate.json \
  --listen-host 127.0.0.1 \
  --listen-port 19080
```

3. Install the `systemd` unit:

```bash
scholar-outbound-manager sidecar service-install \
  --unit-name scholar-outbound-sidecar.service
```

4. Start and enable it:

```bash
scholar-outbound-manager sidecar service-start \
  --unit-name scholar-outbound-sidecar.service

scholar-outbound-manager sidecar service-enable \
  --unit-name scholar-outbound-sidecar.service
```

5. Print a production Xray or XrayR SOCKS outbound snippet:

```bash
scholar-outbound-manager sidecar service-snippet \
  --listen-host 127.0.0.1 \
  --listen-port 19080 \
  --tag scholar-sidecar-socks-out
```

- `service-stage` and `service-install` often require root.
- The generated runtime config is sensitive.
- The `systemd` unit itself should not contain proxy credentials.
- Production Xray or XrayR integration remains manual.
- Docker is not the default lifecycle manager.
- In production, the preferred sequence is: full probe, select a passed candidate, stage the sidecar, install the unit, start the unit, check service status, then manually point production Xray or XrayR at the localhost SOCKS sidecar.

## Single-Xray multi-port sidecar pool

- Multi-node expansion does not require multiple Xray processes by default.
- One sidecar Xray can expose multiple localhost SOCKS ports.
- Each port maps to one passed candidate outbound.
- Port availability must be checked before staging.
- This reduces process overhead compared with `systemd` instance-per-node.
- Multi-instance mode is not the default.
- Production Xray or XrayR integration remains manual.
- The pool runtime config is sensitive and must not be pasted publicly.

Example pool flow:

```bash
scholar-outbound-manager sidecar pool plan \
  --candidates state_data/passed_candidates.json \
  --max-count 4 \
  --base-port 19080 \
  --output state_data/sidecar_pool_plan.json

scholar-outbound-manager sidecar pool check-ports \
  --plan state_data/sidecar_pool_plan.json

scholar-outbound-manager sidecar service-stop \
  --unit-name scholar-outbound-sidecar.service

scholar-outbound-manager sidecar pool stage \
  --config config.yaml \
  --candidates state_data/passed_candidates.json \
  --plan state_data/sidecar_pool_plan.json \
  --source-xray-binary .runtime/xray/xray

scholar-outbound-manager sidecar service-start \
  --unit-name scholar-outbound-sidecar.service

scholar-outbound-manager sidecar pool validate \
  --plan state_data/sidecar_pool_plan.json

scholar-outbound-manager sidecar pool snippets \
  --plan state_data/sidecar_pool_plan.json
```

If the current single-node service already owns `127.0.0.1:19080`, stop it first or choose a different base port such as `19180`.

## Geo-aware selection

- Selection priority is:
  1. user-specified candidate
  2. geo-nearest candidate from local cache
  3. first available fallback
- Geo DB, host geo cache, and candidate geo cache are separate layers.
- Geo DB is local reference data for future lookups. The current core does not parse it.
- Host geo cache describes the VPS or host location, for example `state_data/geo/host_geo.json`.
- Candidate geo cache stores `candidate_id` keyed cached geo metadata, for example `state_data/geo/candidate_geo_cache.json`.
- Geo-aware ranking uses cached local data by default.
- Select never performs network lookup.
- Select never downloads a Geo DB.
- Candidate server address does not necessarily equal the true egress IP.
- If a cache entry was derived only from server endpoint GeoIP, treat it as an endpoint geo heuristic.
- More accurate egress geo requires the node to reach an IP echo service, which is a network action.
- Endpoint geo and egress geo are different:
  - endpoint geo: candidate server endpoint heuristic
  - egress geo: actual exit IP via node, which requires an explicit future network lookup
- Networking-based egress IP lookup is a future or backup path and must remain explicit opt-in.
- Phase 23A only implements cached geo ranking. It does not do live egress IP lookup.
- Phase 23C adds `geo refresh-plan`, but it is dry-run only in this phase.
- Geo ranking is a sorting heuristic only. It does not determine Scholar availability.
- Selection can infer passed status from Scholar home/query evidence for older passed-candidates artifacts that do not contain an explicit passed flag.
- Raw egress IP values should not be stored by default. If stored metadata is needed, prefer a hash such as `sha256:...`.
- `candidate_geo_cache.json` should remain local and should not be committed.
- The core project does not currently depend on `maxminddb`. If MMDB lookup is added later, it should live behind a dedicated extra such as `geo`.

Example:

```bash
scholar-outbound-manager select choose \
  --candidates state_data/passed_candidates.json \
  --strategy auto \
  --host-geo state_data/geo/host_geo.json \
  --geo-cache state_data/geo/candidate_geo_cache.json \
  --output state_data/selected_candidate.json
```

Use `select explain` when you want a redacted explanation of why one candidate was selected.

Local Geo inspection and dry-run planning:

```bash
scholar-outbound-manager geo db-info \
  --geo-db state_data/geo/db/GeoLite2-City.mmdb

scholar-outbound-manager geo cache-inspect \
  --geo-cache state_data/geo/candidate_geo_cache.json

scholar-outbound-manager geo refresh-plan \
  --candidates state_data/passed_candidates.json \
  --geo-cache state_data/geo/candidate_geo_cache.json
```

## Optional TUI

- Install with:
  `pip install "ScholarOutboundManager[tui]"`
- Run with:
  `scholar-outbound-manager-tui --candidates state_data/passed_candidates.json`
- The TUI uses the redacted candidate catalog and selection helpers.
- The TUI does not display proxy secrets.
- The TUI does not mutate production Xray, XrayR, or `x-ui`.
- The first version is a selection and control surface, not daemon automation.

## Production operations

Validate the deployed sidecar without printing runtime config content:

```bash
scholar-outbound-manager sidecar service-status \
  --unit-name scholar-outbound-sidecar.service

scholar-outbound-manager sidecar service-validate \
  --unit-name scholar-outbound-sidecar.service \
  --listen-host 127.0.0.1 \
  --listen-port 19080

systemctl is-active scholar-outbound-sidecar.service
systemctl is-enabled scholar-outbound-sidecar.service
```

Rollback or stop the sidecar without touching external Xray services:

```bash
scholar-outbound-manager sidecar service-stop \
  --unit-name scholar-outbound-sidecar.service

scholar-outbound-manager sidecar service-disable \
  --unit-name scholar-outbound-sidecar.service
```

Do not print `/etc/scholar-outbound-manager/scholar_sidecar_runtime.json`.
Do not use `killall xray`.
Do not use `pkill xray`.
Do not modify production Xray, XrayR, or `x-ui` from this project.

## Typical Workflow

### Step 1: prepare local config

```bash
cp config.example.yaml config.yaml
```

Enable network probing only in your local `config.yaml`:

```yaml
probe:
  allow_network_probe: true
```

Only enable this in local `config.yaml`. Do not change shared examples to real credentials. Do not commit `config.yaml`.

### Step 2: prepare local candidates JSON

Option A: fetch candidates from enabled subscriptions.

```bash
scholar-outbound-manager fetch \
  --config config.yaml \
  --output candidates.json \
  --allow-network-fetch \
  --user-agent "Clash.Meta"
```

`fetch` may download subscription content. `--allow-network-fetch` is required. `--user-agent` is optional and is useful when the subscription endpoint applies User-Agent filtering. `candidates.json` is sensitive and must not be committed. `fetch` does not probe Scholar and does not start Xray.

Option B: use an existing offline `candidates.json` artifact.

Prepare an offline `candidates.json` file from the Phase 2 parser output or from your own offline export. Do not use real proxy material in examples or shared documents.

### Step 3: probe candidates

```bash
scholar-outbound-manager probe \
  --config config.yaml \
  --candidates candidates.json \
  --summary-output state_data/probe_summary.json \
  --passed-candidates-output state_data/passed_candidates.json \
  --parallel 4 \
  --keep-all-passed \
  --query ppr \
  --allow-network-probe
```

For VPS full probes, prefer `--parallel` with a conservative value such as `2` to `4`. Each worker starts its own managed Xray runtime, and `--keep-all-passed` keeps every passed candidate in the sensitive artifact for later sidecar selection. External Xray or `x-ui` processes are not managed by this project.

### Step 4: inspect probe result

```bash
scholar-outbound-manager inspect \
  --probe-summary state_data/probe_summary.json \
  --passed-candidates state_data/passed_candidates.json
```

### Step 5: start an isolated sidecar manually for smoke or local validation

```bash
scholar-outbound-manager select list \
  --candidates state_data/passed_candidates.json

scholar-outbound-manager select choose \
  --candidates state_data/passed_candidates.json \
  --candidate-index 0 \
  --output state_data/selected_candidate.json

scholar-outbound-manager select explain \
  --candidates state_data/passed_candidates.json \
  --host-geo state_data/geo/host_geo.json \
  --geo-cache state_data/geo/candidate_geo_cache.json

scholar-outbound-manager sidecar start \
  --config config.yaml \
  --selected-candidate state_data/selected_candidate.json \
  --listen-host 127.0.0.1 \
  --listen-port 19080
```

`select list` prints redacted human-readable labels by default. Labels are derived from subscription node names and source labels, are for human review only, and continue to hide raw URIs, UUIDs, public keys, passwords, tokens, addresses, and other secrets. Region hints are heuristic and are not a substitute for GeoIP cache or egress verification. Use `candidate_id` for stable selection.

Example:

```bash
scholar-outbound-manager select list \
  --candidates state_data/passed_candidates.json
```

Example output:

```text
index  candidate_id   protocol  label      region  passed  stage
0      candidate-001  vless     US-LA-01   US-LA   yes     full_access
```

Use `--no-label` if you want the older compact table. `select explain` includes the same redacted label and region hint in its JSON catalog.

### Step 6: stage production sidecar files

```bash
scholar-outbound-manager sidecar service-stage \
  --config config.yaml \
  --selected-candidate state_data/selected_candidate.json \
  --listen-host 127.0.0.1 \
  --listen-port 19080
```

### Step 7: install and start the production sidecar unit

```bash
scholar-outbound-manager sidecar service-install \
  --unit-name scholar-outbound-sidecar.service

scholar-outbound-manager sidecar service-start \
  --unit-name scholar-outbound-sidecar.service

scholar-outbound-manager sidecar service-enable \
  --unit-name scholar-outbound-sidecar.service
```

### Step 8: print the downstream production SOCKS outbound snippet

```bash
scholar-outbound-manager sidecar service-snippet \
  --listen-host 127.0.0.1 \
  --listen-port 19080 \
  --tag scholar-sidecar-socks-out
```

Production Xray or XrayR integration remains a manual downstream step that points to the localhost SOCKS sidecar. ScholarOutboundManager does not mutate production Xray, XrayR, or `x-ui` configuration.

Optional terminal UI:

```bash
pip install "ScholarOutboundManager[tui]"
scholar-outbound-manager-tui \
  --candidates state_data/passed_candidates.json \
  --output state_data/selected_candidate.json
```

The optional TUI shows the same redacted label and heuristic region columns without exposing proxy credentials.

## Legacy Offline Fragment Export

`generate` is retained for legacy offline export, debugging, and advanced tooling. It does not modify production configuration and is not the recommended production workflow.

### Legacy step: export offline Xray fragments

```bash
scholar-outbound-manager generate \
  --config config.yaml \
  --candidates state_data/passed_candidates.json
```

### Legacy step: inspect generated manifest

```bash
scholar-outbound-manager inspect \
  --manifest generated/google_scholar_manifest.json
```

### Legacy step: prepare one runtime config and optionally test it

```bash
scholar-outbound-manager run \
  --config config.yaml \
  --candidates state_data/passed_candidates.json \
  --candidate-index 0 \
  --test-config
```

## CLI Reference

### `generate`

Purpose: export legacy offline Xray outbounds, routes, and manifest JSON for debugging or advanced downstream tooling.

Required arguments:

- `--config`
- `--candidates`

Notes:

- `generate` can consume plain candidates JSON.
- `generate` can also consume sensitive passed-candidates artifacts.
- When probe evidence is present, the generated manifest preserves redacted probe evidence.
- `generate` applies configured candidate filters before export.
- `generate` does not modify production Xray, XrayR, or `x-ui` configuration.
- `generate` does not reload production services.
- For production use, prefer the sidecar service workflow.

Output files:

- outbounds JSON
- routes JSON
- generated manifest JSON

Exit codes:

- `0`: generation succeeded
- `1`: config, input, validation, or write error

### `probe`

Purpose: sequentially probe offline candidates, write a redacted review-safe summary, and write a sensitive passed-candidates artifact for later sidecar selection or legacy offline export.

Important arguments:

- `--config`
- `--candidates`
- `--summary-output`
- `--passed-candidates-output`
- `--max-candidates`
- `--max-passed`
- `--include-unsupported`
- `--query`
- `--skip-query`
- `--startup-timeout`
- `--request-timeout`
- `--xray-test-timeout`
- `--runtime-config-name`
- `--allow-network-probe`

Safety:

- `--allow-network-probe` is required together with `probe.allow_network_probe: true`.
- This command may start local Xray and issue Scholar HTTP requests only after both are enabled.
- A passed candidate requires both `https://scholar.google.com/` and the reference query path to pass.
- `home blocked` means the Scholar home page is denied.
- `query blocked` means the home page responds, but the reference query path is denied.

Output files:

- redacted probe summary JSON
- sensitive passed-candidates JSON

Exit codes:

- `0`: probe completed and at least one candidate passed
- `1`: config, input, validation, probe, write error, or safety-gate refusal
- `2`: probe completed but no candidate passed

## Real probe environment

- A MacBook running `mihomo` or another TUN-based client is not a trustworthy final Scholar probe environment.
- Use the MacBook for development, fetch, parse, inspect, and artifact review.
- Use the target VPS for final probe and generate decisions.
- TUN routing can contaminate the effective Xray outbound path even when the local workflow looks correct.
- The `environment` command only provides a local hint. It cannot prove routing isolation.
- Final confidence comes from running `probe` on the target VPS.

## Live A/B Fetch Smoke Test

Use the local harness when you need to compare a known-valid subscription set against a known-invalid set without printing subscription URLs or proxy credentials.

```bash
python scripts/live_ab_fetch_test.py \
  --valid-links live_test_data/sublinks/valid.txt \
  --invalid-links live_test_data/sublinks/invalid.txt \
  --work-dir state_data/live_ab/ \
  --xray-binary fake-xray \
  --user-agent "Clash.Meta"
```

Optional transport proxy:

```bash
python scripts/live_ab_fetch_test.py \
  --valid-links live_test_data/sublinks/valid.txt \
  --invalid-links live_test_data/sublinks/invalid.txt \
  --work-dir state_data/live_ab/ \
  --xray-binary fake-xray \
  --user-agent "Clash.Meta" \
  --proxy-url http://127.0.0.1:7890
```

The live A/B fetch smoke test downloads subscription content, parses candidates, writes only local sensitive artifacts under `state_data/live_ab/`, and does not probe Scholar.

### `inspect`

Purpose: safely review redacted probe summaries, generated manifests, and metadata from sensitive passed-candidate artifacts.

Important arguments:

- `--probe-summary`
- `--manifest`
- `--passed-candidates`

Guarantees:

- `inspect` may show redacted generated probe evidence from manifest.
- `inspect` does not print sensitive candidate credentials.

Exit codes:

- `0`: inspection succeeded
- `1`: input, JSON, or schema error

### `environment`

Purpose: report local-only environment hints that affect how trustworthy live probe results are.

Notes:

- `environment` does not access the network.
- `environment` does not start Xray.
- It only reports local hints such as proxy environment variables and the current platform.
- On macOS, it should be treated as a development-only warning surface rather than proof of routing isolation.

### `run`

Purpose: prepare one local runtime config from a selected candidate and optionally validate it with `xray run -test`.

Notes:

- `run` prepares runtime config only.
- `--test-config` is optional.
- `run` does not live-probe Google Scholar.

Exit codes:

- `0`: runtime preparation succeeded, and optional config test passed
- `1`: config, input, validation, runtime preparation, or config test failure

### `fetch`

Purpose: download enabled subscriptions, decode subscription text, parse proxy candidates, and write a sensitive local candidate artifact.

Important arguments:

- `--config`
- `--output`
- `--allow-network-fetch`
- `--proxy-url`
- `--timeout`
- `--max-bytes`

Notes:

- `fetch` only starts after `--allow-network-fetch` is passed.
- `--proxy-url` is optional and can route subscription downloads through an HTTP(S) proxy.
- `fetch` may download subscription content and write raw candidate material locally.
- `fetch` does not start Xray.
- `fetch` does not probe Google Scholar.

Output files:

- sensitive candidate artifact JSON

Exit codes:

- `0`: subscription content was fetched and at least one candidate was parsed
- `1`: config, input, validation, fetch, parse, or write error
- `2`: fetch completed but no enabled source was fetched or no candidate was parsed

## Live A/B fetch smoke test

You can keep real subscription links in ignored local files such as `live_test_data/sublinks/valid.txt` and `live_test_data/sublinks/invalid.txt`, then run:

```bash
python scripts/live_ab_fetch_test.py \
  --valid-links live_test_data/sublinks/valid.txt \
  --invalid-links live_test_data/sublinks/invalid.txt \
  --work-dir state_data/live_ab \
  --xray-binary fake-xray
```

This smoke test only exercises fetch/parse behavior. It does not probe Scholar, does not start Xray, and writes local output under `state_data/live_ab/`. Do not commit `live_test_data/` or `state_data/live_ab/`.

If the valid group shows `dns_error`, the current environment may not be able to resolve the subscription host directly. In that case you can optionally route fetch through a local HTTP(S) proxy:

```bash
python scripts/live_ab_fetch_test.py \
  --valid-links live_test_data/sublinks/valid.txt \
  --invalid-links live_test_data/sublinks/invalid.txt \
  --work-dir state_data/live_ab \
  --xray-binary fake-xray \
  --proxy-url http://127.0.0.1:7890
```

`--proxy-url` is optional. Do not commit a proxy URL, and the script does not print the proxy URL. This still only tests subscription fetch/parse, not Scholar probe.

The redacted summary now includes fetch error categories and HTTP status counts when available. A valid group with `fetched_count=0` means fetch failed before parsing. A valid group with `fetched_count>0` and `parsed_count=0` points to a parser or content-format issue.

## Artifact Table

| Path | Produced by | Sensitivity | Purpose | Commit? |
| --- | --- | --- | --- | --- |
| `config.yaml` | user | sensitive | local configuration | no |
| `candidates.json` | `fetch`, user, or offline parser | sensitive | downloaded subscription candidate input with raw candidate material | no |
| `state_data/probe_summary.json` | `probe` | review-safe | redacted probe report | no |
| `state_data/passed_candidates.json` | `probe` | sensitive | passed proxy credentials and optional `ProbeResult` evidence for sidecar selection or legacy offline export | no |
| `generated/google_scholar_outbounds.json` | `generate` | local generated | Xray outbound fragments | no |
| `generated/google_scholar_routes.json` | `generate` | local generated | Xray route fragments | no |
| `generated/google_scholar_manifest.json` | `generate` | review-safe | generated manifest for inspection, including redacted probe evidence when available | no |
| `.runtime/` | `run` and probe runtime prep | sensitive | local runtime configs and temporary execution material | no |
| `state_data/history/` | local workflow | local generated | retained local history artifacts | no |

## Exit Codes

- `0`: success
- `1`: command, config, input, validation, write, runtime, or safety-gate error
- `2`: no passed candidate for `probe`, or fetch completed without any fetched subscription candidates

## Development Notes

- Tests use fake binaries and local fake servers.
- The full test suite may require loopback port binding.
- No real Xray binary is required for most tests.
- No real proxy credentials should be committed.
