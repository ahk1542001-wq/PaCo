# Scheduler / Publisher — Department 2: Digital Marketing

## Owns

- Queueing gate-approved posts for publication.
- Recording the queue ID of every scheduled item.

## Stops

- Refuses anything that is not in `approved` status. The refusal
  is enforced in code, not by convention.
- Creates or alters no content.

## Self-check

- Every queued item carries approved status and a queue ID.

## Skills

None assigned; no evaluated pack covers scheduling.

## Tools

Buffer API (dry-run until the owner's live key is connected) or
Postiz.

## Model

None.
