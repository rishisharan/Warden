# TCK-104 — Webhook endpoint returning 500 errors
Customer: Voss Manufacturing (support rep: T. Reyes)
Opened: 2026-09-14

Customer's integration team reports our /webhooks/events endpoint has been
intermittently returning 500s since yesterday's deploy. About 8% of their
webhook deliveries are failing and need manual replay.

Resolution: Escalated to engineering on-call. Root cause traced to a null
pointer in the new event-filtering code path. Hotfix deployed 2026-09-14
18:40 UTC. Customer's failed webhooks were replayed from the dead-letter
queue.
Status: Closed
