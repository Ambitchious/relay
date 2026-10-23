# Trino queries rejected by the coordinator

**Symptom.** Queries fail immediately with `QUERY_REJECTED` or
`NO_NODES_AVAILABLE`, usually during a Hive metastore failover.

## Triage

1. Check coordinator health and the number of registered workers.
2. Check whether the metastore is mid-failover. During failover the
   coordinator cannot resolve table metadata and rejects rather than queues.
3. Confirm the resource group is not at its concurrency limit.

## Fix

- Wait for failover to complete; it is normally under five minutes. Retrying
  immediately makes the queue worse.
- If workers are missing, check for a rolling deploy in progress.
- For a resource group limit, move ad-hoc queries to the `adhoc` group rather
  than raising the limit on `etl`.

## Escalate

Page on-call if the coordinator has fewer than half its expected workers for
more than ten minutes.
