# Security Notes

## Sensitive Files

Treat the following as local sensitive material:

- `config.yaml`
- `candidates.json`
- `state_data/passed_candidates.json`
- `state_data/`
- `generated/`
- `.runtime/`
- `.env`
- logs containing proxy material
- `/etc/scholar-outbound-manager/`

These files can contain proxy URI, UUID, public key, token, runtime config, or other credential-bearing data. They must not be committed.

## Redacted vs Sensitive Artifacts

- Redacted probe summary is for review.
- Sensitive passed-candidates artifact is for sidecar selection or legacy offline export.
- `inspect` only shows metadata for sensitive artifacts.

The redacted probe summary is intended for safe sharing inside reviews. The passed-candidates artifact intentionally preserves selected proxy credentials for later sidecar selection or legacy offline generation and must remain local.

`passed_candidates.json` may contain nested candidate credentials and probe evidence. It remains sensitive even if probe evidence is useful for debugging. It must not be committed.

If produced, generated Xray fragments are legacy offline exports and may also contain real node credentials. They must remain local.

Sidecar runtime configs are sensitive. Do not paste `.runtime/` sidecar configs or production-staged runtime configs under `/etc/scholar-outbound-manager/`.

## Network Probe Safety Gate

Real probing is disabled by default.

- `probe.allow_network_probe: false` is the safe default.
- To run live network probing, the user must set `probe.allow_network_probe: true` in local config and pass `--allow-network-probe`.
- This two-key gate prevents accidental Xray startup and accidental Google Scholar HTTP requests.
- Do not enable it in committed examples.
- Do not paste live probe logs containing credentials or real endpoints.

## What Not to Paste Into Issues

Do not paste any of the following into issues, pull requests, chats, or screenshots:

- full `vless://` URI
- UUID
- public key
- short id if tied to a real node
- subscription URL
- `config.yaml`
- `passed_candidates.json`
- generated outbounds containing real nodes
- generated routes containing real nodes
- generated manifests if they carry real credential-bearing fragments
- sidecar runtime config
- `/etc/scholar-outbound-manager/scholar_sidecar_runtime.json`

## Safe Debugging Checklist

Prefer sharing only:

- command used
- exit code
- redacted `inspect` output
- failure markers
- file paths, with usernames removed if desired

Production Xray, XrayR, and `x-ui` configuration is not managed by this project. The production integration model is a manual downstream SOCKS outbound that points at the Scholar sidecar. The `systemd` unit itself should not contain proxy credentials.

## Recovery and Cleanup

If you want to remove local workflow artifacts, examples include:

```bash
rm -rf .runtime generated state_data
rm -f config.yaml candidates.json
```

These are cleanup examples only. They are not required for normal use.
