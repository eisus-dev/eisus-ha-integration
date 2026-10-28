# EISUS — Home Assistant integration (firmware v9.6.6+)

Local, cloud-free control of EISUS Wi-Fi switch modules from Home Assistant.

Firmware **v9.6.6 removed the device-side Home Assistant MQTT client** that
existed in v9.6.5 (FIX-72..FIX-77): the device no longer runs a second
PubSubClient, no longer stores a local broker config in NVS, no longer
publishes `homeassistant/*` discovery documents, and no longer exposes
`/local/ha-config` or `/local/ha-status`.

The integration in this folder replaces all of that. It talks to the device
over the **existing, token-protected local HTTP API** (`X-Local-Token`,
TCP/80) and finds devices over **mDNS** (`_eisus._tcp`). No Mosquitto add-on,
no broker credentials, no MQTT at all.

```
Home Assistant  --HTTP :80/local/*  (X-Local-Token)-->  EISUS device
                <--mDNS _eisus._tcp (devid, type, fw, mac)--
```

## Requirements

| Item | Value |
| --- | --- |
| Device firmware | v9.6.6 or newer (`fw` TXT record / `/local/info → fwVersion`) |
| Home Assistant | 2024.1 or newer (uses `zeroconf`, `DataUpdateCoordinator`) |
| Network | Home Assistant and the device on the same L2/L3 LAN (mDNS is link-local) |
| Device setting | a local access token stored in NVS (`mqttcreds → localtoken`) |

## Install

### Method 1: HACS (Recommended for standard setups)
1. In Home Assistant, open **HACS** > **Integrations**.
2. Click the three dots (top right) > **Custom repositories**.
3. Add repository URL: `https://github.com/eisus-dev/eisus-ha-integration`
4. Type: **Integration**.
5. Click **Add**, find **EISUS**, click **Download**, and restart Home Assistant.

---

### Method 2: Mass Production & Automated Deployments (Zero-Terminal for Clients)

For deploying client hubs (e.g., Armbian TV Boxes, Mini PCs) without opening terminal at client sites:

#### A. Golden Config Template (Recommended for Commercial Production)
Prepare a golden Home Assistant `/config` folder once in-house with HACS and `custom_components/eisus` pre-installed and configured:
1. Copy this golden `config` directory directly onto client storage during device flashing/provisioning.
2. Mount it in `docker-compose.yml`:
   ```yaml
   volumes:
     - /opt/homeassistant/config:/config
   ```
3. The server boots at the client with EISUS pre-loaded and ready instantly.

#### B. Docker Compose (Auto-pull via Init Container)
Automatically clone/update the integration repository on first boot:
```yaml
services:
  init-eisus:
    image: alpine/git
    volumes:
      - /opt/homeassistant/config:/config
    command: >
      sh -c "if [ ! -d /config/custom_components/eisus ]; then
               git clone --depth=1 https://github.com/eisus-dev/eisus-ha-integration.git /tmp/eisus_repo &&
               mkdir -p /config/custom_components &&
               cp -r /tmp/eisus_repo/custom_components/eisus /config/custom_components/ &&
               rm -rf /tmp/eisus_repo;
             fi"

  homeassistant:
    image: lscr.io/linuxserver/homeassistant:latest
    container_name: homeassistant
    depends_on:
      - init-eisus
    network_mode: host
    volumes:
      - /opt/homeassistant/config:/config
    restart: unless-stopped
```

#### C. Shell Command (UI Triggered)
In client's default `configuration.yaml`:
```yaml
shell_command:
  install_eisus: "git clone --depth=1 https://github.com/eisus-dev/eisus-ha-integration.git /tmp/eisus && mkdir -p /config/custom_components && cp -ru /tmp/eisus/custom_components/eisus /config/custom_components/ && rm -rf /tmp/eisus"
```
Execute via **Developer Tools** > **Services** (`shell_command.install_eisus`), then restart Home Assistant.

---

### Method 3: PowerShell Script or Manual Copy

The component lives in `custom_components/eisus/`. Copy that folder into your
Home Assistant configuration directory, then restart Home Assistant.

**Windows PowerShell, one command** (Home Assistant in Docker, config shared
over SMB):

```powershell
.\deploy_to_ha.ps1 -Destination "\\homeassistant\config"
```

**Windows PowerShell, one command** (Home Assistant in Docker on a Debian host
reached over SSH — uploads with scp, installs with ssh and restarts the
container). `-Destination` defaults to the production path
`/opt/homeassistant/config`, so the whole update is:

