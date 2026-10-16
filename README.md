# ha-ecovacs-legacy — Ecovacs DEEBOT 710/711 for Home Assistant

Custom integration for the **legacy Ecovacs DEEBOT 710 family** (DEEBOT 710 `uv242z`,
711 `jr3pqa`, 711s `d0cnel`, 715 `eyi9jv`), which the core Ecovacs integration lists as
*"Device not supported"* (see DeebotUniverse/client.py#612 and #809).

## Why they are "not supported"
These robots report `company: eco-ng` in the Ecovacs device list but speak the old
**XML ("non-950") protocol**: commands go to `POST /api/iot/devmanager.do` with
`payloadType: "x"` and an XML `<ctl …/>` payload, and status is pushed as XML on the MQTT
topic `iot/atr/<event>/<did>/<class>/<resource>/x`. They are **not** XMPP, so the
`sucks` code path in core does not take them either.

`deebot-client` (already shipped with Home Assistant) implements that XML transport for the
OZMO 900 family; it only lacks a hardware profile for these classes. This integration adds
that profile (from `mrbungle64/ecovacs-deebot.js` 0.9.6, `uv242z`) plus tolerant parsers and
its own entities, and **only offers the legacy robots** — the ones core already supports are
never duplicated.

## Entities (per robot)
- `vacuum`: state, start / pause / resume / stop, return to base, **locate** (plays the
  "I am here" sound), fan speed `normal` / `max`, `send_command` (raw XML command name +
  attributes).
- `sensor`: battery, main brush / side brush / filter lifespan (%), error code (+ description).
- Lifetime totals (area, time, cleanings) — disabled by default.

Push over MQTT, plus a refresh every 5 min (lifespan and totals hourly). The cloud session
re-logs in automatically; a new device verification triggers a re-auth flow.

## Install (HACS custom repository)
1. HACS → ⋮ → Custom repositories → `https://github.com/abasgeor/ha-ecovacs-legacy` (Integration).
2. Install and restart Home Assistant.
3. Settings → Devices & Services → Add Integration → **Ecovacs Legacy** → Ecovacs account
   (same as the app) and country.
4. If Ecovacs asks to verify the device, it e-mails a code: enter it in the next step.
   The verified client id is stored in the entry, so it is asked only once.
5. Pick the robots to expose.

## Notes
- Requires Home Assistant 2026.10+ (deebot-client 18.x).
- Uses its own client device id, distinct from the core integration's, so both can run
  side by side on the same account without fighting over the MQTT session.
- Credentials live only in the config entry.
