#!/usr/bin/env python

import logging
import fnmatch
import click
import os
import subprocess

GOROOT=os.path.join(os.environ.get('GOROOT', os.path.expanduser("~/go")))
TSBS_GENERATE_DATA=os.path.join(GOROOT, "bin", "tsbs_generate_data")
TSBS_GENERATE_QUERIES=os.path.join(GOROOT, "bin", "tsbs_generate_queries")


SYSTEMS=dict(
  kudu=dict(
    format="influx",
    url="http://localhost:4242",
    extra_load_flags=[
        "--do-create-db=0",
        "--gzip=0",
    ],
  ),
  influx=dict(
    format="influx",
    url="http://localhost:8086",
    extra_load_flags=[
        "--gzip=0",
    ],
  ),
  victoriametrics=dict(
    format="victoriametrics",
    load_url="http://localhost:8428/write",
    query_url="http://localhost:8428",
    unsupported=["high-cpu-*"],
  ),
)

WORKLOADS=[
  "cpu-max-all-1",
  "cpu-max-all-8",
  "double-groupby-1",
  "double-groupby-5",
  "double-groupby-all",
  "high-cpu-1",
  "high-cpu-all",
  "single-groupby-1-1-1",
  "single-groupby-1-1-12",
  "single-groupby-1-8-1",
  "single-groupby-5-1-1",
  "single-groupby-5-1-12",
  "single-groupby-5-8-1",
  # NOT SUPPORTED:
  #"groupby-orderby-limit",
  # "lastpoint",
]


SCALE=4000
TS_START="2019-04-01T00:00:00Z"
TS_END="2019-04-04T00:00:00Z"
LOAD_WORKERS=8
COMMON_ARGS=[
    "--use-case=cpu-only",
    "--seed=123",
    "--scale={}".format(SCALE),
    "--timestamp-start={}".format(TS_START),
    "--timestamp-end={}".format(TS_END),
]

@click.group()
def cli():
  if not os.path.exists("logs"):
    os.mkdir("logs")
  pass

def generate_data(system, out_path):
  if os.path.exists(out_path):
    logging.info("%s already exists, using existing data", out_path)
    return
  logging.info("generating data for %s", system)
  tmp_path = "{}.tmp".format(out_path)
  zstd = subprocess.Popen(["zstd", "-f", "-o", tmp_path], stdin=subprocess.PIPE)
  cmd=[TSBS_GENERATE_DATA,
    "--log-interval=10s",
    "--format={}".format(system)] + COMMON_ARGS
  try:
    subprocess.check_call(cmd, stdout=zstd.stdin)
    zstd.stdin.close()
    if zstd.wait() != 0:
      raise Exception("zstd failed")
  except:
    if os.path.exists(tmp_path):
      os.unlink(tmp_path)
    raise
  os.rename(tmp_path, out_path)

def tee(path):
  p = subprocess.Popen(["tee", path], stdin=subprocess.PIPE)
  return p.stdin

def load_data(system, input_zst_path):
  sys = SYSTEMS[system]
  loader = os.path.join(GOROOT, "bin", 'tsbs_load_{}'.format(sys['format']))
  zstd = subprocess.Popen(["zstdcat", input_zst_path], stdout=subprocess.PIPE)
  cmd=[loader,
    "--reporting-period=1s",
    "--workers={}".format(LOAD_WORKERS),
    "--urls={}".format(sys.get('load_url', sys.get('url')))]
  cmd += SYSTEMS[system].get('extra_load_flags', [])
  subprocess.check_call(cmd,
      stdin=zstd.stdout,
      stdout=tee("logs/load-{}.txt".format(system)))

@cli.command()
@click.argument("system")
def load(system):
  file_format = SYSTEMS[system]['format']
  data_path = "data-{}-scale-{}.txt.zst".format(file_format, SCALE)
  generate_data(file_format, data_path)
  load_data(system, data_path)

def _query_count_multiple(workload):
  if "single-group" in workload or 'cpu-max' in workload:
    return 1000
  return 1

@cli.command(name="run-queries")
@click.option("--workloads", default="*")
@click.option("--workers", default=1, type=int)
@click.argument("system")
def run_queries(system, workloads, workers):
  sys = SYSTEMS[system]
  for workload in fnmatch.filter(WORKLOADS, workloads):
    logging.info("=== Running workload %s with %s workers", workload, workers)
    if any(fnmatch.fnmatch(workload, p) for p in sys.get('unsupported', [])):
      logging.warn("Not supported!")
      continue
    gen_queries = subprocess.Popen(
        [TSBS_GENERATE_QUERIES] + COMMON_ARGS +
        ["--format={}".format(sys['format']),
         "--query-type={}".format(workload),
         "--queries={}".format(workers * _query_count_multiple(workload))],
        stdout=subprocess.PIPE)
    runner = os.path.join(GOROOT, "bin",
        "tsbs_run_queries_{}".format(sys['format']))
    subprocess.check_call(
        [runner,
         "--workers={}".format(workers),
         "--urls={}".format(sys.get('query_url', sys.get('url'))),
         "--print-interval=0"],
        stdin=gen_queries.stdout)
    gen_queries.communicate()
    print("\n\n")

if __name__ == "__main__":
  logging.basicConfig(level=logging.INFO)
  cli()
