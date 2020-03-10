== Repo setup

```
./setup.sh
```

== Starting daemons:

*influxdb*
```
./sw/influx/usr/bin/influxd 
```

*victoriametrics*

```
./sw/victoriametrics/victoria-metrics-prod  \
  -retentionPeriod 1000 \
  -search.disableCache \
  -search.maxConcurrentRequests=$[$(nproc) * 2] \
  -search.maxQueryDuration=60s
```

*kudu*

```
# Disable replication since we'll only run one tserver.
kudu master run -fs-wal-dir /data/m -default-num-replicas 1 &

# Only retain a few seconds of history to save disk space and IO.
# The other comparable systems don't allow time-travel or differential
# backups.
kudu tserver run -fs-wal-dir /data/ts --tablet_history_max_age_sec=5 &

# We use large batches on load, so allow the web server to accept them
kudu-tsdb -logtostderr -webserver_max_post_length_bytes=100000000
```

*Clickhouse*

Install ClickHouse from APT repos as described on appropriate documentation.
Run it with the default configuration.


== Running benchmarks

Start the appropriate server per above, and then run the following with one of
`influx`, `kudu`, `clickhouse`, or `victoriametrics`:

```
# Set the number of concurrent clients as you like. Twice the number of vCPUs
# seems to maximize throughput for Kudu but has some throughput collapse issues
# on VictoriaMetrics.
NUM_CLIENTS=$[$(nproc)*2]
./env/bin/python -u benchmark.py load influx
./env/bin/python -u benchmark.py run-queries influx --workers=$NUM_CLIENTS
```

Various results will be emitted into `logs/`

== Summarizing results

Simple tabulation can be done on the command line:
```
cat logs/*json | jq '[.workers, .workload, .system, .qps] | @tsv' -r | sort -n | column -t 
```

or use the included jupyter notebook `graphs.ipynb` to generate nice graphs.
