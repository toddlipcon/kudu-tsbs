#!/usr/bin/env python

from pprint import pprint
from tempfile import NamedTemporaryFile
import json
import logging
import fnmatch
import click
import os
import subprocess
import signal
import pdb

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

def _gen_queries(system, workload, count):
  sys = SYSTEMS[system]
  return subprocess.Popen(
      [TSBS_GENERATE_QUERIES] + COMMON_ARGS +
      ["--format={}".format(sys['format']),
       "--query-type={}".format(workload),
       "--queries={}".format(count)],
      stdout=subprocess.PIPE)


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
    gen_queries = _gen_queries(system, workload, workers * _query_count_multiple(workload))
    runner = os.path.join(GOROOT, "bin",
        "tsbs_run_queries_{}".format(sys['format']))
    subprocess.check_call(
        [runner,
         "--workers={}".format(workers),
         "--urls={}".format(sys.get('query_url', sys.get('url'))),
         "--print-interval=0"],
        stdin=gen_queries.stdout,
        stderr=subprocess.STDOUT)
    gen_queries.communicate()
    print("\n\n")

@cli.command()
@click.option("--workloads", default="*")
def test(workloads):
  """ Check that influx and kudu have matching results for all workloads """
  failed = []
  for workload in fnmatch.filter(WORKLOADS, workloads):
    logging.info("Testing workload {}".format(workload))
    responses = {}
    for system in ['kudu', 'influx']:
      sys = SYSTEMS[system]
      gen_queries = _gen_queries(system, workload, 1)
      runner = os.path.join(GOROOT, "bin", "tsbs_run_queries_influx")
      output = subprocess.check_output(
          [runner,
           "--urls={}".format(sys.get('query_url', sys.get('url'))),
           "--print-interval=0",
           "--print-responses"],
          stdin=gen_queries.stdout,
          stderr=subprocess.STDOUT)
      prefix = "ID 0:"
      # BUG: every line of the response is prefixed with "ID 0" except for the
      # leading '{' so we have to put that in manually!
      response = "{" + "\n".join(l[len(prefix):] for l in output.splitlines()
                           if l.startswith(prefix))
      response = json.loads(response)
      # kudu-tsdb column names differ from influx, so just diff the count, not the
      # names.
      for r in response['response']['results']:
        for s in r['series']:
          s['column_count'] = len(s['columns'])
          del s['columns']
      responses[system] = response
    with NamedTemporaryFile(prefix="influx") as influx_tmp:
      pprint(responses['influx'], influx_tmp)
      influx_tmp.flush()
      with NamedTemporaryFile(prefix="kudu") as kudu_tmp:
        pprint(responses['kudu'], kudu_tmp)
        kudu_tmp.flush()

        try:
          subprocess.check_output(['diff', '-U3', influx_tmp.name, kudu_tmp.name])
        except subprocess.CalledProcessError as e:
          print("results differed for workload {}:".format(workload))
          print("diff:")
          print(e.output)
          print("\n\nresponses:")
          pprint(responses)
          failed.append(workload)
  if failed:
    print("\nFollowing workloads failed:\n" + "\n".join(failed))
    return 1

def _debug(*args):
  pdb.set_trace()

if __name__ == "__main__":
  logging.basicConfig(level=logging.INFO)
  signal.signal(signal.SIGQUIT, _debug)
  cli()
