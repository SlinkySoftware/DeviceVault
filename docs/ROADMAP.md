# DeviceVault — Product Roadmap

Status: **Proposal** (2026-10-24). Nothing here is committed work until it is given a phase in
[ARCHITECTURE.md](ARCHITECTURE.md) section 10. This document is the idea backlog: what an enterprise
network team, its security team and its auditors would plausibly ask for, ranked by value for effort.

## 1. Where DeviceVault stands

Phases 0-13 give DeviceVault the hard parts of an enterprise backup system:

- **Collection**: scheduled and on-demand polling over SSH (Cisco IOS, MikroTik), plus device-initiated
  push over SCP, SFTP and TFTP.
- **Storage**: pluggable targets (filesystem, git, S3, PostgreSQL), assigned per target to specific workers.
- **Security**: signed orchestrator-to-worker messages, per-recipient sealed credentials, optional
  end-to-end backup encryption to a vault key, encrypted secrets at rest.
- **Access**: user groups with five-flag device-group grants, LDAP and OIDC, break-glass, server-side
  sessions and an audit log.
- **Operations**: zero-configuration workers with approval, two-node HA, Flower access.

What an enterprise still finds missing is mostly **the layer above the bytes**: knowing *what changed*, *whether it
was supposed to*, *whether it is compliant*, *who must hear about it*, and *how to get a dead device back*. The
data path is strong. The intelligence on top of it is where the value is.

Already planned and not repeated in detail below: Redis Sentinel, further vendor
drivers (ARCHITECTURE.md section 10, "later").

## 2. How to read this

Each item has an **Impact** (what it buys an enterprise) and an **Effort** estimate:

| Effort | Meaning |
|---|---|
| **S** | Days. One app plus a small UI change. No new component or protocol. |
| **M** | One to two weeks. A new model and API surface, a driver, or a worker task. |
| **L** | A full phase (several weeks). New component, new data pipeline or a cross-cutting design. |

Quick wins are ordered by **value ÷ effort**, best first, so reading from the top and stopping is a
sensible strategy. Detailed changes are grouped by theme and ordered by strategic value.

Every item must still follow the repository rules: signed tasks, no Django in workers or receivers, secrets
write-only, permissions stated per view, audit on security-relevant actions, `DV_*` environment variables
only.

---

## 3. Quick wins

Small, self-contained, and each one removes a reason for an evaluator to say "not yet".

