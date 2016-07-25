#!/bin/bash -x

SANDBOX_NAME=${SANDBOX_NAME:-k8s}
INDOCKER="docker exec mnsandbox${SANDBOX_NAME}_keystone_1"
KEYSTONE_IP=$(docker exec mnsandbox${SANDBOX_NAME}_keystone_1 hostname --ip-address)
NEUTRON_IP=$(docker exec mnsandbox${SANDBOX_NAME}_neutron_1 hostname --ip-address)
OS_SERVICE_TOKEN="ADMIN"
OS_SERVICE_ENDPOINT="http://$KEYSTONE_IP:35357/v2.0"

$INDOCKER keystone-manage db_sync >> /dev/null 2>&1

attempts=0
printf "Checking if Keystone API is running...."
until [[ ${attempts} -gt 45 ]] || \
    curl http://${KEYSTONE_IP}:5000 &> /dev/null; do
  attempts=$((attempts+1))
  printf "."
  sleep 5
done

OPENSTACK="$INDOCKER openstack --os-url=$OS_SERVICE_ENDPOINT --os-token=$OS_SERVICE_TOKEN"
$OPENSTACK project create admin
$OPENSTACK role create admin
$OPENSTACK user create admin --password admin
$OPENSTACK role add admin --user admin --project admin

$OPENSTACK project create service --description 'Service apis'
$OPENSTACK user create neutron --password neutron
$OPENSTACK role add admin --user neutron --project service

$OPENSTACK service create --name keystone identity
$OPENSTACK service create --name neutron network

$OPENSTACK endpoint create \
  --publicurl http://$KEYSTONE_IP:5000/v2.0 \
  --internalurl http://$KEYSTONE_IP:5000/v2.0 \
  --adminurl http://$KEYSTONE_IP:35357/v2.0 \
  --region regionOne \
  keystone

$OPENSTACK endpoint create \
  --publicurl http://$NEUTRON_IP:9696 \
  --internalurl http://$NEUTRON_IP:9696 \
  --adminurl http://$NEUTRON_IP:9696 \
  --region regionOne \
  neutron