```powershell
.\deploy_to_ha.ps1 -SshTarget "root@192.168.1.50" -Container homeassistant
```

which is exactly equivalent to:

```powershell
.\deploy_to_ha.ps1 -Destination "/opt/homeassistant/config" -SshTarget "root@192.168.1.50" -Container homeassistant
```

and on the host installs into
`/opt/homeassistant/config/custom_components/eisus` (the folder Home Assistant
in Docker has bind-mounted as `/config`), then runs `docker restart homeassistant`.

**Manual copy** (any OS): copy `custom_components/eisus/` into `/config/custom_components/eisus/`
and restart Home Assistant.

## Getting the local token

The token is created by the EISUS platform during onboarding and delivered to
the device over its own cloud link (topic `eisus/<type>/<deviceId>/ctrl-token`,
field `localAccessToken`). Home Assistant cannot read it from the device — the
device only accepts it, it never hands it out. Retrieve it from the EISUS
platform / your installer notes and keep it somewhere safe: it is the only
credential needed for LAN control.

Firmware side (for reference): stored as `NVS_KEY_MQTT_LOCAL_TOKEN` = key
`localtoken` in namespace `mqttcreds`; the device rejects requests with an
empty or different token with HTTP 401.

## Adding the device

1. **Automatic (recommended)** — as soon as the device has an IP address it
   advertises `_eisus._tcp` with TXT records `devid`, `type`, `sub`, `fw`,
   `hw`, `mac` and `out` (output count). Home Assistant shows a discovery card;
   click **Configure** and paste the token. The host/port are pre-filled from
   mDNS. The `devid` is used as the config entry unique ID, so a device is
   never added twice.
2. **Manual** — *Settings → Devices & Services → Add Integration → EISUS*, then
   enter `IP address`, `port` (80) and the **Local token**.
3. To change address/port/token later: the entry's **Configure** button
   (options flow) or re-authentication when a 401 is seen.

## What you get

Entities are created from the device's own `/local/state` document, so the
set matches the hardware and the configured mode.

**Always**

| Platform | Entity | Notes |
| --- | --- | --- |
| `switch` | Output 1..4 | the relay outputs (`{"outputN": true/false}`) |
| `switch` | Output N pulse mode | gate-opener / momentary mode per output (config) |
| `switch` | Child lock | blocks the physical wall switches (config) |
| `select` | Switch mode | Toggle / Momentary / Shutter (config) |
| `select` | Power restore | Last state / All on / All off (config) |
| `number` | Output N pulse duration | 50..600000 ms (config) |
| `number` | Shutter open/close time | only in shutter mode, 500..120000 ms (config) |
| `sensor` | Uptime, Device time | device clock + offset (diagnostic) |
| `sensor` | Wi-Fi signal | RSSI in dBm from `/local/info` (diagnostic) |
| `sensor` | IP address | address the device answers on (diagnostic) |
| `sensor` | Cloud link | online / cloud offline / no internet (diagnostic) |
| `sensor` | Schedule rules | count, with the rule list as an attribute (diagnostic) |
| `sensor` | Last state trigger | which source changed the state last (diagnostic) |
| `sensor` | Output N timer remaining | seconds left on that output's timer (diagnostic) |
| `time` | Set device time | the device clock; setting it pushes Home Assistant's time |
| `binary_sensor` | Output N timer active | timer / pulse running (diagnostic) |
| `binary_sensor` | Output N manual override | manual control beating the schedule, disabled by default |
| `binary_sensor` | Cloud reachable | the **device** can reach the EISUS cloud, disabled by default |
| `button` | Sync device time | pushes the HA clock to the device (`/local/time/set`) |
| `button` | Cancel all timers | cancels the timer on every output (diagnostic) |
| `button` | Clear schedule | deletes all weekly rules (diagnostic) |
| `button` | Factory reset | wipes credentials and reboots the device (diagnostic) |

**Shutter mode only** (`switchMode = Shutter`)

| Platform | Entity | Notes |
| --- | --- | --- |
| `cover` | *(device name)* | open / close / stop, plus set position once calibrated |
| `sensor` | Shutter calibration | `calibrated` / `not calibrated`, travel times as attributes |
| `binary_sensor` | Shutter moving | motor running |
| `binary_sensor` | Shutter calibrating | interactive calibration in progress |
| `button` | Shutter calibration start / end | enter / leave interactive calibration |

Sensor devices (`type: sensor`, `presence`, `motion`) get a single primary
binary sensor plus the shared diagnostics and buttons instead of the relay
entities - see "Adding a new device type".

