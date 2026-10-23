# Spark executor OOM on the shared cluster

**Symptom.** Jobs fail with `ExecutorLostFailure` or `java.lang.OutOfMemoryError:
Java heap space`. Usually appears after a change to driver or executor memory,
or after an upstream table grows.

## Triage

1. Confirm it is memory and not a lost node. In the Spark UI, open the failed
   stage and check whether executors died with OOM or were simply removed.
2. Check `spark.executor.memory` and `spark.executor.memoryOverhead`. On the
   shared cluster the overhead defaults to 10% of executor memory, which is too
   low for anything doing wide shuffles.
3. Look at the shuffle read size for the failing stage. Above roughly 20 GB per
   executor, the problem is partitioning, not heap size.

## Fix

- Raise `spark.executor.memoryOverhead` to 20% before raising
  `spark.executor.memory`. Overhead exhaustion is the more common cause and
  raising heap alone makes the job more expensive without fixing it.
- Increase `spark.sql.shuffle.partitions` so each task handles less data. The
  cluster default of 200 is too low for tables over about 500 GB.
- If a single key dominates, salt the join key rather than scaling the cluster.

## Escalate

Page the on-call data platform engineer if the job is a tier-1 pipeline and
the above has not resolved it within 30 minutes.
