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

These files can contain proxy URI, UUID, public key, token, runtime config, or other credential-bearing data. They must not be committed.

## Redacted vs Sensitive Artifacts

- Redacted probe summary is for review.
- Sensitive passed-candidates artifact is for `generate`.
- `inspect` only shows metadata for sensitive artifacts.

The redacted probe summary is intended for safe sharing inside reviews. The passed-candidates artifact intentionally preserves selected proxy credentials for later offline generation and must remain local.

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

## Safe Debugging Checklist

Prefer sharing only:

- command used
- exit code
- redacted `inspect` output
- failure markers
- file paths, with usernames removed if desired

## Recovery and Cleanup

If you want to remove local workflow artifacts, examples include:

```bash
rm -rf .runtime generated state_data
rm -f config.yaml candidates.json
```

These are cleanup examples only. They are not required for normal use.
