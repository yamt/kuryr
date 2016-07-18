=========================
Kubernetes + Midonet demo
=========================

This document will guide the user in setting a Kubernetes cluster with the
Kuryr API watcher backed by a Neutron MidoNet deployment in OS.
The following instructions assume you have access to an OpenStack managed
platform which allows access from an extenal network.


The demo deployment will consist of the following machines:

- OSt controller: It will run Keystone, Neutron and MidoNet cluster (with
  Zookeeper).
- K8s controller: It will run Kubernetes and the Kuryr API watcher.
- K8s worker1: It will run Kubelet and the MidoNet agent.
- K8s worker2: It will run Kubelet and the MidoNet agent.


Setup OS credential
-------------------

In a text editor create the file demo-openrc.sh::

   export OS_USERNAME=<username>
   export OS_PASSWORD=<password>
   export OS_TENANT_NAME=<projectName>
   export OS_AUTH_URL=https://<identityHost>:<portNumber>/v2.0

Setup the required credentials and setup for the current session::

   $ . demo-openrc.sh

Additionally, to access the instances via ssh, you need to register a
key pair. If you haven't generate an ssh key pair, generate it first::

  $ssh-keygen

Now register the keys in OS::

  $ nova keypair-add --pub-key ~/.ssh/id_rsa.pub demo-key


Creating a network
------------------

Let's create a network for the instances that we'll use as the underlay for
this deployment::

    $ neutron net-create demo
    $ neutron subnet-create demo --name demo-sub \
      --gateway 10.142.0.254 --dns 8.8.8.8  10.142.0.0/24

Once it is created, we should allow ssh access to the instances in the
deployment, as well as communicaton between them::

    $ neutron security-group-create demo --description "security rules to access demo instances"
    $ nova secgroup-add-rule demo tcp 22 22 0.0.0.0/0
    $ nova secgroup-add-rule demo tcp 1 65535 10.142.0.0/24
    $ nova secgroup-add-rule demo udp 1 65535 10.142.0.0/24
    $ nova securoup-add-rule demo icmp -1 -1 10.142.0.0/24


Allow access from Intenet
-------------------------

We should allow internal access too. We need to create a router::

   $ neutron router-create demo

Now we must create a gateway to the external network::

   $ neutron router-gateway-set demo <external network>

...and create an interface for the router in the instance subnetwork::

   $ neutron router-interface-add demo demo-sub

Later, we will have to assign a floating ip addres from the external network to each controller instance.

OSt controller
--------------

Creating the instance
~~~~~~~~~~~~~~~~~~~~~

In order to setup the Keystone and Neutron for usage with MidoNet, we are going
to create an instance that will use devstack to start the
necessary services.

The instance wil run Ubuntu 14.04. find an appropiated image from your image
repository::

    $ nova image-list

    +--------------------------------------+------------------------------+--------+
    | ID                                   | Name                         | Status |
    +--------------------------------------+------------------------------+--------+
     ...
    | 10a70cf6-28ac-440c-9e76-8b8fdc21c08e | CoreOS 1068.6.0              | ACTIVE |
     ....
    | fc1e589e-3d68-4f36-a76e-c01b9fd5f332 | Ubuntu 14.04.3 20151216      | ACTIVE |
     ...
    +--------------------------------------+------------------------------+--------+

This instance will require 16Gb of memory and 4 VCPP. Check the  list of available flavors and pick the right one::

    $ nova flavor-list

     +----+-----------+-----------+------+-----------+------+-------+-------------+-----------+
     | ID | Name      | Memory_MB | Disk | Ephemeral | Swap | VCPUs | RXTX_Factor | Is_Public |
     +----+-----------+-----------+------+-----------+------+-------+-------------+-----------+
     ...
     | 12 | m2.large  | 8193      | 20   | 0         |      | 2     | 1.0         | True      |
     ...
     |  7 | m2.xlarge | 16384     | 80   | 0         |      | 4     | 1.0         | True      |
     ...
     | 5  | m1.xlarge | 16384     | 80   | 0         |      | 8     | 1.0         | True      |
     ...
     +----+-----------+-----------+------+-----------+------+-------+-------------+-----------+


If none of the listed flavors satisfy these requirements (and you have the permissions) create one::

    $ nova flavor-create demo-large auto 16Gb 200 4

Once you have identified the flavor, create the instance::

    $ nova boot --flavor m2.xlarge --image "Ubuntu 14.04.3 20151216"  \
           --nic net-name=demo,v4-fixed-ip=10.142.0.2 \
           --security-group demo --key-name demo-key ost-controller


