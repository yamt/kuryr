#!/bin/bash

TOX_DIR=$1
ENV_DIR=$2
LOG_DIR=${ENV_DIR}/log
MIDONET_SANDBOX_SRC_DIR=${ENV_DIR}/src/midonet-sandbox/

source "${MIDONET_SANDBOX_SRC_DIR}/.venv/bin/activate"
printf "Stopping the sandbox..."
sh "${TOX_DIR}/scripts/run_sandbox.sh" stop >>"${LOG_DIR}/sandbox_log" 2>&1
printf " \e[32mDONE\e[39m\n"
deactivate
