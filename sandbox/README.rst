Midonet Sandbox for Kubernetes and Kuryr
========================================

This directory contains all the needed information to run the
_`midonet-sandbox`. This is intended to run all the services that
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


Clone kuryr downstream
----------------------

.. code:: bash

    $> git clone http://github.com/midonet/kuryr -b k8s
    $> cd kuryr

Create a virtual env
--------------------

In the home directory of the `kuryr` repository, create the virtual environment:

.. code:: bash

    $> virtualenv .venv-sandbox
    $> source .venv-kuryr/bin/activate
    $(.venv-sandbox)> pip install -r sandbox/requirements.txt


Install kubectl
---------------

Kubectl is not available on repos. But it is easy to install and set up:


.. code:: bash

    curl -sSL "http://storage.googleapis.com/kubernetes-release/release/v1.2.0/bin/linux/amd64/kubectl" > /usr/bin/kubectl
    chmod +x /usr/bin/kubectl


On OS X, to make the API server accessible locally, setup a ssh tunnel.

    docker-machine ssh `docker-machine active` -N -L 8080:localhost:8080



Run the script
--------------

First time it will take a lot of time, since it will need to build the images.
But after that, it will be fast


.. code:: bash

    $(.venv-sandbox)> ./scripts/run_sandbox.sh start


Create the environment file
---------------------------


Raven needs several environment variables to spawn. The best you can do is
create an environment file with them, like this one:

.. code:: bash
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

Load the env file!

Run your raven service
----------------------

Unfortunately, midonet-sandbox does not run on python3.4, so we have to create a
new virtual environment for kuryr.

.. code:: bash

    $> virtualenv -p python3.4 .venv-kuryr
    $(.venv-kuryr)> python setup.py install
    $(.venv-kuryr)> raven

You are ready to run `kubectl` commands and hack the code!


Stop your Sandbox
-----------------

Just run:

.. code:: bash

    $(.venv-kuryr)> ./scripts/run_sandbox.sh stop


.. `midonet-sandbox http://github.com/midonet/midonet-sandbox`_
