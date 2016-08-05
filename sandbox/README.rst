Midonet Sandbox for Kubernetes and Kuryr
========================================

This directory contains all the needed information to run the
_`midonet-sandbox<https://github.com/midonet/midonet-sandbox>`. This is intended to run all the services that
k8s integration work needs for an end-to-end development.

That will deploy all the services except Raven. It will also mount your current
directory to the 'kubernetes' container, so your code related to CNI driver will
automatically be used for the kubelet.

You will have to spawn your raven service by youself. This is why you are
developing, right??


Prerequisites
-------------

You need to have installed:

 * python3.4
 * kubectl
 * docker
 * realpath (you need to install the package in some environments like Debian)


Kubectl is not available on repos. But it is easy to install and set up::

    curl -sSL "http://storage.googleapis.com/kubernetes-release/release/v1.2.0/bin/linux/amd64/kubectl" > /usr/bin/kubectl
    chmod +x /usr/bin/kubectl

On OS X, to make the API server accessible locally, setup a ssh tunnel::

    docker-machine ssh `docker-machine active` -N -L 8080:localhost:8080


Clone kuryr downstream
----------------------

Get the code from the K8s integration branch::

    $> git clone http://github.com/midonet/kuryr -b k8s
    $> cd kuryr

Create a virtual env for sandbox
--------------------------------

In the home directory of the `kuryr` repository, create the virtual environment::

    $> virtualenv .venv-sandbox
    $> source .venv-sandbox/bin/activate
    $(.venv-sandbox)> pip install -r sandbox/requirements.txt

Getting images for sandbox containers
-------------------------------------

By default, the images used by the sandbox are retrieved from the artifactory
(internal image respository). If you want to build them from public repositories
set the `SANDBOX_PULL` variable to `false`. First time it will take a lot of time,
since it will need to build the images, but after that, it will be fast.


Launching the sanbox
--------------------

If you are not already in the virtual environment, activate it::

    $> source .venv-sandbox/bin/activate

Then launch the sandbox. For using images from the artifactory::

    $(.venv-sandbox)> ./scripts/run_sandbox.sh start

Or for building images locally from public sources::

    $(.venv-sandbox)>SANDBOX_PULL=false ./scripts/run_sandbox.sh start


Prepare kuryr environment
-------------------------

Kuryr requires python3.4, so we have to create a new virtual environment
for it::

    $> virtualenv -p python3.4 .venv-kuryr
    $> source .venv-kuryr/bin/activate

Before proceding to complete the installation, be sure pip and setuptools are
up to date::

    $> sudo pip install --upgrade pip setuptools

We can now install the dependencies::

    $(.venv-kuryr)> pip install .


Create the environment file
---------------------------

Raven needs several environment variables to spawn. The best you can do is
create an environment file with them, like this one::

    #!/bin/bash

    export IDENTITY_URL=http://172.17.0.2:35357/v2.0
    export OS_URL=http://172.17.0.8:9696
    export SERVICE_TENANT_NAME=admin
    export SERVICE_USER=admin
    export SERVICE_PASSWORD=admin
    export SERVICE_CLUSTER_IP_RANGE=10.0.0.0/24

    # for neutron calls
    export OS_USERNAME=admin
    export OS_TENANT_NAME=admin
    export OS_PASSWORD=admin
    export OS_AUTH_URL=http://172.17.0.2:35357/v2.0/


`172.17.0.2` is the keystone container IP and `172.17.0.8` is the neutron one.
You may need to check if your actual containers have these IPs.


Run your raven service
----------------------

If you are not already in the kuryr environement, activate it::

    $> source .venv-kuryr/bin/activate

and launch the service::

    $(.venv-kuryr)> source ravenrc
    $(.venv-kuryr)> raven

You can specify the `--debug` option to have a more detailed trace of raven's execution.

You are ready to run `kubectl` commands and hack the code!

Stop your Sandbox
-----------------

Just run::

    $(.venv-sandbox)> ./scripts/run_sandbox.sh stop


.. `midonet-sandbox http://github.com/midonet/midonet-sandbox`_
