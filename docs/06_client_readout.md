# SetuHaul dispatch demo: client readout

## What this demo does

The demo helps a driver report a delay, identify the shipment, and see
compatible dock times. It checks the current booking data before offering
options. An option is not a booking: the system checks the slot again when the
driver selects it, then records a hold or booking through the deterministic
booking engine.

If the driver has more than one active shipment, the system asks which one.
If no safe compatible slot is available, or a situation needs human judgment,
it records an escalation for operations instead of inventing an answer.

## Operating policy

- Capacity is decided by ordinary application rules and the database, not by
  generated text.
- A slot shown to a driver is not reserved. The state changes only when the
  booking engine records a hold or confirmation.
- Slot feasibility accounts for facility, dock and load compatibility,
  availability, and configured operating rules.
- Ambiguous shipment references are clarified. Stale choices are checked
  again. Unsafe or unsupported cases are sent to a coordinator.
- Each outcome is recorded so operations can inspect the booking, escalation,
  and audit history.

## What the demo cannot know

There is no live GPS connection. Arrival estimates come from the driver or the
seeded snapshot; they can be late, incomplete, or wrong. A suggested time is
therefore based on declared information, not a live view of the truck.

The sample database contains only two facilities and a small set of loads and
docks. It demonstrates the rules but does not prove performance at the expected
production volume. The interface is a local demonstration, not a driver
messaging deployment.

## Open operational risk

When capacity is unavailable or the information conflicts, the system hands
the case to a person. That is safer than silently relaxing a rule, but a surge
of delays could create a large coordinator queue. The demo has not measured
coordinator staffing needs, response times, or queue service levels. Those
should be tested with operations before launch.

The recorded scenario ends with escalations and shows no conflicting
allocations in that replay. These are evidence from a small snapshot run, not a
guarantee about every live operating condition.

## Production additions

Before a production rollout, the team should:

1. Connect the driver conversation to a WhatsApp Business webhook and handle
   delivery retries with durable message identifiers.
2. Move shared operational state from the local SQLite file to a managed
   database such as PostgreSQL, using transactions and row-level locking or
   equivalent constraints for competing bookings.
3. Integrate trusted location and ETA sources if available, while retaining
   the source and confidence for every estimate.
4. Define coordinator queue ownership, staffing, response targets, and
   escalation procedures for peak periods.
5. Add operational monitoring, backup and recovery, access controls, and
   end-to-end testing against realistic traffic and data.

These are production requirements to validate, not capabilities claimed by
this demo.