Now we have an ip to access the instance from internet::
     $ neutron floatingip-create <external network>
     Created a new floatingip:
     +---------------------+--------------------------------------+
     | Field               | Value                                |
     +---------------------+--------------------------------------+
     | fixed_ip_address    |                                      |
     | floating_ip_address | <floating ip address>                |
     | floating_network_id | c0ccd5d3-f5fa-4608-9310-49919038faa4 |
     | id                  | e5d39a05-ecd4-41bc-a104-93b798dfc644 |
     | port_id             |                                      |
     | router_id           |                                      |
     | status              | ACTIVE                               |
     | tenant_id           | bbefc5080f814a46bd1b1103ea83750a     |
     +---------------------+--------------------------------------+

Take note of the ip address, as you will need it later to connect to the instance.

Now we can associate the floating ip address with the instance::
   $ nova floating-ip-associate ost-controller <floating ip address>


Then we enter the instance to set it up::

    $ ssh ubuntu@<floating ip address>

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
cluster in OS.

We will use
`cloud-config-master.yaml <https://github.com/midonet/kuryr/blob/k8s/contrib/demo/os/cloud-config-master.yaml>`_.
If you have set up the network range differently or picked a different
private-network-ip for the ost-controller, you should adjust the file
accordingly.

Then create the controller instance::

    $ nova boot --flavor m2.large --image "CoreOS 1068.6.0"  \
           --nic net-name=demo,v4-fixed-ip=10.142.0.3 \
           --security-group demo --key-name demo-key k8s-controller \
           --user-data cloud-config-master.yaml

    +--------------------------------------+-----------------------------------------------+
    | Property                             | Value                                         |
    +--------------------------------------+-----------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                        |
    | OS-EXT-AZ:availability_zone          | nova                                          |
    | OS-EXT-STS:power_state               | 0                                             |
    | OS-EXT-STS:task_state                | scheduling                                    |
    | OS-EXT-STS:vm_state                  | building                                      |
    | OS-SRV-USG:launched_at               | -                                             |
    | OS-SRV-USG:terminated_at             | -                                             |
    | accessIPv4                           |                                               |
    | accessIPv6                           |                                               |
    | adminPass                            | cNcB2VxCwUDk                                  |
    | config_drive                         |                                               |
    | created                              | 2016-07-13T13:56:48Z                          |
    | flavor                               | m2.large (12)                                 |
    | hostId                               |                                               |
    | id                                   | 518d5174-c012-4ba7-b137-4fbb53d54c1e          |
    | image                                | CoreOS (10a70cf6-28ac-440c-9e76-8b8fdc21c08e) |
    | key_name                             | demo-key                                      |
    | metadata                             | {}                                            |
    | name                                 | k8s-controller                                |
    | os-extended-volumes:volumes_attached | []                                            |
    | progress                             | 0                                             |
    | security_groups                      | demo                                          |
    | status                               | BUILD                                         |
    | tenant_id                            | bbefc5080f814a46bd1b1103ea83750a              |
    | updated                              | 2016-07-13T13:56:49Z                          |
    | user_id                              | 337002c9ef774525a03dfd8da88662df              |
    +--------------------------------------+-----------------------------------------------+


Note, that until the worker1 and worker2 nodes, which are part of the three
node Etcd cluster, are up with their etcd3.service running, the k8s-controller
Kubernetes services will not start, as they depend upon having a healthy Etcd
cluster. This does not mean that the worker nodes should be started before the
master, as soon as the worker nodes start and get their etcd3.service active,
the master will resume starting its Kubernetes services.

Worker nodes
------------

