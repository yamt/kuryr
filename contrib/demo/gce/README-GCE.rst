=========================
Kubernetes + Midonet demo
=========================

This document will guide the user in setting a Kubernetes cluster with the
Kuryr API watcher backed by a Neutron MidoNet deployment in GCE.

The demo deployment will consist of the following machines:

- OSt controller: It will run Keystone, Neutron and MidoNet cluster (with
  Zookeeper).
- K8s controller: It will run Kubernetes and the Kuryr API watcher.
- K8s worker1: It will run Kubelet and the MidoNet agent.
- K8s worker2: It will run Kubelet and the MidoNet agent.

Creating an instance group
--------------------------

In order to keep things tidy, it is best to create an instance group with only
the instances that belong to this deployment::

    $ gcloud compute --project "my_gce_project_name" instance-groups \
      unmanaged create "demo" --zone "us-east1-b" \
      --description "my midonet and k8s demo environment"

Creating a network
------------------

Let's create a network for the GCE instances that we'll use as the underlay for
this deployment::

    $ gcloud compute networks create --range 10.142.0.0/24 demo

Once it is created, we should allow ssh and mosh access to the instances in the
deployment::

    $ gcloud compute firewall-rules create terminal --network demo --allow \
      tcp:22,udp:60000-61000

We should allow internal access too::

    $ gcloud compute firewall-rules create demo-allow-internal \
      --network demo --allow tcp:1-65535,udp:1-65535 \
      --source-ranges "10.142.0.0/24"

OSt controller
--------------

Creating the instance
~~~~~~~~~~~~~~~~~~~~~

In order to setup the Keystone and Neutron for usage with MidoNet, we are going
to create an Ubuntu 14.04 instance that will use devstack to start the
necessary services::

    $ gcloud compute --project "my_gce_project_name" instances create \
      "ost-controller" --zone "us-east1-b" \
      --custom-memory 16GiB --custom-cpu 4 \
      --network "demo" --can-ip-forward \
      --image-project "ubuntu-os-cloud" --image-family "ubuntu-1404-lts" \
      --boot-disk-size "200" \
      --private-network-ip 10.142.0.2 \
      --maintenance-policy "MIGRATE"

Let's add it to the instance group::

    $ gcloud compute --project "my_gce_project_name" instance-groups unmanaged \
      add-instances "demo" --zone "us-east1-b" \
      --instances "ost-controller"

Then we enter the instance to set it up::

    $ gcloud compute ssh --zone us-east1-b "ost-controller"

Setting it up
~~~~~~~~~~~~~

In order to set it up, let's do::

    $ sudo apt-get update
    $ sudo apt-get install -y git
    $ git clone https://github.com/openstack-dev/devstack
    $ pushd devstack
    $ cat >> local.conf << 'EOF'
    [[local|localrc]]
    OFFLINE=No
    RECLONE=No

    ENABLED_SERVICES=""

    Q_PLUGIN=midonet
    enable_plugin networking-midonet http://github.com/openstack/networking-midonet.git
    MIDONET_PLUGIN=midonet_v2
    MIDONET_CLIENT=midonet.neutron.client.api.MidonetApiClient
    MIDONET_USE_ZOOM=True
    Q_SERVICE_PLUGIN_CLASSES=midonet_l3
    NEUTRON_LBAAS_SERVICE_PROVIDERV1="LOADBALANCER:Midonet:midonet.neutron.services.loadbalancer.driver.MidonetLoadbalancerDriver:default"

    # hack for getting to internet from the containers
    sudo iptables -t nat -A POSTROUTING -s 172.24.4.1/24 -d 0.0.0.0/0 -j MASQUERADE

    # Credentials
    ADMIN_PASSWORD=pass
    DATABASE_PASSWORD=pass
    RABBIT_PASSWORD=pass
    SERVICE_PASSWORD=pass
    SERVICE_TOKEN=pass

    enable_service q-svc
    enable_service q-lbaas
    enable_service neutron
    enable_service key
    enable_service mysql
    enable_service rabbit
    enable_service horizon

    [[post-config|$NEUTRON_CONF_DIR/neutron_lbaas.conf]]
    [service_providers]
    service_provider = LOADBALANCER:Haproxy:neutron_lbaas.services.loadbalancer.drivers.haproxy.plugin_driver.HaproxyOnHostPluginDriver:default
    service_provider = LOADBALANCER:Midonet:midonet.neutron.services.loadbalancer.driver.MidonetLoadbalancerDriver

    # Log all output to files
    LOGFILE=$HOME/devstack.log
    SCREEN_LOGDIR=$HOME/logs
    EOF

