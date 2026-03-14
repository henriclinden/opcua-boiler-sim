# OPC UA Boiler Simulator

A Python-based OPC UA server that simulates a hot-water boiler system for development and testing purposes. It exposes a realistic physical model — with actuators, sensors, and alarms — over an unauthenticated, unencrypted OPC UA endpoint.

> ⚠️ **Development use only.** This server has no security or authentication configured and should never be deployed in a production or networked environment.

---

## Features

- Realistic boiler physics: water mixing, heating, passive heat loss, pressure modelling
- Writable actuator nodes (inlet valve, outlet valve, heater)
- Read-only sensor nodes updated every second (fill level, temperature, pressure, flow rates, heater power)
- Boolean alarm nodes (over-temperature, low level, high pressure)
- Anonymous access, no encryption — connects instantly from any OPC UA client
- Fully self-contained single-file server

---

## Requirements

- Python 3.8+
- [asyncua](https://github.com/FreeOpcUa/opcua-asyncio)

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Getting Started

```bash
git clone https://github.com/your-username/your-repo.git
cd your-repo
pip install -r requirements.txt
python boiler_opcua_server.py
```

The server starts on:

```
opc.tcp://0.0.0.0:4840/boiler/
```

Connect with any OPC UA client (e.g. [UaExpert](https://www.unified-automation.com/products/development-tools/uaexpert.html), [Prosys OPC UA Browser](https://prosysopc.com/products/opc-ua-browser/)) using:

- **Endpoint:** `opc.tcp://localhost:4840/boiler/`
- **Security policy:** None
- **Authentication:** Anonymous

---

## OPC UA Address Space

```
Objects/
└── Boiler/
    ├── Actuators/              ← Writable nodes
    │   ├── InletValve          Float   0–100 %     Fresh water intake valve position
    │   ├── OutletValve         Float   0–100 %     Hot water outlet valve position
    │   └── HeaterEnable        Boolean             Heating element on/off
    │
    ├── Sensors/                ← Read-only, updated every second
    │   ├── FillLevel           Float   %           Water level in the boiler
    │   ├── Temperature         Float   °C          Water temperature
    │   ├── Pressure            Float   bar         Internal pressure
    │   ├── FlowRateIn          Float   L/min       Actual inlet flow rate
    │   ├── FlowRateOut         Float   L/min       Actual outlet flow rate
    │   └── HeaterPower         Float   kW          Actual heater power delivered
    │
    └── Alarms/                 ← Read-only boolean flags
        ├── OverTemperature     Boolean             Temperature exceeds 95 °C
        ├── LowLevel            Boolean             Fill level below 10 %
        └── HighPressure        Boolean             Pressure exceeds 3.5 bar
```

---

## Physical Model

The simulation runs a 1-second tick and models the following:

| Parameter             | Default value |
|-----------------------|---------------|
| Boiler volume         | 200 L         |
| Heater rated power    | 6 kW          |
| Passive heat loss     | 0.3 kW        |
| Max inlet flow        | 20 L/min      |
| Max outlet flow       | 15 L/min      |
| Ambient temperature   | 20 °C         |

**Water level** rises and falls based on inlet and outlet valve positions. Incoming water is always at ambient temperature and mixes with existing water using energy conservation.

**Temperature** is driven by heater power minus passive losses. The heater derate as water approaches 100 °C and is hard-capped at boiling. The element is also disabled if the boiler runs dry.

**Pressure** is derived from both fill level and temperature:

```
P = P_atm + fill_factor × 0.5 + (T - 20°C) × 0.02
```

---

## Configuration

All physical constants are defined at the top of `boiler_opcua_server.py` and can be adjusted freely:

```python
BOILER_VOLUME_LITERS  = 200.0   # Total boiler capacity
HEATER_MAX_KW         = 6.0     # Heating element rated power
HEAT_LOSS_KW          = 0.3     # Passive heat loss
AMBIENT_TEMP_C        = 20.0    # Room temperature
MAX_FLOW_IN_LPM       = 20.0    # Max inlet flow at 100% valve
MAX_FLOW_OUT_LPM      = 15.0    # Max outlet flow at 100% valve
SIM_INTERVAL_S        = 1.0     # Simulation tick in seconds

ALARM_OVER_TEMP_C     = 95.0
ALARM_LOW_LEVEL_PCT   = 10.0
ALARM_HIGH_PRESSURE   = 3.5
```

---

## Project Structure

```
.
├── boiler_opcua_server.py   # OPC UA server + physics simulation
├── requirements.txt         # Python dependencies
└── README.md
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.