| # | Item | Effort | Impact |
|---|---|---|---|
| Q1 | [Retention enforcement](#q1-retention-enforcement) | S-M | **Scheduled: phase 14.** Storage stops growing without bound. |
| Q2 | [Notifications: webhooks and email](#q2-notifications-webhooks-and-email) | S-M | Failures and changes reach people instead of waiting to be noticed. |
| Q3 | [Change summary on every backup](#q3-change-summary-on-every-backup) | S | **Scheduled: phase 15.** "What changed?" answered at a glance, with added/removed line counts. |
| Q4 | [Zabbix and Prometheus monitoring](#monitoring-integration-zabbix-and-prometheus) | S-M | Backup times, success/failure counts and ratios in the monitoring stack you already run, with ready-made Zabbix templates. |
| Q5 | [Stale and missing backup detection](#q5-stale-and-missing-backup-detection) | S | The classic silent failure: a device that stopped backing up weeks ago. |
| Q6 | [Config search](#q6-config-search) | S-M | "Which devices still have SNMP community `public`?" in seconds. |
| Q7 | [Bulk device import and export](#q7-bulk-device-import-and-export) | S | Onboarding hundreds of devices from a CSV instead of a form. |
| Q8 | [Pin, label and annotate backups](#q8-pin-label-and-annotate-backups) | S | Mark known-good versions, exempt them from retention, record why. |
| Q9 | [Personal API tokens](#q9-personal-api-tokens) | S | Automation and scripting without borrowing a browser session. |
| Q10 | [Audit log export and syslog forwarding](#q10-audit-log-export-and-syslog-forwarding) | S | Satisfies "send it to the SIEM" without a project. |
| Q11 | [Add more built-in vendor drivers](#q11-more-built-in-vendor-drivers) | S each | Each Netmiko-based driver is a few dozen lines; covers a new customer base. |
| Q12 | [Backup verification probes](#q12-backup-verification-probes) | S | Reject empty, truncated or error-page "backups" before they replace a good one. |
| Q13 | [Dashboard upgrades](#q13-dashboard-upgrades) | S | Success-rate trend, oldest backup per group, top failing devices. |
| Q14 | [Scheduled digest report](#q14-scheduled-digest-report) | S | A weekly "state of the estate" email for managers. |

### Q1. Retention enforcement
Scheduled as phase 14 (`feat/retention`); see ARCHITECTURE.md section 10 and decisions 30-31.

### Q2. Notifications: webhooks and email
A `notifications` app: channels (SMTP email, generic signed webhook, Slack/Teams-style incoming webhook),
rules ("a backup in group X failed 3 times", "a config changed on device group Y", "a worker went offline",
"a push was refused"), and per-user subscriptions. Triggered from the same job events that already drive
`BackupJob` state. Webhook URLs and SMTP passwords are write-only secrets. Rate-limit and de-duplicate so a
dead site does not send 400 emails.

### Q3. Change summary on every backup
Scheduled as phase 15 (`feat/change-summary`); see ARCHITECTURE.md section 10 and decision 32. Notifications on
changes (Q2) and change counts in monitoring (Q4) can use `BackupJob.changed`, `lines_added` and `lines_removed`.

### Q4. Monitoring endpoints: Zabbix first, Prometheus second
Enterprises already have a monitoring stack, and meeting them there is worth more than building charts.
Zabbix is the first target; Prometheus comes almost free from the same data. The full design, metric
list and generated templates are in [Monitoring integration](#monitoring-integration-zabbix-and-prometheus)
below, and the larger follow-ups are D30.

### Q5. Stale and missing backup detection
Compute "last successful backup" per device and flag devices that are overdue relative to their schedule
(or, for push devices, the expected push interval). Surface on the dashboard and feed Q2. For push mode
this is the only way to notice a device that quietly stopped sending.

### Q6. Config search
Full-text search over the latest (or all) backups. Without payload encryption the storage layer could index;
with it, the orchestrator is the only place that can decrypt, so the realistic design is an orchestrator-side
index built at `stored` time (PostgreSQL full-text or trigram on the plaintext, held to the same permission
checks as `view_contents`). Make it opt-in because it holds decrypted text in the database, and say so in
the docs. Add saved searches as a seed for the compliance work in D2.

### Q7. Bulk device import and export
CSV/JSON import with a dry-run report (row-by-row errors), and an export of the inventory. Include
device group, collection group, credential reference, schedule and push settings. Idempotent on
`ip_address` (already unique). Audited as a single action.

### Q8. Pin, label and annotate backups
A `pinned` flag, free-text label ("pre-upgrade 17.9", "approved baseline") and note on a backup. Pinned
backups are exempt from retention (Q1): the `BackupJob.pinned` flag and its handling already exist (phase 14),
so Q8 adds the API and UI to set it, the label and note, and auditing. Needs only the `view_contents`-level permission plus `admin` to pin.

### Q9. Personal API tokens
Scoped, expiring, revocable tokens for scripts and CI, hashed at rest, shown once, audited on use, and
subject to exactly the same grants as the owning user (no privilege escalation). Needed for anything in
the integrations theme (D8).

### Q10. Audit log export and syslog forwarding
CSV/JSON export with filters, and an optional forwarder to syslog (RFC 5424, TLS) or a webhook, configured as
`DV_*` variables. A SIEM requirement in most regulated shops. Add a tamper-evidence hash chain here if cheap
(see D15 for the full version).

### Q11. More built-in vendor drivers
`drivers.ssh.NetmikoDriver` makes each of these a small class of device type, commands and volatile-line
regexes. Highest-demand first: Juniper Junos, Arista EOS, Cisco NX-OS, Cisco ASA, Cisco IOS-XE and IOS-XR,
Fortinet FortiOS, Palo Alto PAN-OS, HPE/Aruba (ProCurve and CX), Dell/Force10, Ubiquiti EdgeOS/UniFi,
pfSense/OPNsense (config XML over SSH), F5 BIG-IP (UCS archive, binary), Huawei VRP, Extreme EXOS. Each
ships with a unit test using recorded output and the volatile-line patterns that keep diffs quiet (timestamps,
NTP clocks, "last configuration change" banners).

### Q12. Backup verification probes
Per-driver sanity checks run on the collector before the blob is staged: minimum size, expected
sentinel text (`end` on Cisco, a version banner), absence of error strings ("% Invalid input", "Authorization
failed"). A failing probe marks the job failed with a clear reason instead of silently storing a useless
file as the "latest good" config. Also guards against a truncated SSH session.

### Q13. Dashboard upgrades
Success-rate and duration trend over time, oldest backup per device group, top-N failing devices, push
refusals, storage usage by target, change counts per day. Data already exists; this is a query and chart
exercise in the existing dashboard page.

### Q14. Scheduled digest report
A weekly/daily summary (success rate, failures, devices with no backup, changes, storage growth) rendered
to email or a PDF, per device group and for the whole estate. Built on Q2 delivery and Q13 queries.

### Monitoring integration: Zabbix and Prometheus

This is the design behind Q4. The goal is that a Zabbix administrator can import one template, set two
macros (URL and token) and immediately see backup times, success and failure counts and ratios, stale
devices, and the health of the platform itself, with sensible triggers already attached.

**Approach: a read-only HTTP JSON API plus generated templates.** Zabbix's *HTTP agent* items poll a
URL on an interval and *dependent items* then extract values from that one response with JSONPath, so a
single request per interval feeds dozens of items. This needs no agent on the orchestrator, no
Zabbix-specific code in workers, and nothing outbound from DeviceVault. It lives in the existing
`monitoring` app (which already owns the Flower endpoints), and every number is computed in the
orchestrator from tables it already has (`BackupJob`, workers, push refusals, schedules).

**Endpoints** (under `/api/monitoring/`, JSON, `GET` only):

| Endpoint | Returns | Used by |
|---|---|---|
| `summary/` | Estate-wide metrics (list below) in one object | Master item, dependent items |
| `device-groups/` | One entry per device group with the same job metrics | Low-level discovery (LLD) and per-group items |
| `devices/?group=<id>` | Per-device last-backup facts, paged and filterable | Optional device-level LLD (see scale note) |
| `collectors/`, `storage-targets/`, `receivers/` | Liveness, last seen, queue depth, last write or push, refusals | LLD for platform components |
| `zabbix/template/` | The Zabbix template, generated from the live driver and metric catalogue | Import in Zabbix |
| `metrics` (Q4b) | The same data in Prometheus text format | Prometheus scrape |

**Authentication and permissions.** A dedicated, read-only **monitoring token** (hashed at rest, shown once,
revocable, optional source-address allow-list, every use rate-limited and the creation and revocation
audited). It is a bearer token (`Authorization: Bearer ...`), which Zabbix HTTP agent items support through
the `{$DV.TOKEN}` macro, so no session or CSRF handling is needed. It grants only these endpoints and never any
backup content, credentials or settings. It builds on Q9's token machinery but is its own scope, so a
monitoring system never holds a user's rights. Following the repository rule, each view states its
`permission_classes` (a new `IsMonitoringToken` alongside `IsGlobalAdmin`, added to the test that enforces
the rule), and a global administrator can also call them from the UI session for debugging.

**Metrics.** Anything an operator might graph or alert on, in two flavours: *window gauges* (easy to alert on)
and *monotonic counters* (Zabbix derives rates with a "change per second" preprocessing step and survives
polling gaps).

- **Backup outcomes** (per estate and per device group): jobs started, succeeded, failed, retried, timed
  out, currently running and queued, in the last 1 h, 24 h and 7 d, plus lifetime counters. **Success ratio
  and failure ratio** for each window, and a **failure count by reason** (connection, authentication,
  timeout, verification probe (Q12), storage, hash mismatch).
- **Timing**: backup duration average, median, 95th percentile and maximum per window, split into
  collect time and store time (the pipeline already has separate collected and stored events), queue wait
  before a job starts, and the end-to-end age of the **newest** and **oldest** successful backup.
- **Freshness**: devices whose last success is older than their expected interval (Q5), devices **never**
  backed up, devices **disabled**, devices in **consecutive failure** (1, 3, 5+), and the age in seconds of
  the oldest successful backup per group, which is the single most useful alert in practice.
- **Change** (needs Q3): backups with changes in the window, total lines added and removed, and devices that
  changed more than N times (a flapping config is a signal).
- **Volume**: bytes stored per window and in total, per storage target, backups held, and growth rate,
  so capacity alerts appear before a disk fills.
- **Push** (receivers): files accepted, refused (by reason), bytes received, last push per receiver, and
  devices push-enabled but silent.
- **Platform health**: workers by state (approved and online, offline, pending approval, revoked), heartbeat
  age per worker, applied versus current assignment version (a stuck assignment), queue depth per collection
  group and storage target, whether the **scheduler has a leader** and its lease age, last successful
  scheduler tick, `events` backlog, storage target check result and free space, Redis and RabbitMQ
  reachability from the orchestrator, and key and certificate expiry where known.
- **Self-description**: DeviceVault version, orchestrator count, `payload_encryption` on or off, and the
  server time (so Zabbix can alarm on clock skew between the two).

**Generated templates.** `zabbix/template/` (and a `make` target / `manage.py` command that writes the file
for offline use) emits a Zabbix template in the YAML export format, one file per supported Zabbix LTS (the
format is versioned, so emit the oldest supported and test on the newest). Generating, rather than
hand-writing, keeps the template exactly in step with the metric catalogue and with the drivers a given
installation actually has. Contents:

- **`DeviceVault by HTTP`** — the main template, applied to one Zabbix host that represents the orchestrator
  (no agent needed). Macros: `{$DV.URL}`, `{$DV.TOKEN}` (secret macro), `{$DV.INTERVAL}`, and the thresholds
  below. One master HTTP agent item polls `summary/`; all estate metrics are dependent items with JSONPath and
  `Discard unchanged with heartbeat` where it helps. Value maps for worker and job states, units
  (`s`, `B`, `%`) set correctly, a **dashboard** (success ratio, duration percentiles, failures by reason,
  freshness, platform health) and a graph prototype set are included.
- **LLD rules** for device groups, collection groups, storage targets, workers and receivers, with item
  and trigger prototypes for each, so new groups and workers appear in Zabbix on their own and removed ones
  age out (*Keep lost resources period*).
- **Triggers with sane defaults**, all threshold-macro driven and with `Recovery` expressions, tags
  (`component`, `group`, `scope`) and dependencies so a down orchestrator does not raise 200 child alerts:
  - *Success ratio below `{$DV.SUCCESS.MIN}` (default 95 %) over 24 h*, per estate and per group.
  - *No successful backup for `{$DV.STALE.MAX}`* (default 2 × the longest schedule) per group.
  - *Devices never backed up > 0*, *consecutive failures >= `{$DV.FAIL.CONSEC}`*.
  - *Backup duration p95 above `{$DV.DURATION.MAX}`* or a 3× jump against the previous week
    (`trendavg`).
  - *Scheduler has no leader for > 2 min*, *worker heartbeat older than 3 intervals*, *worker pending approval
    for > 1 h*, *assignment version behind*, *storage target check failing*, *storage free space low*,
    *push refusals spiking*, *monitoring endpoint unreachable or returning 401/5xx*, *clock skew > 60 s*.
- **`DeviceVault Device by HTTP`** (optional, see scale note): a host-prototype style template that creates
  one Zabbix host per device (or per tag/smart group (D27)) so network teams can see "last backup" on the
  device they already monitor. Because they often have a Zabbix host per device already, the same
  per-device LLD can instead be provided as a **template linked to the existing host**, matched by a
  `{$DV.DEVICE}` macro (the device name or IP in DeviceVault), which avoids duplicating inventory.

**Scale note.** A 10,000-device estate must not become 10,000 requests a minute. Two controls: estate and
per-group metrics are aggregated server-side in one query each (an indexed query over a bounded recent window,
cached for the polling interval, with no per-request heavy work), and the per-device endpoint is paged,
filterable by group and tag, and meant to be polled slowly (for example every 15 minutes), with a single bulk response feeding
dependent items. Discovery should default to **groups, not devices**; per-device discovery is opt-in.

**Push alternative.** For firewalled Zabbix proxies or air-gapped networks, the same metric catalogue can be
sent out through `zabbix_sender`-style **trapper** items by the leader scheduler on a timer (`DV_ZABBIX_*`
variables, secret from a file), instead of being polled. It is a thin second transport over the same
metric computation, so it is a follow-up (D30), not part of the first cut.

**Prometheus (Q4b).** The same catalogue rendered in Prometheus text format at `/api/monitoring/metrics`
(counters for outcomes, histograms for durations, gauges for freshness and health, with `device_group`,
`collection_group` and `reason` labels and **no per-device labels by default** to keep cardinality bounded), plus
shipped example alert rules and a Grafana dashboard in `deploy/`. This is mostly formatting work once the
metrics exist.

**Delivery in slices** (each useful on its own):
1. Metric computation module and the `summary/` and `device-groups/` endpoints with the monitoring token, plus tests, including the
   authorization test.
2. Template generator and the `DeviceVault by HTTP` template with the estate, group and platform-health items and
   triggers, validated by importing it into a Zabbix container in the dev stack (a `make` target; Docker only, like
   everything else).
3. Per-device endpoint and optional template; `metrics` for Prometheus; docs in `DEPLOYMENT.md` and an
   `OPERATIONS.md` page on thresholds and tuning.

Metrics that depend on other roadmap items degrade gracefully: change counts appear once Q3 exists, freshness
against expected interval once Q5 does, and failure reasons from verification probes once Q12 does.

---

## 4. Detailed changes

Larger pieces of work, in rough strategic order within each theme. Several unlock others, so the final
section proposes a sequence.

### Theme A — Understanding changes

#### D1. Semantic, structured diff and change timeline
**Impact**: Turns a wall of text into answers: "an ACL was edited on interface Gi0/1", not "line 412
changed".
**Design**: Per-driver parsers produce a structured tree (interfaces, ACLs, routing, users, SNMP, NTP,
AAA...). Cisco-style hierarchical configs can use an indentation parser (like `ciscoconfparse`);
Junos has `display set`; others via TextFSM/Genie where licensing allows. Store the structured form
alongside the raw text, diff trees, and render a **change timeline** per device and per group with
categories and risk badges. Drivers declare a `sections` capability so this stays additive. Raw
diff stays the fallback for unknown platforms.

#### D2. Compliance and policy checking
**Impact**: The feature that moves DeviceVault from "backup tool" to "compliance evidence source".
**Design**: Rules evaluated against each new backup: *must contain* / *must not contain* (regex),
structured assertions on D1's tree ("every interface has `no ip proxy-arp`"), and
**benchmark packs** (CIS, vendor hardening guides, an organisation's own baseline) shipped as data. Each
rule has severity, scope (device group, driver, tag), and an owner. Results are stored per backup:
pass/fail/not applicable, with the offending lines, a compliance score per device and group, and a
trend. Violations feed Q2. Rules are managed by global administrators, results visible with
`view_contents`. Exceptions with expiry and justification are first-class (auditors ask for them).

#### D3. Golden config and drift detection
**Impact**: "Is this device what we intended?"
**Design**: A device (or a group/type) can have a **golden** reference: a pinned backup (Q8) or a
rendered template. Compare each new backup against it with ignore patterns, report drift as a score and a
diff, and alert on new drift. Includes **expected-change windows** so a planned maintenance does not page
anyone, and an "accept as new baseline" action that is audited.

#### D4. Unauthorized-change detection with change-ticket correlation
**Impact**: Answers "who changed it and was it approved?", the question every post-incident review asks.
**Design**: Correlate backup diffs with (a) AAA/syslog "configured from vty" events, (b) maintenance windows,
and (c) change tickets (ServiceNow, Jira, Freshservice) via D8 connectors. Flag changes outside a window or
without a ticket. Optional syslog ingestion on the receiver (UDP/TCP/TLS) triggers an *event-driven backup* when
a "configuration change" message arrives (see D5), which both captures the change quickly and attributes it.

#### D5. Event-driven backups
**Impact**: Backups at the moment of change instead of at 02:00; far smaller recovery-point gaps.
**Design**: Trigger a backup when a syslog `%SYS-5-CONFIG_I`-style message, an SNMP trap, a webhook from a
network automation tool, or a CI pipeline says so. Debounced per device. Lives in the `receiver`
component (already the only inbound-exposed piece) and creates ordinary `BackupJob`s via signed events,
exactly like `push.received`.

### Theme B — Recovery

#### D6. Restore and push-back
**Impact**: Backup without restore is half a product. This is the most-requested feature in this
category.
**Design**: A *restore* job type: select a backup, optionally select a **subset** (a section from D1),
preview as a diff against the live config (fetched fresh), require a second approver (D9), then a collector
applies it. Drivers declare a `restore` capability with a method: `replace` (Cisco `configure replace`, Junos
`load override`), `merge` (paste into config mode), `commit-confirmed` with automatic rollback timer
(Junos, IOS-XR, Arista). Pre-restore backup is always taken first. Everything is audited and requires the
new `restore` grant flag. Start with drivers that support safe replace/rollback; refuse where there is no
safe path.

#### D7. Disaster-recovery bundles and device replacement
**Impact**: "A switch died at 2 a.m. and the replacement is in the box."
**Design**: For a device, produce a **bundle**: latest config, firmware version, license info, optionally
related artefacts (D10), plus step-by-step bootstrap instructions generated from the driver
(management IP, SSH keys, serial console snippet). A *zero-touch provisioning* mode exposes the config over
the receiver (TFTP/HTTP) for a replacement unit to fetch by serial number or MAC. Tight scope: serve
a config to a known device, once, on request, audited.

### Theme C — Broader collection

#### D8. Integrations: CMDB, ticketing, source of truth and chat
**Impact**: Enterprises will not maintain a second inventory.
**Design**: A connector framework in the same style as storage drivers (`devicevault.integrations` entry
point, pydantic `Config`, UI form from schema).
- **Inventory sync (inbound)**: NetBox, Nautobot, ServiceNow CMDB, Infoblox, LibreNMS/Zabbix/Observium, CSV from
  a URL. Creates/updates/retires devices and groups from the source of truth, with field mapping, dry run, and
  "managed by" flag so UI edits to a synced field are refused.
- **Ticketing (outbound)**: open a ticket on persistent failure, on non-compliance (D2), on drift (D3).
- **Chat/ChatOps**: Slack, Teams, Mattermost, with a bot command to "back up device X now" (permissions
  enforced as the linked user).
- **Automation hand-off**: Ansible inventory export, an official Terraform provider, a Python client.
- **SIEM**: Q10 extended with CEF/LEEF.

#### D9. Approval workflow (four-eyes)
**Impact**: Required by many regulated environments for sensitive actions.
**Design**: A generic *pending action* model: restore (D6), deleting backups before retention, changing
retention, un-pinning, editing credentials, approving a worker. A policy chooses which actions need a second
person from a given group. Requester and approver must differ; both are audited. Fits the existing `access.py`
single-decision-point design: approval is another input to the decision, not a parallel path.

#### D10. Beyond configuration: firmware, licences, inventory, state
**Impact**: Network teams back up more than `running-config`.
**Design**: Per-device multiple **artefacts**: running and startup config, VLAN database (`vlan.dat`),
license files, certificates, full-system archives (F5 UCS, Fortinet full backup), and **operational snapshots**
(`show version`, `show inventory`, interface and neighbour tables). Parse out OS version, serial number,
model, uptime and end-of-support dates into device attributes, giving you:
- **Firmware/OS inventory** with "devices on affected versions" lookups against a vulnerability feed
  (CVE/vendor advisory import), a rare and valuable combination with config search (Q6): *which devices run
  version X **and** have the vulnerable feature enabled?*
- **End-of-life/end-of-support tracking** with expiry reports.
- **Certificate expiry** alerts from collected certificates.

#### D11. Non-CLI collection methods
**Impact**: Many platforms (controllers, firewalls, SD-WAN, cloud) have no usable SSH CLI.
**Design**: Driver bases next to `NetmikoDriver` for **REST/HTTPS APIs** (Meraki, Fortinet, Palo Alto,
SD-WAN controllers, Aruba Central, Mist, Cisco DNA Center/Catalyst Center), **NETCONF/RESTCONF** and
**gNMI** (YANG-model backups), and **SNMP** where config copy is triggered by MIB (Cisco `ccCopy`). Add
cloud-network config: AWS security groups and route tables, Azure NSGs, GCP firewall rules, snapshotted to
the same pipeline, which brings "what was the cloud firewall at 14:03 last Tuesday" to the same tool.

#### D12. Jump hosts, bastions and network segments
**Impact**: Real networks are segmented. Most customers will not open a flat route from one collector.
**Design**: Collection groups already localize collectors. Add per-device/group SSH **jump host** (ProxyJump)
support and credential reference, SOCKS/HTTP proxy, and out-of-band console server access (serial over
SSH). Keep the secret handling sealed per worker as today. Pairs with D13 for automatic discovery per segment.

#### D13. Discovery and onboarding
**Impact**: The inventory is wrong on day one. Discovery fixes it.
**Design**: A discovery job on a collector: scan CIDR ranges (ICMP/SSH banner/SNMP sysDescr), fingerprint the
platform, try candidate credentials from a **credential trial list** (safe retry limits to avoid account
lockout), and propose devices for approval with the driver pre-selected. LLDP/CDP neighbour crawling to find
adjacent devices. Results sit in an *inbox* for review, never auto-added.

### Theme D — Security and trust

#### D14. Secrets management integration
**Impact**: Many security teams forbid long-lived device passwords in an application database.
**Design**: A `Credential` backend abstraction: **HashiCorp Vault**, **CyberArk**, **Delinea/Thycotic**,
**AWS/Azure/GCP secrets**, **Bitwarden Secrets Manager**. The orchestrator fetches (or, better, hands the
*reference* to the collector, which fetches through its own identity, so the secret never sits on the
orchestrator). Support dynamic/ephemeral credentials (Vault SSH CA certificates, TACACS+ one-time
accounts), checkout/check-in workflows, and automatic rotation of the passwords DeviceVault itself uses on
devices, with verification and rollback.

#### D15. Tamper-evident audit and backup integrity
**Impact**: Auditors ask "how do I know this log or this backup was not altered?"
**Design**: Hash-chain audit entries (each includes the hash of the previous, anchored periodically), signed
daily checkpoints that can be exported to a write-once location. For backups, the SHA-256 already
recorded at store time becomes a **signed manifest**; add periodic **integrity sweeps** that read stored
backups back and verify them (catches bit rot on S3/NAS), and **WORM/object-lock** support on the S3 driver
(S3 Object Lock, compliance mode) and legal-hold flags that override retention.

#### D16. Key management and rotation tooling
**Impact**: The key ring exists; operating it should not need a shell.
**Design**: UI and API to rotate the vault key, data keys and orchestrator signing key with progress
and rollback, re-wrap rather than re-encrypt where the format allows, and **re-sign worker trust** without
manual state resets (an improvement to decision 1). Optional **HSM/KMS** wrapping of the vault private key
(AWS KMS, Azure Key Vault, PKCS#11). Per-device-group vault keys, so the crypto boundary matches the
permission boundary: *one tenant's content can never be decrypted by another's admins*.

#### D17. Authentication hardening
**Impact**: Closes common security-questionnaire gaps.
**Design**: **MFA** (TOTP and WebAuthn/passkeys) for local users, with enforcement per group; **SAML 2.0**
(previously ruled out in decision 22; enterprises keep asking, so revisit if demand is real); **SCIM 2.0**
provisioning and deprovisioning from Entra/Okta so leavers lose access immediately rather than at their
next login; IP allow-lists per user group; session concurrency limits; and **just-in-time elevation**
("request Global administrator for 1 hour, with reason"), which also builds on D9.

#### D18. Worker and receiver security tightening
**Impact**: Reduces blast radius, answers "what if a collector is compromised".
**Design**: Per-worker broker users and vhost permissions (listed as a known limitation in
ARCHITECTURE.md section 4.2), mTLS for AMQP/Redis, receiver rate-limits per source with automatic
temporary bans, optional **allow-list of drivers per worker** so a compromised collector in the DMZ cannot
be asked to run a driver meant for the core. Signed driver packages (plugin integrity) for third-party
entry points.

### Theme E — Scale, resilience and operations

#### D19. Multi-tenancy and delegated administration
**Impact**: MSPs, large holdings and carriers need strict separation; internal customers want self-service.
**Design**: Introduce **tenants** above device groups: each with its own device groups, credentials,
storage targets, collection groups, vault key (D16), branding, retention policy and admins, so a tenant
admin can administer *their* world without being a Global administrator. Cross-tenant visibility only for
platform administrators. This is a major data-model change, so decide it **early**, since retrofitting is far
more expensive than building it in.

#### D20. Scale-out scheduling and large estates
**Impact**: 10,000+ devices need predictable behaviour.
**Design**: Scheduler jitter and smoothing (spread cron-aligned jobs across the window), per-collection-group
and per-credential concurrency limits (avoid TACACS meltdown), per-site "maintenance blackout" calendars, job
priority classes (on-demand beats scheduled), back-pressure when storage lags, and a documented sizing
guide with load-test results. Add a synthetic load generator to the `demo` collector so capacity can be
proven without hardware.

#### D21. Backup storage efficiency
**Impact**: Most configs are 99.9% identical to yesterday's.
**Design**: Delta/deduplicating storage: the git driver already does this implicitly; add chunk-level
dedup (content-defined chunking) for the S3 and filesystem drivers, compression policies, and tiering
(hot → cold/Glacier) driven by retention. Keeps encrypted content opaque by deduplicating *before* encryption on
the collector with per-device convergent keys only if the security trade-off is accepted and documented.
Otherwise store full encrypted blobs and rely on compression-before-encryption.

#### D22. Multi-target replication and storage health
**Impact**: One copy is no copy.
**Design**: A device can have **several storage targets** (primary + replicas, e.g. local NAS, S3 in another
region, git mirror) with a write quorum policy ("stored" when 2 of 3 confirm), automatic repair of a
lagging target, per-target health (free space, last successful write) and a *restore drill* that
periodically reads a random backup back from each target and reports the result. Fits the existing
"stored when hashes match" model.

#### D23. Disaster recovery of DeviceVault itself
**Impact**: The backup system must itself be recoverable.
**Design**: One-command export of the orchestrator's state (database, keys, workers, settings) into an
encrypted bundle, a documented and tested **bare-metal restore**, an SQLite→PostgreSQL command (decision
5 promised it), PostgreSQL PITR and Redis Sentinel guidance (already listed as "later"), RabbitMQ
cluster recipes, and a **DR runbook** in `docs/`. A `manage.py doctor` command that verifies
the whole installation (keys, queues, workers, storage reachability, clock skew) belongs here too.

#### D24. Upgrades, versioning and fleet management of workers
**Impact**: 20 collectors across 12 sites cannot be updated by hand.
**Design**: Version negotiation in registration (workers report their version and driver list; the
orchestrator refuses incompatible protocol versions with a clear message), a UI view of fleet versions,
**rolling-upgrade** guidance, and optional staged driver rollout ("enable the new Junos driver on collection
group A first"). Health: per-worker disk, memory, clock and connectivity checks surfaced in the Workers page.

### Theme F — User experience and insight

#### D25. Topology, relationships and impact
**Impact**: Turns an inventory into a map.
**Design**: Use LLDP/CDP neighbours (D13) and parsed interfaces (D1) to draw topology and answer "what
depends on this device" before a change. Show per device a one-page **profile**: facts, last N changes,
compliance status, drift, firmware, support dates, notes and attachments.

#### D26. Reports and evidence packs
**Impact**: Audit season becomes a button.
**Design**: Parameterised reports (PDF/CSV/JSON): *backup coverage*, *change history for device group over
period*, *compliance by benchmark*, *access review* (who can see what, from `accounts`), *credential age*,
*retention proof*. An **evidence pack** bundles a period's reports, the audit extract and the integrity
manifest (D15) into one signed archive for an auditor. Scheduled delivery via Q14.

#### D27. Tags, custom fields and smart groups
**Impact**: Real inventories have dimensions beyond "device group": site, owner, criticality, lifecycle,
PCI scope.
**Design**: Free-form tags and typed custom fields on devices, saved filters as **dynamic groups**
that schedules, compliance rules (D2), notifications (Q2) and reports (D26) can target. Fewer device groups,
less manual maintenance, and a natural bridge to inventory sync (D8).

#### D28. AI-assisted analysis (optional, off by default)
**Impact**: Reduces the time between "something changed" and "I understand it".
**Design**: Summaries of diffs in plain language ("added a permit rule for 10.4.0.0/16 on the outside
ACL; changed OSPF cost on Gi0/2"), risk classification of changes, natural-language config search ("which
firewalls allow any-any?"), and draft remediation. Strict constraints because configs hold sensitive data:
bring-your-own model endpoint, run on-premises or via a customer-controlled gateway, redact secrets before
any model sees text, no training, per-group opt-in, and every call audited. Built only on top of D1/D2 so
the model explains facts rather than inventing them.

#### D29. Accessibility, localisation and theming
**Impact**: Procurement checklists ask (WCAG 2.1 AA, languages, dark mode, corporate branding).
**Design**: Systematic accessibility pass of the Quasar UI, Vue I18n with externalised strings, per-tenant
logo/colour (D19), keyboard-first navigation for the diff and search views.

### Theme G — Monitoring and observability

The first slice is Q4 ([Monitoring integration](#monitoring-integration-zabbix-and-prometheus)). These are the
larger follow-ups.

#### D30. Monitoring suite: push transport, tracing and more platforms
**Impact**: Fits DeviceVault into whichever operations stack a customer runs, including restricted networks.
**Design**:
- **Zabbix trapper push** from the leader scheduler (`DV_ZABBIX_SERVER`, `DV_ZABBIX_HOST`, secret from file),
  for sites where Zabbix cannot reach the orchestrator, and an optional **Zabbix agent 2 plugin or
  `UserParameter` pack** for the worker and receiver hosts (disk, state volume, process, listener ports), shipped as
  a second template.
- **Per-device status in Zabbix** at scale: host-prototype automation driven by inventory sync (D8), with the
  device's tags (D27) mapped to Zabbix host groups and tags.
- **Event stream**: every job and worker event also available as a webhook or syslog message (Q2, Q10), so
  Zabbix (or Splunk, Elastic, Datadog) can alarm on a single occurrence rather than a polled aggregate.
- **Other platforms**: Grafana dashboards-as-code, Nagios/Icinga plugin (`check_devicevault`), PRTG sensor,
  Datadog and OpenTelemetry (metrics and **traces** of a job across orchestrator, collector and storage
  worker, using the job id as the trace id) and **SNMP traps** for estates that only speak SNMP.
- **Service health endpoint**: unauthenticated `/healthz` (liveness) and `/readyz` (database, Redis, broker,
  scheduler lease) for load balancers and orchestrators, giving the HA VIP in ARCHITECTURE.md section 8 a real
  health check.
- **SLO view**: define a target ("99 % of devices backed up within 24 h"), compute attainment and error budget,
  and show it in the UI and in exported metrics.

---

## 5. Suggested sequencing

The order below keeps each step useful on its own and puts the foundations other items need first.

| Step | Contents | Why here |
|---|---|---|
| **1. Trust the data** | Q1 retention, Q3 change summary, Q5 stale detection, Q8 pin/label, Q12 verification probes | Makes existing backups bounded, meaningful and trustworthy. Pins and summaries are prerequisites for later work. |
| **2. Be heard** | Q2 notifications, Q4 Zabbix and Prometheus monitoring, Q10 audit export, Q13 dashboard, Q14 digest | Gets signal out to people and monitoring. Cheap, and the first thing evaluators check. |
| **3. Be adopted** | Q7 bulk import, Q9 API tokens, Q11 vendor drivers, Q6 search | Onboarding speed and reach. |
| **4. Tenancy decision** | D19 multi-tenancy (design at least), D27 tags and smart groups | Hardest to retrofit; settle the model before piling features on it. |
| **5. Understand** | D1 structured diff → D2 compliance → D3 golden/drift → D4/D5 change attribution and event-driven backups | The differentiating core. D1 is the base for everything after it. |
| **6. Recover** | D6 restore, D9 approvals, D7 DR bundles | Completes the backup → restore loop, using approval to make it safe. |
| **7. Enterprise fit** | D8 integrations, D14 secrets managers, D17 auth hardening, D15 tamper-evident audit | The security-questionnaire and integration items that close deals. |
| **8. Scale and resilience** | D12 jump hosts, D13 discovery, D20 scale-out, D22 replication, D23 DR, D16 key tooling, D18 tightening, D24 fleet | Larger, riskier estates. |
| **9. Beyond config** | D10 artefacts, D11 non-CLI methods, D25 topology, D26 reports, D21 efficiency | Broadens what DeviceVault is a system of record for. |
| **10. Optional** | D28 AI assistance, D29 accessibility and localisation, D30 further monitoring integrations | Valuable but depends on the foundations above (D29 earlier if a tender needs it). |

### Dependencies at a glance

- **Q8 (pin)** → Q1 (retention exemption), D3 (golden reference).
- **Q3 (change summary)** → Q2 (change notifications), D4.
- **Q9 (API tokens)** → D8 (automation integrations), Q4 (the monitoring token reuses the machinery).
- **Q3, Q5, Q12** → richer Q4 metrics (change counts, freshness against schedule, failure reasons).
- **D1 (structured diff)** → D2, D3, D6 (partial restore), D10, D25, D28.
- **D9 (approvals)** → D6, D17 (JIT elevation), and sensitive retention actions.
- **D19 (tenancy)** → D16 (per-tenant keys), D29 (per-tenant branding); affects every later data model.
- **D13 (discovery)** → D25 (topology), D8 (inventory sync).

## 6. Deliberately not on the list

- **Live configuration management or full network automation** (pushing templated changes at scale):
  that is Ansible, Nornir and Nautobot territory. DeviceVault should integrate with them (D8), and its
  restore (D6) should stay a recovery tool.
- **Real-time telemetry and performance monitoring**: LibreNMS, Zabbix and Prometheus do this well. Export
  metrics (Q4, D30), do not rebuild them.
- **Replacing the Celery/RabbitMQ/Redis bus** or breaking the "workers have no configuration" rule: both
  are core to the design (ARCHITECTURE.md sections 1 and 4) and every item above is expected to fit them.

## 7. Keeping this document honest

When an item is scheduled, give it a phase in ARCHITECTURE.md section 10 and a decision-log entry for any
design choice, then change its entry here to a one-line pointer. When an item is rejected, move it to
section 6 with the reason. Review the ranking whenever a real customer conversation changes the picture:
the value estimates above are informed guesses, not measurements.
