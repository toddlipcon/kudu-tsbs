#!/bin/bash

set -e
set -x

DIR=$(readlink -f $(dirname $BASH_SOURCE))
cd $DIR

GO_URL=https://dl.google.com/go/go1.14.linux-amd64.tar.gz
GO_TGZ=$(basename $GO_URL)

DL_DIR=$DIR/dl/
SW_DIR=$DIR/sw/

INFLUX_URL=https://dl.influxdata.com/influxdb/releases/influxdb-1.7.10_linux_amd64.tar.gz
INFLUX_TGZ=$(basename $INFLUX_URL)
INFLUX_DIR=sw/influx

VM_URL=https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/v1.34.2/victoria-metrics-v1.34.2.tar.gz
VM_DIR=sw/victoriametrics

GOROOT=$DIR/go

export PATH=$GOROOT/bin:$PATH

install_go() {
  echo installing go...
  if [ ! -f $DL_DIR/go.tgz ]; then
    wget --continue $GO_URL -O $DL_DIR/go.tgz
    tar xzf $DL_DIR/go.tgz -C $SW_DIR
  fi
}

install_tsbs() {
  echo installing tsbs..
  pushd $SW_DIR
  if [ ! -d tsbs ]; then
    git clone https://github.com/victoriametrics/tsbs --branch master2
  fi
  pushd tsbs
  git pull https://github.com/timescale/tsbs --no-edit
  go install ./...
  popd
  popd
}

install_influx() {
  echo installing influx...
  if [ ! -d $INFLUX_DIR ]; then
    tmp=$(mktemp -d -p .)
    wget --continue $INFLUX_URL -O $DL_DIR/influx.tgz
    tar xzf $DL_DIR/influx.tgz --strip-components=2 -C $tmp
    rm -rf $INFLUX_DIR
    mv $tmp $INFLUX_DIR
  fi
}

install_victoriametrics() {
  echo installing victoria metrics...
  if [ ! -d $VM_DIR ]; then
    wget --continue $VM_URL -O $DL_DIR/victoria-metrics.tgz
    mkdir -p $VM_DIR
    tar xzf $DL_DIR/victoria-metrics.tgz -C $VM_DIR
  fi
}

setup_venv() {
  virtualenv env
  env/bin/pip install -r requirements.txt
}

mkdir -p $DL_DIR
mkdir -p $SW_DIR
sudo apt install virtualenv
if [ ! -d $GOROOT ]; then
 install_go
fi
install_tsbs
install_influx
install_victoriametrics
setup_venv
