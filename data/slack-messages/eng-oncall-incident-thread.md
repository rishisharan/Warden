# #eng-oncall — Thread (Confidential — Manager Access)
Channel: #eng-oncall (Restricted — manager access only)

**on-call eng** (6:12 PM): webhook 500s traced to a null pointer in the
new event-filtering path from yesterday's deploy. ~8% of deliveries
failing for affected customers, Voss Manufacturing (TCK-104) is the loudest
so far.

**on-call eng** (6:38 PM): hotfix deployed, replaying dead-letter queue
now. Also worth noting this is incident #3 this quarter for Northfield
Analytics specifically — that's the SLA threshold per section 4.2, flagging
for accounts team.
