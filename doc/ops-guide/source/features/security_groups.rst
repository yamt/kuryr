==============================
Map to Neutron Security Groups
==============================


Raven default Security Group
----------------------------

On start up, Raven creates a Neutron Security Group named "raven-default-sg"
if it doesn't exist.  It is used for every Neutron Ports for Pods by default.
By default it contains rules similar to Neutron's default Security Group for
tenants.  That is, ingress rules for IPv4 and IPv6, which allows traffic from
the same Security Group.


Using other Security Group
--------------------------

You can override the behaviour described in the above section by specifying
an UUID of other Neutron Security Group explicitly with a Kubernetes Pod
Label "kuryr.org/neutron-security-group".


Examples
--------

Associate a Neutron Security Group
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    kubectl label po pod-name kuryr.org/neutron-security-group=7e0f9cae-d286-4b07-804c-dcdcf25f4912


Disassociate a Neutron Security Group
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This restores the association to the Raven's default Security Group.

.. code-block:: bash

    kubectl label po pod-name kuryr.org/neutron-security-group-


References
----------

- `Raven Pod-SG demo <https://drive.google.com/file/d/0B-0uTmOVk3gnTEhQVEFUYU4tWGs/view?usp=sharing>`_

    1 minute video to demonstrate Security Group association feature.
