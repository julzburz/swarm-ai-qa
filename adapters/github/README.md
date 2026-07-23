# GitHub read-only adapter

The adapter uses only GitHub REST `GET` endpoints to read repository metadata, the default
branch commit, a bounded recursive tree, selected manifests and optional pull-request files.

Safety limits:

- 15 second request timeout by default;
- two retries for network errors, rate limiting and transient 5xx responses;
- at most 32 captured manifest/configuration files;
- at most 128 KiB per captured file;
- at most 10 pages (1000 files) from a pull-request file list;
- no redirects and no mutation methods;
- public repositories are always read without the server token;
- private repositories require `GITHUB_TOKEN` with `Contents: read`;
- every private repository must also appear in the comma-separated
  `SWARM_GITHUB_ALLOWED_PRIVATE_REPOSITORIES` allowlist using its canonical
  `github:OWNER/REPO` identifier.

Large binaries and arbitrary source files are not downloaded. Source-language detection uses
tree paths; framework and command claims require captured manifest evidence.
