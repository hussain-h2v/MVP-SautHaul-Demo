# Phase 8 facility scheduling comparison

- Facility: `FAC-JAI-01`
- As of: `2026-08-04T09:00:00+05:30`
- Competing shipments: `SHP1002`, `SHP1003`, `SHP1004`, `SHP1006`
- Rule: Assign the earliest feasible dock start first; for equal starts, prefer higher priority, then earlier ETA and shipment ID. Compare proposals by priority-weighted waiting minutes (wait minutes × priority weight), total waiting minutes, and missed appointments.

## Fixed in-progress work

- `SHP1002` remains at dock `D2`; estimated finish `2026-08-04T09:18:00+05:30`; rescheduled: no.

## Scorecard

| Proposal | Priority-weighted wait (min) | Total wait (min) | Average wait (min) | Missed appointments |
|---|---:|---:|---:|---:|
| Earliest start + priority tie-break | 40.0 | 40.0 | 13.3 | 2 |
| FCFS baseline | 40.0 | 40.0 | 13.3 | 2 |

## Proposed order

### Priority-aware

- `SHP1003` → dock `D1`, 09:00–09:45, wait 40.0 min, missed current appointment: False.
- `SHP1004` → dock `D3`, 09:20–10:20, wait 0.0 min, missed current appointment: True.
- `SHP1006` → dock `D4`, 11:20–12:05, wait 0.0 min, missed current appointment: True.

### FCFS

- `SHP1003` → dock `D1`, 09:00–09:45, wait 40.0 min, missed current appointment: False.
- `SHP1004` → dock `D3`, 09:20–10:20, wait 0.0 min, missed current appointment: True.
- `SHP1006` → dock `D4`, 11:20–12:05, wait 0.0 min, missed current appointment: True.

## Interpretation

The rule is a transparent greedy proposal, not a capacity reservation or a global optimizer. It selects the earliest feasible start and uses shipment priority only when feasible starts tie; ETAs, dock compatibility, and the fixed in-progress unload constrain the order. The scorecard shows the priority-weighted wait (`wait minutes × priority weight`), total and average wait, and missed appointments separately rather than hiding trade-offs in one arbitrary composite number.

On this snapshot the competing schedules are expected to be similar because the two waiting trucks are ready at different times and SHP1006 has a later ETA. The rule should not claim a benefit where the measured scorecard shows none.

CP-SAT was not added: after fixing SHP1002 there are only three movable shipments in this comparison, and the transparent rule ties the FCFS scorecard. This example provides no evidence that a heavier solver would improve the result.
