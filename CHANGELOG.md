# Homeboard changes

## 0.2.0-rc.1 — release candidate

- Guided first-time household setup, neutral defaults and owner access recovery.
- Windows desktop launcher and a per-user installer build. Python and Docker are not required on the buyer's PC when using the bundled Windows edition.
- Data and backups are stored outside the installation folder and retained during application updates and ordinary uninstall.
- Customer packaging includes a version and SHA-256 inventory; runtime databases, setup codes, recovery secrets and personal deployment configuration are excluded.
- Calendar recurrence can select weekdays; editing actions and clock/date labels are distinct.

This candidate is not code signed. Public-sale gates, including independent security review, clean-machine testing, seller-approved terms and brand clearance, are documented in `release/SELLER-CHECKLIST.md`.