Entities marked *(config)* can be hidden with the entity-registry settings; the
diagnostic ones are already grouped as `Diagnostic`.

While the device runs in shutter mode, outputs 1 and 3 are the motor relays
and are therefore owned by the cover entity instead of being exposed as
switches. Changing the switch mode on the device is detected by the
coordinator (poll interval: 4 s) and the config entry is reloaded
automatically so the entity set follows the hardware.

## Command mapping

Every entity action is a single POST to the device; the firmware answers with
`{"ack": ..., "state": ...}` and the returned state is folded straight back
into the coordinator, so the UI updates without waiting for the next poll.

| Home Assistant action | Request |
| --- | --- |
| Output N switch | `POST /local/cmd` `{"outputN": true}` |
| Output N pulse mode | `POST /local/cmd` `{"pulseMode": {"output": N, "enabled": true, "durationMs": 500}}` |
| Output N pulse duration | same as above (enabled flag preserved) |
| Child lock | `POST /local/cmd` `{"childlock": true}` |
| Switch mode | `POST /local/cmd` `{"switchmode": 0\|1\|2}` |
| Power restore | `POST /local/cmd` `{"powerRestore": 0\|1\|2}` |
| Shutter open/close/stop | `POST /local/cmd` `{"shutter": "open"\|"close"\|"stop"}` |
| Shutter position | `POST /local/cmd` `{"shutterPosition": 0..100}` |
| Shutter open/close time | `POST /local/cmd` `{"shutterCalibrate": {"openTimeMs": X, "closeTimeMs": Y}}` |
| Output N timer remaining (read) | `GET /local/state` → `timers.outputN.remainingMs` |
| Cancel all timers | `POST /local/timer` `{"output": N, "cancel": true}` × outputs |
| Timer set | `POST /local/timer` `{"output": N, "state": true, "afterMs": 0, "durationMs": 60000, "restoreState": true}` |
| Schedule upload | `POST /local/schedule` `{"command": "set", "rules": [ ... ]}` |
| Clear schedule | `POST /local/schedule` `{"command": "clear"}` |
| Device clock (read) | `GET /local/time/get` → valid / epoch / timezone / offsetSec / localTime |
| Device clock (set) | `POST /local/time/set` `{"epoch": X, "timezone": "Africa/Cairo", "offsetSec": 7200}` |
| Shutter calibration start/end | `POST /local/cmd` `{"shutterCalibrate": {"mode": "start"\|"end"}}` |
| Shutter calibration jog | `POST /local/cmd` `{"shutterCalibrate": {"action": "open"\|"stop"\|"close"}}` |
| Factory reset | `POST /local/cmd` `{"command": "factoryreset"}` |

`X-Local-Token` is sent on **every** request, including the 4 s `GET /local/state`
poll. A 401 is surfaced as an unavailable entity plus a log entry; a 503
(device state mutex busy) is retried three times with 300 ms spacing.

## IP address changes

If a request fails, the coordinator re-resolves `eisus-<devid>._eisus._tcp`
over mDNS (at most once every 20 s), and when the address or port changed it
updates the config entry automatically. DHCP moves therefore heal themselves;
the only requirement is that the device keeps its `deviceId`.

## Services

Entities cover the everyday surface; the rest is driven by services (Developer
Tools → Actions, automations or scripts).

| Service | What it does |
| --- | --- |
| `eisus.send_command` | raw JSON to `/local/cmd`, `/local/timer`, `/local/schedule` or `/local/time/set` |
| `eisus.set_time` | set the device clock (defaults to the Home Assistant clock) |
| `eisus.set_schedule` | replace all weekly rules (empty list = clear) |
| `eisus.cancel_timer` | cancel one output's timer, or all of them |
| `eisus.calibrate_shutter` | start/end interactive calibration, or set travel times directly |

### Schedules

```yaml
service: eisus.set_schedule
data:
  device_id: 3f8c1a24b0e94d7fa1c2d3e4f5a6b7c8      # the EISUS device
  rules:
    - days: [mon, tue, wed, thu, fri]              # or "mon,tue", "monday", 62
      start: "07:00"                               # or 420 (minutes past midnight)
      end: "23:00"
      outputs: {1: true, 2: false}                 # or {output1: true}, [1, 2]
      scheduleid: workday                          # optional correlation id
    - id: 9
      enabled: false
      days: 64                                     # bit0=Sun .. bit6=Sat
      startMin: 1200
      endMin: 1380
      outputs: [3]
```

The device stores up to 8 rules (`SCHED_MAX_RULES`); every call replaces the
whole list. `days`, `start` and `end` are validated before anything is sent, so
a typo raises a clear error instead of silently uploading a broken schedule.

