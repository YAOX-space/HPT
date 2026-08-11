# HPT Topology, Control, and Completion Test Alignment

This note aligns the tutorial model with the HPT/HDT literature and the Song Xing thesis. It focuses on one modeling question: where the energy converter should be connected, and what tests should define "modeling complete".

## 1. Immediate Answer: Energy Converter Connection

For the topology in Song Xing, Fig. 2-4, the energy converter is not simply connected to the primary bus, and it is not the ordinary secondary load bus either. It is connected to the main transformer's energy/tertiary winding W3 through magnetic coupling.

The correct AC-side structure for this specific topology is:

```text
Primary bus -> series coupling transformer / regulating converter -> main transformer W1
main transformer W2 -> secondary bus / load
main transformer W3 -> energy converter
regulating converter DC side <-> shared DC link <-> energy converter DC side
```

So for our tutorial model:

- `RegulatingConverter + SeriesTransformer` should be on the primary-side series path.
- `EnergyConverter` should connect to the main transformer's W3 energy/tertiary winding.
- `DCLink` is shared by both converters.
- `PrimaryEnergyCoupling` is not a good final name if it suggests "primary bus energy extraction"; better final names are `TertiaryEnergyWinding` or `EnergyWindingCoupling`.

Why it looks confusing in the paper figure: W3 is drawn on the right side of the transformer, close to W2, but W3 is a separate transformer winding, not the normal secondary load bus.

## 2. HPT/HDT Topology Families

The literature uses several names: HPT, HDT, hybrid transformer, hybrid distribution transformer, intelligent universal transformer, and integrated HDT. The common idea is:

```text
low-frequency transformer + fractionally rated power converter
```

The power converter is usually much smaller than the transformer rating, often used for the difference/compensation power rather than the whole load power.

### A. Series Converter Only

Structure:

```text
Grid -> series converter or series coupling transformer -> low-frequency transformer -> load
```

Variants:

- Direct series connection without coupling transformer.
- Series connection through a coupling transformer.
- Series on high-voltage/medium-voltage side.
- Series on low-voltage side.
- AC/AC matrix or chopper-based converter.
- AC/DC/AC converter.

Main purpose:

- Voltage sag/swell compensation.
- Phase shifting.
- Voltage regulation.

Advantages:

- Smaller converter rating when only compensation voltage is needed.
- Simple function definition.

Limitations:

- Cannot independently exchange sustained active power without an energy path.
- Limited harmonic/current compensation capability.
- Series converter current is line current, so current stress can be high.

### B. Shunt Converter Only

Structure:

```text
Grid/load bus -> shunt converter
low-frequency transformer remains main power path
```

Main purpose:

- Reactive power compensation.
- Power factor correction.
- Harmonic current compensation.
- Current balancing.

Advantages:

- Natural current-source compensation behavior.
- Useful for power quality.

Limitations:

- Does not directly inject series voltage, so load-voltage compensation is limited.
- Needs a DC source or DC-link energy management if active power is exchanged.

### C. Back-to-Back Series-Shunt HPT

Structure:

```text
series converter <-> shared DC link <-> shunt/energy converter
```

The shunt/energy converter can be:

- Directly connected to a bus.
- Connected through a shunt transformer.
- Connected to an auxiliary/tertiary winding of the main transformer.

Main purpose:

- Load voltage regulation.
- Grid current shaping.
- Power factor correction.
- Harmonic mitigation.
- Active power circulation between series and shunt converters.

Advantages:

- Strongest controllability among common HDT configurations.
- Similar functional logic to UPQC/UPFC: series side controls voltage, shunt side controls current/DC-link.

Limitations:

- More complex control.
- DC-link voltage control becomes essential.
- Converter capacity and transformer winding constraints must be coordinated.

### D. Auxiliary/Tertiary-Winding HPT

This is the family closest to Song Xing and Liu et al. 2021.

Structure:

