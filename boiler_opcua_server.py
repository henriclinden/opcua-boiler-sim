"""
OPC UA Boiler Simulator
=======================
A development-only OPC UA server simulating a hot-water boiler system.
- No authentication, no encryption (open endpoint)
- Uses the `asyncua` library (pip install asyncua)

Boiler model:
  Actuators (writable):
    InletValve    – fresh water intake, 0–100 %
    HeaterEnable  – heating element on/off (Boolean)
    OutletValve   – user draws hot water, 0–100 %

  Sensors (read-only, simulated every second):
    FillLevel     – % (0–100)
    Temperature   – °C
    Pressure      – bar (derived from fill + temp)
    FlowRateIn    – L/min
    FlowRateOut   – L/min
    HeaterPower   – kW (actual power delivered)

  Alarms (read-only booleans):
    OverTemperature  – temp > 95 °C
    LowLevel         – fill < 10 %
    HighPressure     – pressure > 3.5 bar

  SimControl (writable – can be adjusted live):
    SimIntervalS     – wall-clock seconds between ticks (default 1.0, min 0.1)
    SimSpeed         – physics seconds simulated per tick (default 1.0, e.g. 10 = 10× faster)

Run:
    python boiler_opcua_server.py

Connect with any OPC UA client (e.g. UaExpert) to:
    opc.tcp://0.0.0.0:4840/boiler/
"""

import asyncio
import logging

from asyncua import Server, ua

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("boiler")

# ---------------------------------------------------------------------------
# Physical constants / tuneable parameters
# ---------------------------------------------------------------------------
BOILER_VOLUME_LITERS = 200.0  # total boiler capacity
HEATER_MAX_KW = 6.0  # heating element rated power
HEAT_LOSS_KW = 0.3  # passive heat loss to environment
AMBIENT_TEMP_C = 20.0  # room temperature
MAX_FLOW_IN_LPM = 20.0  # max inlet flow at 100 % valve
MAX_FLOW_OUT_LPM = 15.0  # max outlet flow at 100 % valve
SIM_INTERVAL_S = 1.0  # wall-clock seconds between ticks
SIM_SPEED = 1.0  # physics seconds simulated per tick (>1 = faster)

# Pressure model: P_bar = BASE + fill_factor * FILL_COEFF + temp_factor * TEMP_COEFF
PRESSURE_BASE = 1.013  # atmospheric pressure (bar)
PRESSURE_FILL_COEFF = 0.5  # extra bar at 100 % fill
PRESSURE_TEMP_COEFF = 0.02  # extra bar per °C above 20 °C

# Alarm thresholds
ALARM_OVER_TEMP_C = 95.0
ALARM_LOW_LEVEL_PCT = 10.0
ALARM_HIGH_PRESSURE = 3.5