### Timers

```yaml
# turn output 2 on for 5 minutes, starting in 30 seconds, then restore it
service: eisus.send_command
data:
  device_id: 3f8c1a24b0e94d7fa1c2d3e4f5a6b7c8
  endpoint: timer
  payload:
    output: 2
    state: true
    afterMs: 30000
    durationMs: 300000
    restoreState: true
    timerid: sprinkler
```

Cancel one output (`eisus.cancel_timer` with `output: 2`) or every output
(`eisus.cancel_timer` without `output`, or the *Cancel all timers* button).
`durationMs` of 0 means "until cancelled", which is how a pulse/gate mode is
implemented (`/local/cmd` + `pulseMode`).

### Shutter

```yaml
# interactive calibration: start, jog the motor, then finish
- service: eisus.calibrate_shutter
  data: { device_id: 3f8c…, mode: start }
- service: eisus.calibrate_shutter
  data: { device_id: 3f8c…, action: open }     # or: stop / close
- service: eisus.calibrate_shutter
  data: { device_id: 3f8c…, mode: end }        # stores the measured travel times

# or enter the travel times directly (the other one is filled from the device)
- service: eisus.calibrate_shutter
  data: { device_id: 3f8c…, open_time_ms: 22000, close_time_ms: 23000 }
```

Position control (`cover.set_position`, or `{"shutterPosition": 0..100}`) only
becomes available once the device reports `shutter.calibrated = true`; the
*Shutter calibration* sensor shows the current state.

### Pulse / gate opener

```yaml
# make output 3 a gate pulse of 800 ms (output=None applies to all outputs)
service: eisus.send_command
data:
  device_id: 3f8c1a24b0e94d7fa1c2d3e4f5a6b7c8
  payload: { pulseMode: { output: 3, enabled: true, durationMs: 800 } }
```

### Clock

```yaml
service: eisus.set_time          # nothing to fill in: HA's clock is pushed
data: { device_id: 3f8c1a24b0e94d7fa1c2d3e4f5a6b7c8 }

# or a specific time / timezone
service: eisus.set_time
data:
  device_id: 3f8c1a24b0e94d7fa1c2d3e4f5a6b7c8
  epoch: 1800000000
  timezone: "Africa/Cairo"
  offset_sec: 7200
```

The coordinator also pushes the clock automatically whenever the device reports
`time.valid = false` (at most once a minute). The device has no RTC and needs
internet for NTP; in a LAN-only install - or during an internet outage - Home
Assistant is what keeps the schedule and timer engines working.

### Raw escape hatch

`eisus.send_command` still exists for firmware keys without an entity, e.g.
updating Wi-Fi credentials: `endpoint: cmd` with `{"ssid": "...", "pass": "..."}`.

## Adding a new device type

Everything type-specific lives in **one file**: `device_registry.py`.

```
DEVICE_TYPES = {
    "switch":   SwitchDeviceHandler,      # shipped hardware (1..4 gang)
    "sensor":   SensorDeviceHandler,      # base class for sensors
    "presence": PresenceSensorHandler,    # mmWave / PIR (future)
    "motion":   MotionSensorHandler,      # motion (future)
    # "energy": EnergyMeterHandler,       # <- add yours here
}
```

A handler declares four things and nothing else:

| Member | Meaning |
| --- | --- |
| `device_type` | the `type` string the firmware reports in `/local/info` |
| `platforms` | which HA entity platforms to create (subset of `ALL_PLATFORMS`) |
| `default_features` | what the device can do when the firmware sends no `capabilities` object |
| `build_command()` / `parse_state()` | how a logical action becomes a request, and how `/local/state` is read |

Add a type in four steps:

1. Subclass the closest handler (usually `SensorDeviceHandler`) in
   `device_registry.py` and set `device_type`, `label`, `platforms`,
   `default_features` and, if needed, `primary_keys`.
2. Override `build_command()` for the commands that type supports and
   `parse_state()` for the values its entities need.
3. Register the class in `DEVICE_TYPES`.
4. Add the entity classes the new platforms need (only the ones that do not
   exist yet) and gate them on `coord.supports("<feature>")` or
   `coord.device_type`. The existing platforms already read everything through
   the handler and the coordinator, so they need no change.

Nothing else has to be touched: the config entry asks the handler for its
platform list, the coordinator resolves the handler on every refresh, and both
`/local/info` (`capabilities`, `outputCount`) and `/local/state` keep the
integration in sync with what the firmware actually reports. A firmware that
reports a type this version does not know yet is handled by the switch handler
instead of failing.

