#!/bin/bash

# Enforce robustness
set -e

TOX_DIR=$1
ENV_DIR=$2
SRC_DIR=${ENV_DIR}/src
LOG_DIR=${ENV_DIR}/log
MIDONET_SANDBOX_REPO=http://github.com/midonet/midonet-sandbox
MIDONET_SANDBOX_SRC_DIR=${SRC_DIR}/midonet-sandbox/

mkdir -p "${SRC_DIR}"
mkdir -p "${LOG_DIR}"
if [ ! -d "${MIDONET_SANDBOX_SRC_DIR}" ]; then
   git clone "${MIDONET_SANDBOX_REPO}" "${SRC_DIR}/midonet-sandbox" | tee "${LOG_DIR}/git_clone"
fi

# Installing kuryr project
printf "Installing Kuryr..."
pip install . >>"${LOG_DIR}/raven_install" 2>&1
printf " \e[32mDONE\e[39m\n"

# This part should be replaced soon
printf "Installing the midonet sandbox "
printf "(this may take quite time if you have never run the test environment before)..."
pushd "${MIDONET_SANDBOX_SRC_DIR}" \
  && virtualenv -p python2 .venv >>"${LOG_DIR}/sandbox_install" 2>&1 \
  && source .venv/bin/activate >/dev/null 2>&1 \
  && python setup.py install >>"${LOG_DIR}/sandbox_install" 2>&1 \
  && popd
printf " \e[32mDONE\e[39m\n"

printf "Starting the midonet sandbox..."
bash "${TOX_DIR}/scripts/run_sandbox.sh" start >>"${LOG_DIR}/sandbox_log" 2>&1
printf " \e[32mDONE\e[39m\n"

attempts=0
printf "Checking if Keystone API is running...."
until [[ ${attempts} -gt 45 ]] || \
    curl http://$(sandbox-manage sandbox-list --details | grep keystone | awk '{print $10}'):5000 &> /dev/null; do
  attempts=$((attempts+1))
  printf "."
  sleep 5
done
attempts=0
printf "Checking if kubernetes API is running...."
until [[ ${attempts} -gt 45 ]] || curl http://localhost:8080 &> /dev/null; do
  attempts=$((attempts+1))
  printf "."
  sleep 5
done

if [[ ${attempts} -gt 45 ]]; then
  printf " \e[91mFAIL\e[39m\n\n"
  printf "For some reason the Kubernetes API hasn't spawned. Please debugg the error at %s/sandbox_log" "${LOG_DIR}"
  printf "\e[39m\n\n"
  exit 1
fi
printf " \e[32mDONE\e[39m\n"

# Save logs
printf "Saving container logs... "
for i in $(docker ps -a --filter "name=mnsandbox" --format {{.Names}}); do
    docker logs --follow $i > "${LOG_DIR}/${i}.log" 2>&1 &
done

KEYSTONE_IP=$(docker inspect mnsandboxk8s_keystone_1 | grep '"IPAddress"' | cut -d \" -f 4 | uniq)
NEUTRON_IP=$(docker inspect mnsandboxk8s_neutron_1 | grep '"IPAddress"' | cut -d \" -f 4 | uniq)

printf "Run raven... "
export IDENTITY_URL="http://${KEYSTONE_IP}:35357/v2.0"
export OS_URL="http://${NEUTRON_IP}:9696"
export SERVICE_USER="admin"
export SERVICE_TENANT_NAME="admin"
export SERVICE_PASSWORD="admin"
export K8S_API="http://127.0.0.1:8080"
export SERVICE_CLUSTER_IP_RANGE="10.0.0.0/24"
raven --debug >> ${LOG_DIR}/raven_log 2>&1 &
sleep 10  # We have to wait before creating pods on k8s
printf " \e[32mDONE\e[39m\n"