Let's stack it::

    $ ./stack.sh

Once it finishes successfully, in order to verify that the haproxy load
balancer agent that we use for services is up and running, we source the
credentials and perform a neutron command::

    $ source openrc admin admin
    $ neutron agent-list -c agent_type -c host -c alive -c admin_state_up

    +--------------------+----------------+-------+----------------+
    | agent_type         | host           | alive | admin_state_up |
    +--------------------+----------------+-------+----------------+
    | Loadbalancer agent | ost-controller | :-)   | True           |
    +--------------------+----------------+-------+----------------+

Now we proceed with the MidoNet tunnel zone::

    $ midonet-cli -e tunnel-zone create name demo type vxlan
    282d7315-382c-4736-a567-afa57009d942

With the uuid for the tunnel zone that was returned, we should proceed to
add the ost-controller host to the tunnel zone. This will allow the haproxy
loadbalancer agent to communicate with the pods in the worker instances.

Check your host uuid::

    $ midonet-cli -e host list
    host bd6a3fe1-a655-49af-bd77-d3b2a5356af4 name ost-controller alive true addresses fe80:0:0:0:0:11ff:fe00:1101,169.254.123.1,fe80:0:0:0:4001:aff:fe8e:2,10.142.0.2,172.17.0.1,fe80:0:0:0:fc6c:38ff:fe47:f864,127.0.0.1,0:0:0:0:0:0:0:1,fe80:0:0:0:0:11ff:fe00:1102,fe80:0:0:0:c4fd:6dff:fe99:7a6d,172.19.0.2 flooding-proxy-weight 1 container-weight 1 container-limit no-limit enforce-container-limit false

Then add it to the tunnel zone, using the internal IP::

    $ midonet-cli -e tunnel-zone 282d7315-382c-4736-a567-afa57009d942 add \
      member host bd6a3fe1-a655-49af-bd77-d3b2a5356af4 address 10.142.0.2
    zone 282d7315-382c-4736-a567-afa57009d942 host bd6a3fe1-a655-49af-bd77-d3b2a5356af4 address 10.142.0.2

Kubernetes controller
---------------------

Back again out of the ost-controller instance, we need to deploy a CoreOS
cluster in GCE.

We will use
`cloud-config-master.yaml <https://github.com/midonet/kuryr/blob/k8s/contrib/demo/gce/cloud-config-master.yaml>`_.
If you have set up the network range differently or picked a different
private-network-ip for the ost-controller, you should adjust the file
accordingly.

