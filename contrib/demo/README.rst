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

The process id documented in two separated files dependinf on the cloud
platform being used:

- gce: Google Cloud Engine
- os: OpenStack