### Firmware contract a new type relies on

| Endpoint | Used for |
| --- | --- |
| `GET /local/info` | `deviceId`, `name`, `type`, `subtype`, `fwVersion`, `hwVersion`, `mac`, `ip`, `outputCount`, `switchMode`, `childLock`, `powerRestore`, `schedRules`, `timeValid`, `timezone`, `offsetSec`, `rssi`, `uptimeMs`, `mqttOnline`, `inetReachable`, `capabilities` |
| `GET /local/state` | outputs, `switchMode`, `childLock`, `powerRestore`, `time`, `manualOverride`, `shutter`, `pulse`, `timers`, `schedule`, `trigger`, `epoch` |
| `POST /local/cmd` | outputs, `switchmode`, `childlock`, `powerRestore`, `pulseMode`, `shutter`, `shutterPosition`, `shutterCalibrate`, `ssid`/`pass`, `command: factoryreset` |
| `POST /local/timer` | `{"command": "get"}` or `{output, state, afterMs, durationMs, restoreState, timerid}` / `{output, cancel: true}` |
| `POST /local/schedule` | `{"command": "get"\|"set"\|"add"\|"delete"\|"clear"}` (+ `rules`) |
| `POST /local/time/set`, `GET /local/time/get` | device clock (firmware FIX-82) |
| mDNS `_eisus._tcp` | `devid`, `type`, `sub`, `fw`, `hw`, `mac`, `out` |

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `invalid_auth` (401) in the log | Wrong token. Re-authenticate the entry or paste the token again in **Configure**. |
| `cannot_connect` | Wrong IP, device on another VLAN, or mDNS blocked. Try the manual setup path with the device IP. |
| Entities unavailable during cloud outages | Not expected — local HTTP is independent of the cloud. Check the LAN path and the token. |
| No discovery card | mDNS is link-local: Home Assistant and the device must share a subnet. Add the device manually instead. |
| `503 device busy` repeatedly | Another controller is issuing commands in a tight loop; the state mutex has a 50 ms window on the device. |
| Shutter position unknown | The shutter is not calibrated (`shutter.calibrated = false`). Set *Shutter open time* then *Shutter close time*, or calibrate interactively with the `shutterCalibrate` command. |
| Mode changed on the device, entities look wrong | Expected for a few seconds: the coordinator detects the change and reloads the entry. |

## Files

```
eisus_ha/
├─ deploy_to_ha.ps1                  # one-command deploy (SMB share or SSH+Docker)
├─ README.md
└─ custom_components/eisus/
   ├─ __init__.py                    # entry setup/unload, platform routing, eisus.* services
   ├─ device_registry.py             # DEVICE_TYPES + handlers (switch / sensor / future)
   ├─ config_flow.py                 # mDNS + manual + reauth + options
   ├─ coordinator.py                 # polling, mDNS rediscovery, all commands, clock
   ├─ entity.py                      # shared device registry entry
   ├─ const.py                       # endpoints, enums, firmware bounds
   ├─ switch.py select.py number.py  # outputs, mode, pulse, child lock
   ├─ cover.py                       # shutter (shutter mode only)
   ├─ time.py                        # device clock entity + eisus.set_time
   ├─ schedule.py                    # weekly rule validation + eisus.set_schedule
   ├─ sensor.py binary_sensor.py     # diagnostics, timers, device clock, link state
   ├─ button.py                      # timers, schedule, calibration, clock, factory reset
   ├─ strings.json translations/en.json services.yaml
```

## Change log

* **2.1.0** (firmware v9.6.6 + FIX-82) — device-type registry
  (`device_registry.py`) drives the entity set, gang detection from
  `outputCount`, richer `/local/info` diagnostics (RSSI, IP, cloud link),
  device clock over `/local/time/set|get` with automatic push when the device
  has no time, weekly schedules via `eisus.set_schedule`, timers via
  `eisus.cancel_timer`, shutter calibration via `eisus.calibrate_shutter`,
  graceful degradation on older firmware, and `-Destination` defaults to
  `/opt/homeassistant/config` for the Docker/Debian deployment.
* **2.0.0** (firmware v9.6.6) — rewritten for the local-HTTP-only protocol:
  full entity surface (switch/select/number/cover/sensor/binary_sensor/button),
  `eisus.send_command`, automatic mDNS re-discovery on IP change, automatic
  reload when the switch mode changes, no MQTT anywhere.
* **1.0.0** (firmware v9.6.5) — outputs-only integration, one switch per relay.