# ---------------------------------------------------------------------------
# Boiler physics model
# ---------------------------------------------------------------------------
class BoilerModel:
    def __init__(self):
        self.fill_level = 80.0  # %
        self.temperature = 25.0  # °C
        # Actuator states
        self.inlet_valve = 0.0  # %
        self.outlet_valve = 0.0  # %
        self.heater_on = False

    # --- derived quantities -------------------------------------------------

    @property
    def water_liters(self):
        return self.fill_level / 100.0 * BOILER_VOLUME_LITERS

    @property
    def flow_in_lpm(self):
        return self.inlet_valve / 100.0 * MAX_FLOW_IN_LPM

    def flow_out_lpm(self, dt_s: float):
        # Can't draw more water than physically present in this tick
        available_lpm = self.water_liters / (dt_s / 60.0) if dt_s > 0 else 0.0
        return min(self.outlet_valve / 100.0 * MAX_FLOW_OUT_LPM, available_lpm)

    @property
    def heater_power_kw(self):
        if not self.heater_on or self.fill_level < 5.0:
            return 0.0
        # Derate as water approaches boiling
        headroom = max(0.0, 100.0 - self.temperature) / 80.0
        return HEATER_MAX_KW * min(headroom, 1.0)

    @property
    def pressure_bar(self):
        fill_factor = self.fill_level / 100.0
        temp_factor = max(0.0, self.temperature - AMBIENT_TEMP_C)
        return (
            PRESSURE_BASE
            + fill_factor * PRESSURE_FILL_COEFF
            + temp_factor * PRESSURE_TEMP_COEFF
        )

    # --- alarms -------------------------------------------------------------

    @property
    def alarm_over_temp(self):
        return self.temperature > ALARM_OVER_TEMP_C

    @property
    def alarm_low_level(self):
        return self.fill_level < ALARM_LOW_LEVEL_PCT

    @property
    def alarm_high_pressure(self):
        return self.pressure_bar > ALARM_HIGH_PRESSURE

    # --- simulation step ----------------------------------------------------

    def step(self, dt_s: float):
        """Advance the physical model by dt_s seconds."""
        dt_min = dt_s / 60.0

        # --- water volume ---------------------------------------------------
        vol_in = self.flow_in_lpm * dt_min  # litres added
        vol_out = self.flow_out_lpm(dt_s) * dt_min  # litres removed

        # Mixing: incoming cold water (ambient) cools the boiler proportionally
        current_water = self.water_liters
        new_water = current_water + vol_in - vol_out
        new_water = max(0.0, min(BOILER_VOLUME_LITERS, new_water))

        if new_water > 0 and vol_in > 0:
            # Conservation of thermal energy during mixing
            energy_existing = current_water * self.temperature
            energy_added = vol_in * AMBIENT_TEMP_C
            total_energy = energy_existing + energy_added - vol_out * self.temperature
            mixed_temp = total_energy / new_water
        else:
            mixed_temp = self.temperature

        self.fill_level = new_water / BOILER_VOLUME_LITERS * 100.0
        self.temperature = mixed_temp

        # --- temperature (heating / cooling) --------------------------------
        # Q_net in kJ = (heater_kw - loss_kw) * dt_s
        # ΔT = Q_net / (mass_kg * specific_heat)  — water: ~4.186 kJ/(kg·°C), ρ≈1 kg/L
        mass_kg = new_water  # ≈ 1 kg per litre
        if mass_kg > 0:
            q_net_kj = (self.heater_power_kw - HEAT_LOSS_KW) * dt_s
            delta_t = q_net_kj / (mass_kg * 4.186)
            self.temperature = max(AMBIENT_TEMP_C, self.temperature + delta_t)

        # Hard cap at 100 °C (steam relief)
        self.temperature = min(self.temperature, 100.0)