```text
Main transformer:
  W1 = primary winding
  W2 = secondary winding
  W3 = tertiary / energy winding

Series coupling transformer:
  W4/W5 = coupling between regulating converter and line

Converters:
  CVp / energy converter -> W3
  CVt / regulating converter -> series transformer
  both share DC-link
```

Design logic:

- W1/W2 carry most load power through the low-frequency transformer.
- W3 gives the energy converter a magnetic coupling port with a suitable voltage rating.
- The regulating converter injects only compensation voltage.
- The energy converter maintains DC-link voltage and can shape grid current or compensate reactive/harmonic components.

Advantages:

- Converter does not need to be rated for the whole transformer power.
- W3 can be designed for converter voltage/current requirements.
- Maintains conventional transformer reliability.

Limitations:

- Requires a multi-winding transformer.
- Winding polarity/ratio matters.
- DC-link power balance must be modeled.

### E. Integrated HPT / IHDT

Structure:

```text
single integrated transformer core
W1 primary
W2 secondary
W3 series winding
W4 parallel winding
CVs series converter
CVp parallel converter
shared DC bus, optionally PV/storage through DC/DC
```

Design logic:

- Integrate series and parallel coupling windings into one transformer body.
- Remove external series coupling transformer.
- Coordinate normal operation and grid-fault operation under safe constraints.

Advantages:

- Lower core material, winding count, volume, and cost compared with multiple-transformer HDT schemes.
- Better suited for fault ride-through and coordinated capacity utilization.

Limitations:

- Transformer magnetic design is more specialized.
- Harder to build in Simulink from generic transformer blocks.
- Requires careful safe-operation constraints.

## 3. Iteration History

The rough development path is:

1. Conventional low-frequency transformer plus mechanical tap changer: reliable and efficient, but slow and not continuous.
2. Solid-state transformer: fully controllable, but expensive, high loss/complexity, and all power passes through converters.
3. Series compensation hybrid transformer: small converter injects compensation voltage for sag/swell.
4. Hybrid AC/AC converter-based transformers: matrix/chopper style structures for voltage compensation.
5. Back-to-back HDT: series converter and shunt/energy converter share a DC link, allowing voltage regulation and current compensation.
6. Auxiliary/tertiary-winding HDT: the energy converter connects to W3, reducing direct bus-voltage stress and improving magnetic integration.
7. Integrated HDT/IHDT: series and parallel windings are integrated into the transformer, reducing external transformer hardware and enabling coordinated fault operation.
8. Advanced-control HDT: compound control, QPR/repetitive control, MPC, hierarchical coordination, and potentially RL-based fault ride-through.

## 4. What HPT Can Do

A complete HPT model can support these functions:

- Voltage regulation: maintain LV/load voltage during grid sag/swell.
- Reactive power compensation: improve grid-side power factor.
- Harmonic mitigation: reduce grid-side current THD under nonlinear loads.
- Three-phase unbalance compensation: reduce negative/zero-sequence effects.
- DC-link energy balancing: keep converter DC voltage within safe range.
- Power flow control: circulate partial active power through the converters.
- Fault ride-through support: isolate/support load voltage during grid faults while respecting converter and winding current limits.
- Passive fallback: if converters are bypassed or disabled, the low-frequency transformer still transfers power.

## 5. Control Strategy Map

### Basic Equivalent Control

For analysis:

- Regulating/series converter = controlled voltage source.
- Energy/shunt converter = controlled current source.
- Shared DC capacitor = active power balance state.

The core condition is:

```text
P_series + P_energy + dE_dc/dt + losses = 0
```

Without storage, long-term active power exchange with the grid must balance through the two converters.

### Energy Converter Control

Typical layers:

1. PLL / phase reference from W3 or grid-side voltage.
2. abc -> dq transform.
3. Outer DC-link voltage loop:

```text
Vdc_ref - Vdc -> PI/filter/feedforward -> i_d_ref
```

4. Reactive/current quality loop:

```text
Q_ref or PF_ref -> i_q_ref
```

5. Inner current loop:

