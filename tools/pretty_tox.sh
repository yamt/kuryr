#! /bin/sh

SUBUNIT_ARGS=$@

exec 3>&1
status=$(exec 4>&1 >&3; ( python setup.py testr --slowest --testr-args="$TESTR_ARGS --subunit $SUBUNIT_ARGS"; echo $? >&4 ) | tee $(dirname $0)/test-results | $(dirname $0)/subunit-trace.py -f); (subunit2junitxml --no-passthrough $(dirname $0)/test-results > $(dirname $0)/test-results.xml) && exit $status
