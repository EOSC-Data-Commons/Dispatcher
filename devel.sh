#!/bin/bash

conf=devel-conf.yaml

trap 'kill $(cat ${pidfile} nginx/temp/fcgi.pid)' EXIT

pidfile=$(yq .nginx.prefix $conf)/$(yq .nginx.pid $conf)

mkdir -p $(yq .git.repos $conf)
mkdir -p nginx/logs nginx/temp

jinja2 nginx/conf/nginx.conf.j2 $conf >nginx/conf/nginx.conf

nginx -c conf/nginx.conf -p $(yq .nginx.prefix $conf)

socket=$(yq .nginx.fcgi $conf)
rm $socket nginx/temp/fcgi.pid
fcgiwrap -s unix:$socket &
echo $! >nginx/temp/fcgi.pid

./driver.py --config $(dirname $0)/devel-conf.yaml --debug