```text
i_dq_ref - i_dq -> decoupled PI / PR / QPR -> PWM
```

Important refinement from Liu et al. 2021:

- Pure PI can regulate Vdc, but may make grid current distorted/asymmetric under distorted or unbalanced conditions.
- PI plus low-pass/notch filters improves sinusoidal and symmetric grid currents.
- Feedforward improves transient overshoot.

### Regulating Converter Control

Typical layers:

1. Measure load voltage or transformer secondary voltage.
2. Generate target injected series voltage.
3. For three independent single-phase bridges, each phase can be controlled separately.
4. Use single-phase Park transform, PR/QPR, or voltage feedforward plus PI.
5. Generate SPWM/PWM gates for each H-bridge.

Main objective:

```text
V_load_ref - V_load -> U_series_ref -> PWM
```

For fault mode, the series converter priority becomes voltage support while respecting current and voltage limits.

### Coordination / Multi-Mode Control

Normal mode:

- Maintain Vload.
- Maintain Vdc.
- Improve PF.
- Share reactive compensation between series and shunt converters if capacity allows.

Fault mode:

- Priority 1: converter/winding current limits.
- Priority 2: DC-link bounds.
- Priority 3: load-voltage support.
- Priority 4: power quality / PF.

IHDT-style hierarchical coordination adds explicit power-sharing parameters such as active/reactive sharing factors and safe-operation constraints.

## 6. Design Norms for a Complete Model

The model should expose these parameters explicitly:

- Transformer ratings: nominal power, frequency, W1/W2/W3 voltage ratios, winding connections, leakage resistance/reactance.
- Series transformer or series winding ratio and polarity.
- Converter DC-link nominal voltage, capacitance, and initial voltage.
- Converter voltage/current ratings.
- Filter L or LCL/LC parameters.
- PWM switching frequency and sample time.
- Load types: balanced RL, unbalanced RL, nonlinear rectifier load.
- Controller gains: DC-link PI, current-loop PI/PR, voltage-loop PI/PR, filters/notches, feedforward gains.
- Limiters: modulation index, converter current, winding current, DC voltage max/min.

Useful design rules from the IHDT paper:

- Filter current ripple is commonly designed around 10%-20% of rated AC current.
- Filter capacitor fundamental reactive power should be kept below about 5% of rated active power.
- DC support capacitor sizing should constrain DC voltage fluctuation during power steps.

## 7. Completion Test Matrix

The tutorial HPT model should be considered complete only if it passes the following tests.

### Test 0: Topology Integrity

Pass conditions:

- W1 primary, W2 secondary, W3 energy/tertiary winding are identifiable.
- `EnergyConverter` AC side connects only to W3.
- `RegulatingConverter` AC side connects through series transformer/winding in the selected side.
- Both converters share the same physical DC link.
- Converter-off mode still leaves a valid transformer power path.
- Polarity test confirms positive series injection causes the expected voltage raise/lower.

### Test 1: Nominal Transformer Operation

Scenario:

- Converters disabled.
- Nominal grid and balanced load.

Pass conditions:

- Secondary voltage matches transformer ratio within tolerance.
- Power balance is physically sensible.
- No floating nodes, algebraic failures, or unconnected physical ports.

### Test 2: Voltage Sag/Swell Regulation

Scenario:

- Grid voltage steps to 0.8 pu and 1.2 pu.
- Balanced load.

Pass conditions:

- Load/LV RMS voltage returns close to reference.
- Series injection stays within modulation and converter voltage limits.
- DC-link remains within the allowed band.

Suggested tutorial gate:

- LV RMS error < 5%.
- Vdc within 0.85-1.15 pu.

Suggested final-research gate:

- LV RMS error < 2%.
- Vdc within 0.95-1.05 pu after settling.

### Test 3: DC-Link Voltage Control

Scenario:

- Load step.
- Grid sag/swell.
- Regulating converter active.

Pass conditions:

- Energy converter restores Vdc.
- No slow drift in Vdc.
- Active power balance holds:

