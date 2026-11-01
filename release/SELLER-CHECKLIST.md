# Homeboard release checklist

Homeboard is public and free under MIT, approved by the owner. The current deliverable is an unsigned community preview. Mark a gate complete only with actual evidence for the shipping build.

## Product and ownership

- [ ] Confirm the selling format, price, supported countries, refund policy and what installation/support includes.
- [ ] Confirm the Homeboard name, domain, logo and descriptions can be used; there is no trademark clearance in this repository.
- [x] Owner approved public source and free MIT licensing. Dependencies keep their own licenses. Commercial support terms are not supplied.
- [ ] Resolve the intended scope of the parent repository license and complete the dependency/asset notice audit for the exact shipped runtime.

## Security and distribution

- [ ] Replace or professionally review the stdlib HTTP serving design; trusted HTTPS and a reverse proxy alone are not evidence of a completed audit.
- [ ] Review authentication, setup claiming, recovery codes, session revocation, CSRF, display filtering and authorization with independent security testing.
- [ ] Sign the application and installer with the real publisher's certificate, timestamp signatures and verify them. Do not invent a publisher or disable SmartScreen/antivirus.
- [ ] Pin build tools/base images, produce a runtime SBOM, scan dependencies and establish update ownership and a vulnerability-reporting channel.
- [ ] Test the actual downloadable artifact and its SHA-256 manifest after upload. Protect signing credentials; the application source is intentionally public.

## Buyer experience

- [ ] On a clean supported Windows PC, double-click install with no Python/Docker dependency; finish onboarding without a terminal.
- [ ] Validate first launch, duplicate launch, logon startup, graceful stop, port conflict, restart, sleep/wake, upgrade and uninstall/reinstall.
- [ ] Test installation and data paths containing spaces and non-Latin characters; test a standard non-admin Windows account.
- [ ] Check setup/recovery with bad inputs, simultaneous first-run attempts, network interruption and browser refresh; no partial owner state or plaintext secrets in logs/packages.
- [ ] Verify Windows private-network firewall instructions and trusted HTTPS from both Android and iPhone, using the supported network setup.
- [ ] Publish a tested TV/browser list. Do not advertise every smart TV as compatible.
- [ ] Verify readability at the intended display size and distance; keep the large clock and simple editing controls.
- [ ] Run a multi-day household pilot with several devices, simultaneous edits, LAN-only outage, reconnect and backup restoration.

## Lifecycle and support

- [ ] Test recovery from a copied snapshot on a separate machine; verify owner access and recurring events.
- [ ] Test each promised upgrade path; preserve data by default and retain rollback artifacts.
- [ ] Provide versioned buyer instructions, known limitations, support contact, recovery instructions and an update policy.
- [ ] Clearly state the PC must remain powered, awake and signed in for this per-user background edition. If selling an always-on appliance, validate its different startup and power behavior separately.
- [x] Owner explicitly approved making the repository public under MIT. Do not represent preview builds as certified or invent commercial support commitments.
