# ScholarOutboundManager

ScholarOutboundManager is a staged, fail-closed Google Scholar outbound manager for offline candidate review, sequential probing, safe inspection, JSON fragment generation, and local runtime preparation.

## Project Status

- `fetch` is still not implemented.
- Current inputs come from a local `candidates.json` file, not from live subscription fetching.
- `probe` is protected by a two-key network safety gate.
- `probe.allow_network_probe` must be `true` in config.
- `--allow-network-probe` must also be passed on the CLI.
- Without both, `probe` fails before starting Xray or sending Scholar HTTP requests.
- `probe` runs sequentially.
- There is no concurrency.
- There is no retry or cache layer in the current CLI workflow.
- `probe` and `generate` apply configured candidate filters before probing or generation.
- Passed-candidates artifacts may preserve `ProbeResult` evidence for later manifest generation.
- `generate` only writes JSON artifacts and does not start Xray.
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
- `config.yaml`
- Runtime configs under `.runtime/`
- Any file containing proxy URI, UUID, public key, token, or subscription material

`passed_candidates.json` contains selected proxy credentials. It may also contain `ProbeResult` evidence used later by `generate`. It must not be committed.

`config.yaml` must not be committed.

`state_data/` and `generated/` should remain local.

`inspect` never prints selected proxy credentials from sensitive artifacts.

### Generated Xray artifacts

- Generated outbounds JSON
- Generated routes JSON
- Generated manifest JSON

These artifacts are produced locally from offline candidate input and are meant for controlled downstream use.

### Network probe safety gate

Network probing is opt-in at both config and CLI layers.

- The config default should remain `allow_network_probe: false`.
- Users should only enable it in a local, ignored `config.yaml`.
- The CLI flag is an intentional second confirmation.

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

Prepare an offline `candidates.json` file from the Phase 2 parser output or from your own offline export. Do not use real proxy material in examples or shared documents.

### Step 3: probe candidates

```bash
scholar-outbound-manager probe \
  --config config.yaml \
  --candidates candidates.json \
  --summary-output state_data/probe_summary.json \
  --passed-candidates-output state_data/passed_candidates.json \
  --allow-network-probe
```

### Step 4: inspect probe result

```bash
scholar-outbound-manager inspect \
  --probe-summary state_data/probe_summary.json \
  --passed-candidates state_data/passed_candidates.json
```

### Step 5: generate Xray fragments from passed candidates

```bash
scholar-outbound-manager generate \
  --config config.yaml \
  --candidates state_data/passed_candidates.json
```

### Step 6: inspect generated manifest

```bash
scholar-outbound-manager inspect \
  --manifest generated/google_scholar_manifest.json
```

### Step 7: prepare one runtime config and optionally test it

```bash
scholar-outbound-manager run \
  --config config.yaml \
  --candidates state_data/passed_candidates.json \
  --candidate-index 0 \
  --test-config
```

## CLI Reference

### `generate`

Purpose: convert offline candidates into Xray outbounds, routes, and manifest JSON.

Required arguments:

- `--config`
- `--candidates`

Notes:

- `generate` can consume plain candidates JSON.
- `generate` can also consume sensitive passed-candidates artifacts.
- When probe evidence is present, the generated manifest preserves redacted probe evidence.
- `generate` applies configured candidate filters before generation.

Output files:

- outbounds JSON
- routes JSON
- generated manifest JSON

Exit codes:

- `0`: generation succeeded
- `1`: config, input, validation, or write error

### `probe`

Purpose: sequentially probe offline candidates, write a redacted review-safe summary, and write a sensitive passed-candidates artifact for later generation.

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

Output files:

- redacted probe summary JSON
- sensitive passed-candidates JSON

Exit codes:

- `0`: probe completed and at least one candidate passed
- `1`: config, input, validation, probe, write error, or safety-gate refusal
- `2`: probe completed but no candidate passed

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

Purpose: currently not implemented.

Exit codes:

- `2`: placeholder command state

## Artifact Table

| Path | Produced by | Sensitivity | Purpose | Commit? |
| --- | --- | --- | --- | --- |
| `config.yaml` | user | sensitive | local configuration | no |
| `candidates.json` | user or offline parser | sensitive | offline candidate input | no |
| `state_data/probe_summary.json` | `probe` | review-safe | redacted probe report | no |
| `state_data/passed_candidates.json` | `probe` | sensitive | selected proxy credentials and optional `ProbeResult` evidence for later `generate` | no |
| `generated/google_scholar_outbounds.json` | `generate` | local generated | Xray outbound fragments | no |
| `generated/google_scholar_routes.json` | `generate` | local generated | Xray route fragments | no |
| `generated/google_scholar_manifest.json` | `generate` | review-safe | generated manifest for inspection, including redacted probe evidence when available | no |
| `.runtime/` | `run` and probe runtime prep | sensitive | local runtime configs and temporary execution material | no |
| `state_data/history/` | local workflow | local generated | retained local history artifacts | no |

## Exit Codes

- `0`: success
- `1`: command, config, input, validation, write, runtime, or safety-gate error
- `2`: no passed candidate for `probe`, or placeholder/unimplemented command such as `fetch`

## Development Notes

- Tests use fake binaries and local fake servers.
- The full test suite may require loopback port binding.
- No real Xray binary is required for most tests.
- No real proxy credentials should be committed.