Then create the controller instance::

    $ gcloud compute --project "my_gce_project_name" instances create \
      "k8s-controller" --zone "us-east1-b" \
      --custom-memory 8GiB --custom-cpu 2 \
      --network "demo" \
      --image-project "coreos-cloud" --image-family "coreos-stable" \
      --boot-disk-size "200" \
      --maintenance-policy "MIGRATE" \
      --private-network-ip 10.142.0.3 \
      --metadata-from-file user-data=cloud-config-master.yaml
    Created
    [https://www.googleapis.com/compute/v1/projects/my_gce_project_name/zones/us-east1-b/instances/k8s-controller].
    NAME            ZONE        MACHINE_TYPE               PREEMPTIBLE
    INTERNAL_IP  EXTERNAL_IP      STATUS
    k8s-controller  us-east1-b  custom (2 vCPU, 8.00 GiB)
    10.142.0.3   104.196.134.170  RUNNING

Note, that until the worker1 and worker2 nodes, which are part of the three
node Etcd cluster, are up with their etcd3.service running, the k8s-controller
Kubernetes services will not start, as they depend upon having a healthy Etcd
cluster. This does not mean that the worker nodes should be started before the
master, as soon as the worker nodes start and get their etcd3.service active,
the master will resume starting its Kubernetes services.

Worker nodes
------------

We will use
`cloud-config-worker1.yaml <https://github.com/midonet/kuryr/blob/k8s/contrib/demo/gce/cloud-config-worker1.yaml>`_
and
`cloud-config-worker2.yaml <https://github.com/midonet/kuryr/blob/k8s/contrib/demo/gce/cloud-config-worker2.yaml>`_.
Both files are basically equal except for the UUID and the etcd2 parameters,
which need to differ for both etcd2 and MidoNet agent to work. If you have set
up the network range differently or picked a different private-network-ip for
the ost-controller or k8s-controller, you should adjust the files accordingly.

If you are going to deploy more worker nodes, we recommend you make extra
worker yaml files and update the initial-cluster, UUID and etcd2 name values.
In order to generate a new uuid for the UUID value, you can do::

    $ uuidgen
    4d249833-30e5-40db-bfc8-46d5bcc2b780

After this explanation about having more worker nodes, we can create the
instances::

    $ gcloud compute --project "my_gce_project_name" instances create \
      "k8s-worker1" --zone "us-east1-b" \
      --custom-memory 12GiB --custom-cpu 6 \
      --network "demo" \
      --image-project "coreos-cloud" --image-family "coreos-stable" \
      --boot-disk-size "200" \
      --maintenance-policy "MIGRATE" \
      --private-network-ip 10.142.0.4 \
      --metadata-from-file user-data=cloud-config-worker1.yaml
    Created
    [https://www.googleapis.com/compute/v1/projects/my_gce_project_name/zones/us-east1-b/instances/k8s-worker1].
    NAME            ZONE        MACHINE_TYPE               PREEMPTIBLE
    INTERNAL_IP  EXTERNAL_IP      STATUS
    k8s-worker1  us-east1-b  custom (2 vCPU, 8.00 GiB)
    10.142.0.4   104.196.134.170  RUNNING

    $ gcloud compute --project "my_gce_project_name" instances create \
      "k8s-worker2" --zone "us-east1-b" \
      --custom-memory 12GiB --custom-cpu 6 \
      --network "demo" \
      --image-project "coreos-cloud" --image-family "coreos-stable" \
      --boot-disk-size "200" \
      --maintenance-policy "MIGRATE" \
      --private-network-ip 10.142.0.5 \
      --metadata-from-file user-data=cloud-config-worker2.yaml
    Created
    [https://www.googleapis.com/compute/v1/projects/my_gce_project_name/zones/us-east1-b/instances/k8s-worker2].
    NAME            ZONE        MACHINE_TYPE               PREEMPTIBLE
    INTERNAL_IP  EXTERNAL_IP      STATUS
    k8s-worker2  us-east1-b  custom (2 vCPU, 8.00 GiB)
    10.142.0.5   104.196.134.170  RUNNING

Now that the instances have launched, we should add these two nodes to the
MidoNet tunnel zone. In order to do that, we should ssh to the ost-controller
node and do::

    $ midonet-cli -e host list
    $ midonet-cli -e tunnel-zone 282d7315-382c-4736-a567-afa57009d942 add \
      member host 2a3b9405-818a-496b-bf75-9a53c9c45b0e address 10.142.0.4
    zone 282d7315-382c-4736-a567-afa57009d942 host 2a3b9405-818a-496b-bf75-9a53c9c45b0e address 10.142.0.4
    $ midonet-cli -e tunnel-zone 282d7315-382c-4736-a567-afa57009d942 add \
      member host 80870762-6bee-4146-bfd8-fb5ae3f5477a address 10.142.0.5
    zone 282d7315-382c-4736-a567-afa57009d942 host 80870762-6bee-4146-bfd8-fb5ae3f5477a address 10.142.0.5

Checking health
---------------

If you are not in the k8s-controller get into it::

    $ gcloud compute ssh --zone us-east1-b "k8s-controller"

Then check that the nodes are up::

    $ kubectl get nodes
    NAME                                            STATUS    AGE
    k8s-worker1.c.my_gce_project_name.internal      Ready     13h
    k8s-worker2.c.my_gce_project_name.internal      Ready     13h

If you see both of your workers, that's good. Then we check that all the
services are running::

    $ sudo systemctl status kube-scheduler
    ● kube-scheduler.service - Kubernetes Scheduler
       Loaded: loaded (/etc/systemd/system/kube-scheduler.service; static;
       vendor preset: disabled)
          Active: active (running) since Wed 2016-07-06 17:13:38 UTC; 20h ago
    $ sudo systemctl status kube-controller-manager
    ● kube-controller-manager.service - Kubernetes Controller Manager
       Loaded: loaded (/etc/systemd/system/kube-controller-manager.service; static; vendor preset: disabled)
       Active: active (running) since Wed 2016-07-06 17:13:33 UTC; 20h ago
    $ sudo systemctl status kuryr-watcher
    ● kuryr-watcher.service - Kuryr Kubernetes API watcher
       Loaded: loaded (/etc/systemd/system/kuryr-watcher.service; static; vendor preset: disabled)
       Active: active (running) since Wed 2016-07-06 21:46:02 UTC; 15h ago

If you see it as active, even though some ExecStartPre or ExecStop processes
may be exited in failure, it is in a healthy state. This is because these
failed tasks are there to clean up things and will fail if there is nothing to
clean up.

Running your first containers
-----------------------------

With all the cluster healthy, let's run our first containers::

    $ kubectl run --image nginx --replicas 2 my-nginx
    deployment "my-nginx" created

After a moment, they should show as running::

    $ kubectl get pods
    NAME                        READY     STATUS    RESTARTS   AGE
    my-nginx-1830394127-mazlo   1/1       Running   0          24s
    my-nginx-1830394127-uyh8d   1/1       Running   0          24s

Once they is running, we can get their IPs::

    $ kubectl exec my-nginx-1830394127-mazlo -- ip -4 a show dev eth0
    15: eth0@if16: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000
        inet 192.168.0.14/24 scope global eth0
           valid_lft forever preferred_lft forever
    $ kubectl exec my-nginx-1830394127-uyh8d -- ip -4 a show dev eth0
    21: eth0@if22: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000
        inet 192.168.0.6/24 scope global eth0
           valid_lft forever preferred_lft forever

Having seen the ips, let's verify connectivity::
    $ kubectl exec my-nginx-1830394127-uyh8d ping 192.168.0.14

Exposing your services to the external world
--------------------------------------------

The containers deployed in the previous step are only accessible inside the Kubernetes
cluster. To make them accessible to the outside world, you need to expose it using an
external ip provided by Neutron.

First from the ost-controller instance create a floating ip in the external network
defined by neutron. To do so, first identify the appropiated network::

    $ neutron net-list -c name -c router:external
     +----------------------------+-----------------+
     | name                       | router:external |
     +----------------------------+-----------------+
     | default                    | False           |
     | kube-system                | False           |
     | raven-default-service      | False           |
     | mn-uplink-net              | False           |
     | public                     | True            | <-- external network
     | private                    | False           |
     | raven-default-cluster-pool | False           |
     +----------------------------+-----------------+

Now request a floating ip from the external network::

    $ neutron floating-ip-create public
    Created a new floatingip:
    +---------------------+--------------------------------------+
    | Field               | Value                                |
    +---------------------+--------------------------------------+
    | description         |                                      |
    | fixed_ip_address    |                                      |
    | floating_ip_address | 172.24.4.5                           |
    | floating_network_id | f4e34da7-1186-4ebf-9d23-cc02f1930d17 |
    | id                  | e992bcc6-1fec-4be6-a677-d499ec770815 |
    | port_id             |                                      |
    | router_id           |                                      |
    | status              | ACTIVE                               |
    | tenant_id           | 3df6bffe3c754efeaeaab8d01b552e1c     |
    +---------------------+--------------------------------------+

In order of this floating ip to be associated with an ip from the Kubernetes cluster,
it is necessary that the two networks to be reachable. Ensure the Kubernetes cluster's
router has a link to the external network::

    $ neutron router-list
    +--------------------------+----------------------+---------------------------+
    | id                       | name                 | external_gateway_info     |
    +--------------------------+----------------------+---------------------------+
    | a35a04af-fe2b-           | raven-default-router | {"network_id":            |
    | 48a2-9c05-1b99713eea63   |                      | "f4e34da7-1186-4ebf-      |
    |                          |                      | 9d23-cc02f1930d17",       |
    |                          |                      | "enable_snat": true,      |
    |                          |                      | "external_fixed_ips":     |
    |                          |                      | [{"subnet_id": "9f9600d3- |
    |                          |                      | 30f1-4c29-8df5-0f7fb54289 |
    |                          |                      | 1d", "ip_address":        |
    |                          |                      | "172.24.4.2"}]}           |
    +--------------------------+----------------------+---------------------------+

If the external_gateway_info shown is null, you must create a link to the public
network::
    $ neutron router-set-gateway raven-default-router public

Now, from the k8s-controller instance, create a service to expose the pods and associate
the floating ip obtained from Neutron::

    $ kubectl expose deployment my-nginx --external-ip 172.24.4.5 --port=80
    service "my-nginx" exposed

    $ kubectl get services my-nginx
    kubectl get services
    NAME         CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
    my-nginx     10.0.0.137   172.24.4.5    80/TCP    11s

The service should now be accessible from the ost-controller instance::

   $ wget 172.24.4.5 -nv --method=HEAD
     2016-07-27 13:42:36 URL: http://172.24.4.9/ 200 OK


Manual service expossure
------------------------

Find the neutron VIP associated with the service::

    $ neutron lb-vip-list -c id -c name -c address

    +--------------------------------------+------------+------------+
    | id                                   | name       | address    |
    +--------------------------------------+------------+------------+
    | a42a0857-becb-435f-89f5-2ba5635dfee9 | my-nginx   | 10.0.0.218 |
    | b8c0b52a-bfd8-4116-a4f3-d923c0a4faf2 | my-nginx-2 | 10.0.0.98  |
    | df994074-e3a3-4460-a863-e58ad6ed0d1f | my-nginx-3 | 10.0.0.177 |
    +--------------------------------------+------------+------------+

Find the port id for the VIP::

    $ neutron lb-vip-show a42a0857-becb-435f-89f5-2ba5635dfee9
    +---------------------+--------------------------------------+
    | Field               | Value                                |
    +---------------------+--------------------------------------+
    | address             | 10.0.0.218                           |
    | admin_state_up      | True                                 |
    | connection_limit    | -1                                   |
    | description         |                                      |
    | id                  | a42a0857-becb-435f-89f5-2ba5635dfee9 |
    | name                | my-nginx                             |
    | pool_id             | 84b7fbec-836a-40e2-a629-2c98cb86bbf1 |
    | port_id             | 52275b78-2eaa-49f0-be4b-5c23f4ee9188 |
    | protocol            | TCP                                  |
    | protocol_port       | 80                                   |
    | session_persistence |                                      |
    | status              | ACTIVE                               |
    | status_description  |                                      |
    | subnet_id           | f1ea012f-88e7-4901-8258-0ccaafa528f0 |
    | tenant_id           | 3df6bffe3c754efeaeaab8d01b552e1c     |
    +---------------------+--------------------------------------+

Assign the floating ip to the vip::

    $ neutron floatingip-associate e992bcc6-1fec-4be6-a677-d499ec770815 \
      52275b78-2eaa-49f0-be4b-5c23f4ee9188