# ---------------------------------------------------------------------------
# OPC UA server
# ---------------------------------------------------------------------------
async def main():
    server = Server()
    await server.init()

    server.set_endpoint("opc.tcp://0.0.0.0:4840/boiler/")
    server.set_server_name("Boiler Simulator")

    # No security – development only
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
    server.set_security_IDs(["Anonymous"])

    # Register namespace
    uri = "urn:boiler:simulator"
    nsidx = await server.register_namespace(uri)

    # Build address space under Objects/Boiler
    objects = server.nodes.objects
    boiler_node = await objects.add_object(nsidx, "Boiler")

    # Helper to add a variable
    async def add_var(parent, name, init_val, writable=False, description=""):
        node = await parent.add_variable(nsidx, name, init_val)
        if writable:
            await node.set_writable()
        return node

    # --- Actuators folder ---------------------------------------------------
    actuators = await boiler_node.add_object(nsidx, "Actuators")
    n_inlet = await add_var(
        actuators,
        "InletValve",
        0.0,
        writable=True,
        description="Fresh-water inlet valve position 0-100 %",
    )
    n_outlet = await add_var(
        actuators,
        "OutletValve",
        0.0,
        writable=True,
        description="Hot-water outlet valve position 0-100 %",
    )
    n_heater = await add_var(
        actuators,
        "HeaterEnable",
        False,
        writable=True,
        description="Heating element on/off",
    )

    # --- Sensors folder -----------------------------------------------------
    sensors = await boiler_node.add_object(nsidx, "Sensors")
    n_fill = await add_var(sensors, "FillLevel", 80.0, description="Fill level 0-100 %")
    n_temp = await add_var(
        sensors, "Temperature", 25.0, description="Water temperature °C"
    )
    n_press = await add_var(
        sensors, "Pressure", 1.013, description="Internal pressure bar"
    )
    n_flow_in = await add_var(
        sensors, "FlowRateIn", 0.0, description="Inlet flow L/min"
    )
    n_flow_out = await add_var(
        sensors, "FlowRateOut", 0.0, description="Outlet flow L/min"
    )
    n_hpow = await add_var(
        sensors, "HeaterPower", 0.0, description="Actual heater power kW"
    )

    # --- Alarms folder ------------------------------------------------------
    alarms = await boiler_node.add_object(nsidx, "Alarms")
    n_ot = await add_var(alarms, "OverTemperature", False, description="Temp > 95 °C")
    n_ll = await add_var(alarms, "LowLevel", False, description="Fill < 10 %")
    n_hp = await add_var(
        alarms, "HighPressure", False, description="Pressure > 3.5 bar"
    )

    # --- SimControl folder --------------------------------------------------
    simctrl = await boiler_node.add_object(nsidx, "SimControl")
    n_interval = await add_var(
        simctrl,
        "SimIntervalS",
        SIM_INTERVAL_S,
        writable=True,
        description="Wall-clock seconds between ticks (min 0.1)",
    )
    n_simspeed = await add_var(
        simctrl,
        "SimSpeed",
        SIM_SPEED,
        writable=True,
        description="Physics seconds per tick — e.g. 10 = 10× faster",
    )

    # --- Simulation loop ----------------------------------------------------
    model = BoilerModel()

    async def simulation_loop():
        while True:
            # Read simulation control parameters
            interval_s = await n_interval.get_value()
            sim_speed = await n_simspeed.get_value()

            # Clamp to safe ranges
            interval_s = max(0.1, float(interval_s))
            sim_speed = max(0.1, float(sim_speed))

            # Read actuator setpoints from OPC UA nodes
            model.inlet_valve = await n_inlet.get_value()
            model.outlet_valve = await n_outlet.get_value()
            model.heater_on = await n_heater.get_value()

            # Clamp actuator values to valid ranges
            model.inlet_valve = max(0.0, min(100.0, model.inlet_valve))
            model.outlet_valve = max(0.0, min(100.0, model.outlet_valve))

            # Advance physics: interval_s of wall time, sim_speed × physics time
            model.step(interval_s * sim_speed)

            # Write sensor outputs back to OPC UA
            await n_fill.set_value(round(model.fill_level, 2))
            await n_temp.set_value(round(model.temperature, 2))
            await n_press.set_value(round(model.pressure_bar, 3))
            await n_flow_in.set_value(round(model.flow_in_lpm, 2))
            await n_flow_out.set_value(
                round(model.flow_out_lpm(interval_s * sim_speed), 2)
            )
            await n_hpow.set_value(round(model.heater_power_kw, 2))

            # Write alarm flags
            await n_ot.set_value(model.alarm_over_temp)
            await n_ll.set_value(model.alarm_low_level)
            await n_hp.set_value(model.alarm_high_pressure)

            log.info(
                "Fill=%.1f%%  Temp=%.1f°C  Press=%.3fbar  "
                "FlowIn=%.1f  FlowOut=%.1f  HeaterPow=%.2fkW  "
                "Speed=%.1fx  Interval=%.2fs  "
                "Alarms[OT=%s LL=%s HP=%s]",
                model.fill_level,
                model.temperature,
                model.pressure_bar,
                model.flow_in_lpm,
                model.flow_out_lpm(interval_s * sim_speed),
                model.heater_power_kw,
                sim_speed,
                interval_s,
                model.alarm_over_temp,
                model.alarm_low_level,
                model.alarm_high_pressure,
            )

            await asyncio.sleep(interval_s)

    log.info("Starting OPC UA Boiler Simulator on opc.tcp://0.0.0.0:4840/boiler/")
    log.info("Security: None  |  Authentication: Anonymous")

    async with server:
        await simulation_loop()


if __name__ == "__main__":
    asyncio.run(main())