```text
P_series + P_energy + dE_dc/dt ~= losses
```

### Test 4: Reactive Power / PF Control

Scenario:

- Inductive load.
- PF reference = 1.0.

Pass conditions:

- MV/grid-side PF improves toward reference.
- Energy converter current remains within rating.
- Voltage regulation remains active.

### Test 5: Unbalance Compensation

Scenario:

- One-phase load changes or asymmetric grid voltage.

Pass conditions:

- LV voltage unbalance is reduced.
- Grid-side current symmetry improves.
- If MV winding is delta, zero-sequence current should not inject to MV grid.

### Test 6: Harmonic Mitigation

Scenario:

- Nonlinear rectifier load.

Pass conditions:

- Grid-side current THD is lower with compensation than without.
- DC-link ripple remains bounded.
- Controller does not inject unstable oscillations.

### Test 7: Fault Ride-Through Smoke Test

Scenario:

- Single-phase voltage drop.
- Two-phase voltage drop.
- Three-phase 50% voltage drop.

Pass conditions:

- Load voltage support remains meaningful during fault.
- Winding/converter currents do not exceed the declared limit.
- Vdc remains inside safe bounds.
- Model recovers after fault clearing.

This test should not be called "full FRT" unless it is checked against an explicit grid-code curve and current-injection requirement. It is a model-completion and controller-stability gate.

### Test 8: Passive Fallback

Scenario:

- Disable PWM/converters or bypass series injection.

Pass conditions:

- Model behaves like a conventional transformer.
- No DC-link instability causes the AC network to fail.

## 8. What This Means for the Current Tutorial Model

Current status:

- The primary-side series path is closer to Song Fig. 2-4 after the previous edit.
- The shared DC-link concept exists.
- Regulating converter has H-bridge/PWM structure.
- Energy converter exists but is not yet final.

Not yet aligned:

- `main` needs to expose W1/W2/W3 clearly.
- `EnergyConverter` must be connected to W3, not to a primary-bus proxy.
- `PrimaryEnergyCoupling` should be renamed/reworked as `TertiaryEnergyWinding` or absorbed into the main transformer subsystem.
- Energy converter should evolve from average DC support to a three-phase bridge with dq current control and DC-link voltage outer loop.
- A persistent test script should be created for Tests 0-3 first, then expanded to Tests 4-8.

Recommended next step:

```text
Step 16: Rebuild/rename main as ElectromagneticTransformer
         expose W1/W2/W3 ports
         connect EnergyConverter to W3 only
         run Test 0 + Test 1
```

## 9. Sources Used

- Song Xing, "Research on Multi-Mode Control Strategy of Hybrid Power Transformer", master's thesis, 2023. Local copy: `C:/Users/m1391/Zotero/storage/UQJ85J4S/混合式电力变压器多工作模式控制策略研究_宋幸.pdf`
- A. Carreno et al., "Configurations, Power Topologies and Applications of Hybrid Distribution Transformers", Energies, 2021. https://www.mdpi.com/1996-1073/14/5/1215
- Y. Liu et al., "Power Flow Analysis and DC-link Voltage Control of Hybrid Distribution Transformer", IEEE Transactions on Power Electronics, 2021. Zotero key: `9HH5A8AI`, DOI: `10.1109/TPEL.2021.3077452`
- J. Hu et al., "Operation and Hierarchical Coordination Control of Integrated Hybrid Distribution Transformer under Grid Fault Conditions", IEEE Transactions on Power Electronics, 2024. Zotero key: `I53BGB8K`, DOI: `10.1109/TPEL.2024.3388721`
- Y. Liu et al., "Compound Control System of Hybrid Distribution Transformer", IEEE Transactions on Industry Applications, 2020. Cited by Liu 2021 and Hu 2024 as a reference topology/control baseline.
- S. Bala et al., "Hybrid Distribution Transformer: Concept Development and Field Demonstration", IEEE ECCE, 2012. Cited by Liu 2021 as an early field-demonstration reference.
