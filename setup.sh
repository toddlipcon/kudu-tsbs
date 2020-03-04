#!/bin/bash

DIR=$(readlink -f $(dirname $BASH_SOURCE))
cd $DIR

GO_URL=https://dl.google.com/go/go1.14.linux-amd64.tar.gz
GO_TGZ=$(basename $GO_URL)

INFLUX_URL=https://dl.influxdata.com/influxdb/releases/influxdb-1.7.10_linux_amd64.tar.gz
INFLUX_TGZ=$(basename $INFLUX_URL)
INFLUX_DIR=influx-root

GOROOT=$DIR/go

export PATH=$GOROOT/bin:$PATH

install_go() {
  if [ ! -f $GO_TGZ ]; then
    wget -C $GO_URL
  fi
  
  tar xzf $GO_TGZ
}

install_tsbs() {
  echo installing tsbs..
  go get github.com/timescale/tsbs/...
}

install_influx() {
  echo installing influx...
  tmp=$(mktemp -d -p .)
  if [ ! -d $INFLUX_DIR ]; then
    wget -C $INFLUX_URL
    tar xzf $INFLUX_TGZ --strip-components=2 -C $tmp
  fi
  mv $tmp $INFLUX_DIR
}

setup_venv() {
  virtualenv env
  env/bin/pip install -r requirements.txt
}

sudo apt install virtualenv
if [ ! -d $GOROOT ]; then
 install_go
fi
install_tsbs
install_influx
setup_venv
