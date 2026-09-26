# go-eCharger (API v1) for Home Assistant

A small, local-polling Home Assistant integration for go-eCharger wallboxes that
speak the **HTTP API v1** (`/status` and `/mqtt?payload=`), for example firmware
0.42.0 with the API v1 enabled.

It is built for flaky Wi-Fi: every request is retried, and when the charger is
unreachable the entities keep their last known values instead of becoming
unavailable. A separate **Connection** binary sensor tells you whether Home
Assistant can currently talk to the charger.

## Features

- Config flow with charger **IP address / hostname** and **refresh interval**,
  both changeable later via *Configure* (options) or *Reconfigure*.
- Status exposed as sensors (see list below).
- **Allow charging** switch (`alw`).
- **Max current** dropdown (select) for dynamic / PV charging, set through
  `amx`, which is kept in RAM on the charger and does not wear out the flash.
- Automatic workaround for the firmware 0.42.0 `amx` bug (see below).
- Retry with back-off on every request, last values kept, connection status
  entity with `last_success`, `consecutive_failures` and `last_error`
  attributes.
- **Reboot** button using the undocumented `rst=1` command.
- Download diagnostics from the device page.

## Installation

### HACS

1. HACS → Integrations → three dots → *Custom repositories*.
2. Add this repository URL with category *Integration*.
3. Install **go-eCharger (API v1)** and restart Home Assistant.

### Manual

Copy `custom_components/goecharger_v1` into the `custom_components` folder of
your Home Assistant configuration directory and restart Home Assistant.

## Configuration

Settings → Devices & services → *Add integration* → **go-eCharger (API v1)**.

| Field | Description |
| --- | --- |
| IP address / hostname | Local address of the charger. The HTTP API must be enabled in the go-eCharger app. |
| Refresh interval | Poll interval in seconds. Default 10, minimum 5 (as recommended by go-e). |
| Reboot once on "No ground" error | On by default. See *Automatic reboot on "No ground"* below. |

Both values can be changed afterwards via the *Configure* button of the
integration entry or via *Reconfigure* in the entry menu. The integration
reloads automatically.

The charger's serial number (`sse`) is used as the unique id, so changing the
IP address keeps all entities and their history.

## Entities

### Controls

| Entity | Key | Notes |
| --- | --- | --- |
| Allow charging (switch) | `alw` | Verified against the charger's response. |
| Reboot (button, diagnostic) | `rst=1` | Undocumented command; the charger restarts without answering. |
| Max current (select, 6 A … `ama`) | `amx` | Shows the charger-reported `amx`, or the requested value while a write is pending. |

### Sensors

| Entity | Key | Unit / values |
| --- | --- | --- |
| Car status | `car` | ready / charging / waiting for vehicle / charge finished |
| Stored charging current | `amp` | A (flash value, not affected by `amx`) |
| Reported max current (diagnostic) | `amx` | A, raw value reported by the charger |
| Error | `err` | none / RCCB / phase / no ground / internal |
| Phases available / Phases active | `pha` | count, with `l1`/`l2`/`l3` attributes |
| Temperature 1 … 6 | `tma` | °C, one sensor per array element present |
| Temperature (disabled by default) | `tmp` | °C, reports a bogus value on firmware 042.0 |
| Session energy | `dws` | kWh |
| Total energy | `eto` | kWh |
| Voltage L1/L2/L3 (N disabled by default) | `nrg` | V |
| Current L1/L2/L3 | `nrg` | A |
| Power L1/L2/L3, Power (total), (N disabled by default) | `nrg` | W |
| Power factor L1/L2/L3 (disabled by default) | `nrg` | % |
| Diagnostic: access control, automatic stop, cable lock, cable current limit, absolute max current, energy limit, unlocked by card, firmware version, reboot counter, uptime, load balancing current | `ast`, `stp`, `ust`, `cbl`, `ama`, `dwo`, `uby`, `fwv`, `rbc`, `rbt`, `loa` | |

### Binary sensors

| Entity | Source | Notes |
| --- | --- | --- |
| Connection | integration | On when the last request succeeded. Always available. |
| Vehicle connected | `car` ≠ 1 | |
| Charging | `car` = 2 | |
| Charging allowed (disabled by default) | `alw` | Read-only twin of the switch. |
| 16 A adapter | `adi` | Diagnostic |

Sensors are only created for keys that are present in the charger's status
object, so a firmware that lacks a field simply does not get that entity.

## Behaviour on connection problems

- Every HTTP request is tried up to 3 times (10 s timeout each, 1 s / 2 s
  back-off).
- If a poll still fails, the coordinator logs one warning, keeps the previous
  status and flips the **Connection** binary sensor to *off*. All other entities
  keep their values and stay available.
- The first successful poll after an outage logs an info message and turns the
  sensor back *on*.
- Setting the switch or number while the charger is unreachable raises an error
  in the UI / automation trace; nothing is silently swallowed.

## Automatic reboot on "No ground"

The charger sometimes reports the "No ground" error (`err=8`) after months of
uptime although nothing is wrong with the installation, and only a reboot
clears it. With the option enabled (default) the integration handles this:

1. When a status reports `err=8` while the rule is armed, the charger is
   rebooted once (`rst=1`) and the rule is disarmed. A warning is logged.
2. The rule is re-armed only after a status with "No error" (`err=0`) has been
   seen. If the error persists after the reboot, or comes back without a
   "No error" in between, nothing further happens.
3. The rule starts armed when the integration loads. If the error is already
   present at that point, a single reboot is attempted.

The **Reboot** button exposes `auto_reboot_on_no_ground`, `auto_reboot_armed`
and `last_auto_reboot` attributes. Other error codes (RCCB, phase, internal)
never trigger a reboot.

## Firmware 0.42.0 `amx` workaround

After a reboot firmware 0.42.0 believes the charging current is limited to
6 A and silently clamps `amx`. The known workaround is to set `amp` to 6 and
then back to the real maximum, after which `amx` works again.

The charger reports `amx` in its status object, but only a few seconds after
the write, and it never mirrors `amx` into `amp`. The integration therefore
verifies asynchronously:

1. **Max current** sends `amx=<value>` and marks the value as pending. The
   dropdown shows the requested value right away.
2. Every fresh status is compared with the pending value. As soon as the
   charger reports the same `amx` the write is confirmed.
3. If the charger still reports a different `amx` **30 seconds** after the
   write, the workaround runs once in the background: `amp=6`, then
   `amp=<restore>` (the current flash value, e.g. 16 A, never lower than the
   requested value and never above `ama`), then `amx=<value>` again. A status
   refresh is scheduled so this happens even with a long poll interval.
4. If another 30 seconds pass without effect, an error is logged, the pending
   value is dropped and the dropdown shows what the charger really reports. No
   further attempts are made until you change the value again.
5. Selecting a new value while one is pending replaces it and restarts the
   30 second wait.

The **Reported max current** diagnostic sensor shows the raw `amx` from the
charger. The dropdown exposes `flash_current`, `pending_value`,
`pending_since`, `workaround_applied` and `last_error` attributes.

## Requirements

- Home Assistant 2024.11 or newer.
- go-eCharger with the local HTTP API (API v1) enabled.