We will use
`cloud-config-worker1.yaml <https://github.com/midonet/kuryr/blob/k8s/contrib/demo/os/cloud-config-worker1.yaml>`_
and
`cloud-config-worker2.yaml <https://github.com/midonet/kuryr/blob/k8s/contrib/demo/os/cloud-config-worker2.yaml>`_.
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

    $ nova boot --flavor m1.large --image "CoreOS 1068.6.0"  \
           --nic net-name=demo,v4-fixed-ip=10.142.0.4 \
           --security-group demo --key-name demo-key k8s-worker1 \
           --user-data cloud-config-worker1.yaml

    +--------------------------------------+-----------------------------------------------+
    | Property                             | Value                                         |
    +--------------------------------------+-----------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                        |
    | OS-EXT-AZ:availability_zone          | nova                                          |
    | OS-EXT-STS:power_state               | 0                                             |
    | OS-EXT-STS:task_state                | scheduling                                    |
    | OS-EXT-STS:vm_state                  | building                                      |
    | OS-SRV-USG:launched_at               | -                                             |
    | OS-SRV-USG:terminated_at             | -                                             |
    | accessIPv4                           |                                               |
    | accessIPv6                           |                                               |
    | adminPass                            | kEMVboKEHF5r                                  |
    | config_drive                         |                                               |
    | created                              | 2016-07-13T14:16:49Z                          |
    | flavor                               | m1.xlarge (5)                                 |
    | hostId                               |                                               |
    | id                                   | c551d6a6-49d0-4f9a-9998-57adbc810e04          |
    | image                                | CoreOS (10a70cf6-28ac-440c-9e76-8b8fdc21c08e) |
    | key_name                             | demo-key                                      |
    | metadata                             | {}                                            |
    | name                                 | k8s-worker1                                   |
    | os-extended-volumes:volumes_attached | []                                            |
    | progress                             | 0                                             |
    | security_groups                      | demo                                          |
    | status                               | BUILD                                         |
    | tenant_id                            | bbefc5080f814a46bd1b1103ea83750a              |
    | updated                              | 2016-07-13T14:16:50Z                          |
    | user_id                              | 337002c9ef774525a03dfd8da88662df              |
    +--------------------------------------+-----------------------------------------------+

    $ nova boot --flavor m1.large --image "CoreOS 1068.6.0"  \
           --nic net-name=demo,v4-fixed-ip=10.142.0.5 \
           --security-group demo --key-name demo-key k8s-worker2 \
           --user-data cloud-config-worker2.yaml

    +--------------------------------------+-----------------------------------------------+
    | Property                             | Value                                         |
    +--------------------------------------+-----------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                        |
    | OS-EXT-AZ:availability_zone          | nova                                          |
    | OS-EXT-STS:power_state               | 0                                             |
    | OS-EXT-STS:task_state                | scheduling                                    |
    | OS-EXT-STS:vm_state                  | building                                      |
    | OS-SRV-USG:launched_at               | -                                             |
    | OS-SRV-USG:terminated_at             | -                                             |
    | accessIPv4                           |                                               |
    | accessIPv6                           |                                               |
    | adminPass                            | g6GwCEr7uMqW                                  |
    | config_drive                         |                                               |
    | created                              | 2016-07-13T14:27:52Z                          |
    | flavor                               | m2.xlarge (18)                                |
    | hostId                               |                                               |
    | id                                   | bf843cf8-9c04-497a-969e-8a526cfafd7b          |
    | image                                | CoreOS (10a70cf6-28ac-440c-9e76-8b8fdc21c08e) |
    | key_name                             | demo-key                                      |
    | metadata                             | {}                                            |
    | name                                 | k8s-worker2                                   |
    | os-extended-volumes:volumes_attached | []                                            |
    | progress                             | 0                                             |
    | security_groups                      | demo                                          |
    | status                               | BUILD                                         |
    | tenant_id                            | bbefc5080f814a46bd1b1103ea83750a              |
    | updated                              | 2016-07-13T14:27:53Z                          |
    | user_id                              | 337002c9ef774525a03dfd8da88662df              |
    +--------------------------------------+-----------------------------------------------+



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


Login into the K8S controller
-----------------------------

To get into the k8s-controller you need to assign it an floating ip::

    $neutron floatingip-create <extenal network>
    Created a new floatingip:
    +---------------------+--------------------------------------+
    | Field               | Value                                |
    +---------------------+--------------------------------------+
    | fixed_ip_address    |                                      |
    | floating_ip_address | <floating ip>                        |
    | floating_network_id | c0ccd5d3-f5fa-4608-9310-49919038faa4 |
    | id                  | e17b32d9-04f3-4f07-a62a-5de6c655578d |
    | port_id             |                                      |
    | router_id           |                                      |
    | status              | ACTIVE                               |
    | tenant_id           | bbefc5080f814a46bd1b1103ea83750a     |
    +---------------------+--------------------------------------+

Associate this address to the instance::

    $nova floating-ip-associate k8s-controller <floating ip>

Now you can login into the instance::

    $ ssh core@<floating ip>


Checking health
---------------

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

    $ kubectl run --image nginx --replicas 2 firstcontainers
    deployment "firstcontainers" created

After a moment, they should show as running::

    $ kubectl get pods
    NAME                               READY     STATUS    RESTARTS   AGE
    firstcontainers-1830394127-mazlo   1/1       Running   0          24s
    firstcontainers-1830394127-uyh8d   1/1       Running   0          24s

Once they is running, we can get their IPs::

    $ kubectl exec firstcontainers-1830394127-mazlo -- ip -4 a show dev eth0
    15: eth0@if16: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000
        inet 192.168.0.14/24 scope global eth0
           valid_lft forever preferred_lft forever
    $ kubectl exec firstcontainers-1830394127-uyh8d -- ip -4 a show dev eth0
    21: eth0@if22: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000
        inet 192.168.0.6/24 scope global eth0
           valid_lft forever preferred_lft forever

Having seen the ips, let's verify connectivity::
    $ kubectl exec firstcontainers-1830394127-uyh8d ping 192.168.0.14
