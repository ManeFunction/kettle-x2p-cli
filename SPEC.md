# MIoT spec: Xiaomi Smart Kettle 2 Pro (EU, BHR9107EU)

**Model string: `xiaomi.kettle.v20`** ("Xiaomi Smart Kettle 2 Pro (欧规版)").
URN: `urn:miot-spec-v2:device:kettle:0000A009:xiaomi-v20:1`

> Status: **model confirmed on the device** (`miIO.info` returned `model: xiaomi.kettle.v20`,
> firmware `2.2.7_0016`, hw `esp32`). `boil`, `warm-to`, `warm-keep`, `cancel` and `status` are all verified on the device.

Sources (two agree on all numbers): home.miot-spec.com/spec/xiaomi.kettle.v20 and
miot-spec.org/miot-spec-v2/instance?type=<URN above>.

## siid 2: kettle

| piid | name | format | access | range / values | unit |
|---|---|---|---|---|---|
| 1 | status | uint8 | r/n | 0 Idle, 1 Heating, 2 Boiling, 3 Cooling down, 4 Keep warm | |
| 2 | fault | uint8 | r/n | 0–255 (0 = none) | |
| 3 | temperature | int8 | r/n | -30–100 | °C |
| 4 | target-temperature | uint8 | r/w/n | 40–99 | °C |
| 5 | auto-keep-warm | bool | r/w/n | | |
| 6 | keep-warm-temperature | uint8 | r/w/n | 0–100 | °C |
| 7 | on | bool | r/w/n | | |

## siid 3: function (xiaomi-spec)

| piid | name | format | access | range / values | unit |
|---|---|---|---|---|---|
| 1 | keep-warm-time | uint16 | r/w/n | **60–1440** | min |
| 2 | custom-knob-temp | bool | r/w/n | | |
| 4 | lift-remember-temp | bool | r/w/n | | |
| 5 | boiling-reminder | bool | r/w/n | | |
| 6 | keep-warm-reminder | bool | r/w/n | | |
| 7 | kettle-lifting | bool | r/n | true = kettle lifted off base | |
| 8 | extended-mode | string | r/w/n | `name,temp,keep,keep_temp,minutes_...` presets | |
| 10 | warming-time | uint16 | r/n | 0–720 | min |
| 11 | target-mode | uint8 | r/w/n | 0 Heating, 1 Boiling, 10–15 Extended 1–6 | |
| 12 | heat-mode | string | r/w/n | `"<target>,<keep 1/0>,<keep_temp>,<keep_min>"`, e.g. `70,1,45,1440` | |
| 13 | boil-mode | string | r/w/n | same layout, e.g. `99,1,45,1440` | |

Action: **siid 3, aiid 1 `stop-work`** (in: `[]`, out: `[]`).

Other services (not used): siid 6 no-disturb (piid 1, bool); siid 4 knob-setting (piid 1–7, strings);
siid 5 local-timing (piid 1–6 strings, action aiid 1 push-water-reminder). Events omitted.

There is **no water-level property** in this spec. The closest safety signals are `fault` (2,2),
`status` (2,1) and `kettle-lifting` (3,7). The unofficial HA integration for this model reports that
fault `E2` = low water, but I have not confirmed the numeric fault code for it.

## Proposed command mapping

How the device is *started* is not defined by the spec itself; the batch below comes from the community integration
[username-andrey/xiaomi-smart-kettle-ha](https://github.com/username-andrey/xiaomi-smart-kettle-ha)
(tested on firmware v2.2.7_0016), which sends one `set_properties` with these items in this order.
`boil` was confirmed on our hardware (starts heating without writing `on`).

| command | set_properties (siid,piid = value) |
|---|---|
| `boil` | (2,4)=99, (2,5)=false, (2,6)=keep_temp, (3,1)=keep_min, (3,11)=1, (3,13)=`"99,0,<keep_temp>,<keep_min>"` |
| `warm-to T` | (2,4)=T, (2,5)=false, (2,6)=keep_temp, (3,1)=keep_min, (3,11)=0, (3,12)=`"T,0,<keep_temp>,<keep_min>"` |
| `warm-keep T M` | (2,4)=T, (2,5)=true, (2,6)=T, (3,1)=M, (3,11)=0, (3,12)=`"T,1,T,M"` |
| `cancel` | action (3,1) stop-work |
| `status` | get (2,1) (2,2) (2,3) (2,4) (2,5) (2,6) (3,7) (3,10) (3,11) |

Validation limits taken from the spec: target 40–99 °C; keep-warm minutes 60–1440 (spec minimum is
60, so `warm-keep` rejects less than 1 h).

Open points:
Which `fault` value means low water is still unknown.
