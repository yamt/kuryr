===============
Raven container
===============

This is the container generation file for Kuryr's Kubernetes API watcher, also
known as raven.

How to build the container
------------------------

If you want to build your own container, you can just build it by running the
following command from this same directory:

::
    docker build -t your_docker_username/raven:latest .

How to get the container
------------------------

To get the upstream raven container, you can just do:

::
    docker pull kuryr/raven:latest

It is expected that different vendors may have their own versions of raven in
their docker hub namespaces, for example:

::
    docker pull midonet/raven:latest

How to run the container
------------------------

::
    docker run --name raven \
      -e SERVICE_USER=admin \
      -e SERVICE_TENANT_NAME=admin \
      -e SERVICE_PASSWORD=admin \
      -e IDENTITY_URL=http://127.0.0.1:35357/v2.0 \
      -e OS_URL=http://127.0.0.1:9696 \
      -e K8S_API=http://127.0.0.1:8080 \
      -v /var/log/kuryr:/var/log/kuryr \
      kuryr/raven

Where:
* SERVICE_USER, SERVICE_TENANT_SERVICE_PASSWORD are OpenStack credentials
* IDENTITY_URL is the url to OpenStack Keystone
* OS_URL is the url to OpenStack Neutron
* k8S_API is the url to the Kubernetes API server
* A volume is created so that the logs are available on the host

Note that the 127.0.0.1 are most likely to have to be changed unless you are
running everything on a single machine with `--net=host`.
