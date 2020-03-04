#!/usr/bin/env python

import logging
import click
import os
import subprocess

GOROOT=os.path.join(os.environ.get('GOROOT', os.path.expanduser("~/go")))
TSBS_GENERATE_DATA=os.path.join(GOROOT, "bin", "tsbs_generate_data")


SYSTEMS=dict(
  kudu=dict(
    loader="tsbs_load_influx",
    extra_load_flags=["--do-create-db=0"],
    format="influx",
    url="http://localhost:4242",
  ),
  influx=dict(
    loader="tsbs_load_influx",
    format="influx",
    url="http://localhost:8086",
  ),
)



SCALE=4000
TS_START="2019-04-01T00:00:00Z"
TS_END="2019-04-04T00:00:00Z"
LOAD_WORKERS=8

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
    "--use-case=cpu-only",
    "--seed=123",
    "--scale={}".format(SCALE),
    "--timestamp-start={}".format(TS_START),
    "--timestamp-end={}".format(TS_END),
    "--log-interval=10s",
    "--format={}".format(system)]
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
  loader = os.path.join(GOROOT, "bin", SYSTEMS[system]['loader'])
  zstd = subprocess.Popen(["zstdcat", input_zst_path], stdout=subprocess.PIPE)
  cmd=[loader,
    "--gzip=0",
    "--reporting-period=1s",
    "--workers={}".format(LOAD_WORKERS),
    "--urls={}".format(SYSTEMS[system]['url'])]
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

if __name__ == "__main__":
  logging.basicConfig(level=logging.INFO)
  cli()
