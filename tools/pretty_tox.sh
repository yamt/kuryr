#! /bin/sh

TESTRARGS=$1

exec 3>&1
status=$(exec 4>&1 >&3; ( python setup.py testr --slowest --testr-args="--subunit $TESTRARGS"; echo $? >&4 ) | tee $(dirname $0)/test-results | $(dirname $0)/subunit-trace.py -f); (subunit2junitxml $(dirname $0)/test-results > $(dirname $0)/test-results.xml) && exit $status
