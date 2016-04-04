..
    This work is licensed under a Creative Commons Attribution 3.0 Unported
    License.

    http://creativecommons.org/licenses/by/3.0/legalcode

    Convention for heading levels in Neutron devref:
    =======  Heading 0 (reserved for the title in a document)
    -------  Heading 1
    ~~~~~~~  Heading 2
    +++++++  Heading 3
    '''''''  Heading 4
    (Avoid deeper levels because they do not render well.)

=============================
Kubernetes API Watcher Design
=============================

This documentation describes the `Kuberenetes API`_ watcher daemon component,
**Raven**, of Kuryr.

What is Raven
-------------

Raven is a daemon watches the internal Kubernetes (K8s) state through its API
server and receives the changes with the event notifications. Raven then
translate the state changes of K8s into requests against Neutron API and
constructs the virtual network topology on Neutron.

Raven must acts as the centralized component for the translations due to the
constraints come from the concurrent deployments of the pods on worker nodes.
Unless it's centralized, each plugin on each work node would make requests
against Neutron API and it would lead the conflicts of the requests due to the
race condition because of the lack of the lock or the serialization mechanisms
for the requests against Neutron API.

Although Raven usually resides in the same node where K8s API server is
located, it can be on any node that can communicate with K8s API server and
Neutron API server.

Raven doesn't take care of the bindings between the virtual ports and the
physical interfaces on worker nodes. It is the responsibility of Kuryr CNI_
plugin for K8s and it shall recognize which Neutron port should be bound to the
physical interface associated with the pod to be deployed. So Raven focuses
only on building the virtual network topology translated from the events of the
internal state changes of K8s through its API server.

Goal
~~~~

Through Raven the changes to K8s API server are translated into the appropriate
requests against Neutron API and we can make sure their logical networking states
are synchronized and consistent when the pods are deployed.

Translation Mapping
-------------------

The detailed specification of the translation mappings is described in another
document, :doc:`../specs/kuryr_k8s_integration`. In this document we touch what
to be translated briefly.

Namespaces are translated into Neutron networks and cluster subnets implicitly
specified by the environment variables, i.e., ``FLANNEL_NET=172.16.0.0/16``
specified `in the deployment phase`_, or predefined values in the configuration
file. Each namespace is translated into a Neutron network and they're separated
from each other.

Therefore the main focus of Raven is the following resources.

* Pod
* Service (Optional)

Pods contain the information required by creating Neutron ports.

Although it's optional, Raven can emulate kube-proxy_. This is for the network
controller that leverages isolated datapath from ``docker0`` bridge such as
Open vSwitch datapath. Services contain the information for the emulation. Raven
maps kube-proxy to Neutron load balancers with VIPs. For "LoadBalancer" type K8s
service, Raven associates a floating IP with a load balancer.

================= ================
Kubernetes        Neutron
================= ================
Namespace         Network
(Cluster subnet)  (Subnet)
Pod               Port
Service           LoadBalancer
                  VIP
                  FloatingIP
================= ================


.. _k8s-api-behaviour:

K8s API behaviour
-----------------

We look at the responses from the pod endpoints as an exmple.

The following behaviour is based on the 1.2.0 release, which is the latest one
as of March 17th, 2016.

::

    $ ./kubectl.sh version
    Client Version: version.Info{Major:"1", Minor:"2", GitVersion:"v1.2.0", GitCommit:"5cb86ee022267586db386f62781338b0483733b3", GitTreeState:"clean"}
    Server Version: version.Info{Major:"1", Minor:"2", GitVersion:"v1.2.0", GitCommit:"5cb86ee022267586db386f62781338b0483733b3", GitTreeState:"clean"}

Regular requests
~~~~~~~~~~~~~~~~

If there's no pod, the K8s API server returns the following JSON response that
has the empty list for the ``"items"`` property.

::

    $ curl -X GET -i http://127.0.0.1:8080/api/v1/pods
    HTTP/1.1 200 OK
    Content-Type: application/json
    Date: Tue, 15 Mar 2016 07:15:46 GMT
    Content-Length: 145

    {
      "kind": "PodList",
      "apiVersion": "v1",
      "metadata": {
        "selfLink": "/api/v1/pods",
        "resourceVersion": "227806"
      },
      "items": []
    }

We deploy a pod as follow.

::

    $ ./kubectl.sh run --image=nginx nginx-app --port=80
    replicationcontroller "nginx-app" created

Then the response from the API server contains the pod information in
``"items"`` property of the JSON response.

::

    $ curl -X GET -i http://127.0.0.1:8080/api/v1/pods
    HTTP/1.1 200 OK
    Content-Type: application/json
    Date: Tue, 15 Mar 2016 08:18:25 GMT
    Transfer-Encoding: chunked

    {
      "kind": "PodList",
      "apiVersion": "v1",
      "metadata": {
        "selfLink": "/api/v1/pods",
        "resourceVersion": "228211"
      },
      "items": [
        {
          "metadata": {
            "name": "nginx-app-o0kvl",
            "generateName": "nginx-app-",
            "namespace": "default",
            "selfLink": "/api/v1/namespaces/default/pods/nginx-app-o0kvl",
            "uid": "090cc0c8-ea84-11e5-8c79-42010af00003",
            "resourceVersion": "228094",
            "creationTimestamp": "2016-03-15T08:00:51Z",
            "labels": {
              "run": "nginx-app"
            },
            "annotations": {
              "kubernetes.io/created-by": "{\"kind\":\"SerializedReference\",\"apiVersion\":\"v1\",\"reference\":{\"kind\":\"ReplicationController\",\"namespace\":\"default\",\"name\":\"nginx-app\",\"uid\":\"090bfb57-ea84-11e5-8c79-42010af00003\",\"apiVersion\":\"v1\",\"resourceVersion\":\"228081\"}}\n"
            }
          },
          "spec": {
            "volumes": [
              {
                "name": "default-token-wpfjn",
                "secret": {
                  "secretName": "default-token-wpfjn"
                }
              }
            ],
            "containers": [
              {
                "name": "nginx-app",
                "image": "nginx",
                "ports": [
                  {
                    "containerPort": 80,
                    "protocol": "TCP"
                  }
                ],
                "resources": {},
                "volumeMounts": [
                  {
                    "name": "default-token-wpfjn",
                    "readOnly": true,
                    "mountPath": "/var/run/secrets/kubernetes.io/serviceaccount"
                  }
                ],
                "terminationMessagePath": "/dev/termination-log",
                "imagePullPolicy": "Always"
              }
            ],
            "restartPolicy": "Always",
            "terminationGracePeriodSeconds": 30,
            "dnsPolicy": "ClusterFirst",
            "serviceAccountName": "default",
            "serviceAccount": "default",
            "nodeName": "10.240.0.4",
            "securityContext": {}
          },
          "status": {
            "phase": "Running",
            "conditions": [
              {
                "type": "Ready",
                "status": "True",
                "lastProbeTime": null,
                "lastTransitionTime": "2016-03-15T08:00:52Z"
              }
            ],
            "hostIP": "10.240.0.4",
            "podIP": "172.16.49.2",
            "startTime": "2016-03-15T08:00:51Z",
            "containerStatuses": [
              {
                "name": "nginx-app",
                "state": {
                  "running": {
                    "startedAt": "2016-03-15T08:00:52Z"
                  }
                },
                "lastState": {},
                "ready": true,
                "restartCount": 0,
                "image": "nginx",
                "imageID": "docker://sha256:af4b3d7d5401624ed3a747dc20f88e2b5e92e0ee9954aab8f1b5724d7edeca5e",
                "containerID": "docker://b97168314ad58404dbce7cb94291db7a976d2cb824b39e5864bf4bdaf27af255"
              }
            ]
          }
        }
      ]
    }

We get the current snapshot of the requested resources with the regular
requests against the K8s API server.

Requests with ``watch=true`` query string
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

K8s provides the "watch" capability for the endpoints with ``/watch/`` prefix
for the specific resource name, i.e., ``/api/v1/watch/pods``, or ``watch=true``
query string.

If there's no pod, we get only the response header and the connection is kept
open.

::

    $ curl -X GET -i http://127.0.0.1:8080/api/v1/pods?watch=true
    HTTP/1.1 200 OK
    Transfer-Encoding: chunked
    Date: Tue, 15 Mar 2016 08:00:09 GMT
    Content-Type: text/plain; charset=utf-8
    Transfer-Encoding: chunked
    

We create a pod as we did for the case without the ``watch=true`` query string.

::

    $ ./kubectl.sh run --image=nginx nginx-app --port=80
    replicationcontroller "nginx-app" created

Then we observe the JSON data corresponds to the event is given by each line.
The event type is given in ``"type"`` property of the JSON data, i.e.,
``"ADDED"``, ``"MODIFIED"`` and ``"DELETED"``.

::

    $ curl -X GET -i http://127.0.0.1:8080/api/v1/pods?watch=true
    HTTP/1.1 200 OK
    Transfer-Encoding: chunked
    Date: Tue, 15 Mar 2016 08:00:09 GMT
    Content-Type: text/plain; charset=utf-8
    Transfer-Encoding: chunked

    {"type":"ADDED","object":{"kind":"Pod","apiVersion":"v1","metadata":{"name":"nginx-app-o0kvl","generateName":"nginx-app-","namespace":"default","selfLink":"/api/v1/namespaces/default/pods/nginx-app-o0kvl","uid":"090cc0c8-ea84-11e5-8c79-42010af00003","resourceVersion":"228082","creationTimestamp":"2016-03-15T08:00:51Z","labels":{"run":"nginx-app"},"annotations":{"kubernetes.io/created-by":"{\"kind\":\"SerializedReference\",\"apiVersion\":\"v1\",\"reference\":{\"kind\":\"ReplicationController\",\"namespace\":\"default\",\"name\":\"nginx-app\",\"uid\":\"090bfb57-ea84-11e5-8c79-42010af00003\",\"apiVersion\":\"v1\",\"resourceVersion\":\"228081\"}}\n"}},"spec":{"volumes":[{"name":"default-token-wpfjn","secret":{"secretName":"default-token-wpfjn"}}],"containers":[{"name":"nginx-app","image":"nginx","ports":[{"containerPort":80,"protocol":"TCP"}],"resources":{},"volumeMounts":[{"name":"default-token-wpfjn","readOnly":true,"mountPath":"/var/run/secrets/kubernetes.io/serviceaccount"}],"terminationMessagePath":"/dev/termination-log","imagePullPolicy":"Always"}],"restartPolicy":"Always","terminationGracePeriodSeconds":30,"dnsPolicy":"ClusterFirst","serviceAccountName":"default","serviceAccount":"default","securityContext":{}},"status":{"phase":"Pending"}}}
    {"type":"MODIFIED","object":{"kind":"Pod","apiVersion":"v1","metadata":{"name":"nginx-app-o0kvl","generateName":"nginx-app-","namespace":"default","selfLink":"/api/v1/namespaces/default/pods/nginx-app-o0kvl","uid":"090cc0c8-ea84-11e5-8c79-42010af00003","resourceVersion":"228084","creationTimestamp":"2016-03-15T08:00:51Z","labels":{"run":"nginx-app"},"annotations":{"kubernetes.io/created-by":"{\"kind\":\"SerializedReference\",\"apiVersion\":\"v1\",\"reference\":{\"kind\":\"ReplicationController\",\"namespace\":\"default\",\"name\":\"nginx-app\",\"uid\":\"090bfb57-ea84-11e5-8c79-42010af00003\",\"apiVersion\":\"v1\",\"resourceVersion\":\"228081\"}}\n"}},"spec":{"volumes":[{"name":"default-token-wpfjn","secret":{"secretName":"default-token-wpfjn"}}],"containers":[{"name":"nginx-app","image":"nginx","ports":[{"containerPort":80,"protocol":"TCP"}],"resources":{},"volumeMounts":[{"name":"default-token-wpfjn","readOnly":true,"mountPath":"/var/run/secrets/kubernetes.io/serviceaccount"}],"terminationMessagePath":"/dev/termination-log","imagePullPolicy":"Always"}],"restartPolicy":"Always","terminationGracePeriodSeconds":30,"dnsPolicy":"ClusterFirst","serviceAccountName":"default","serviceAccount":"default","nodeName":"10.240.0.4","securityContext":{}},"status":{"phase":"Pending"}}}
    {"type":"MODIFIED","object":{"kind":"Pod","apiVersion":"v1","metadata":{"name":"nginx-app-o0kvl","generateName":"nginx-app-","namespace":"default","selfLink":"/api/v1/namespaces/default/pods/nginx-app-o0kvl","uid":"090cc0c8-ea84-11e5-8c79-42010af00003","resourceVersion":"228088","creationTimestamp":"2016-03-15T08:00:51Z","labels":{"run":"nginx-app"},"annotations":{"kubernetes.io/created-by":"{\"kind\":\"SerializedReference\",\"apiVersion\":\"v1\",\"reference\":{\"kind\":\"ReplicationController\",\"namespace\":\"default\",\"name\":\"nginx-app\",\"uid\":\"090bfb57-ea84-11e5-8c79-42010af00003\",\"apiVersion\":\"v1\",\"resourceVersion\":\"228081\"}}\n"}},"spec":{"volumes":[{"name":"default-token-wpfjn","secret":{"secretName":"default-token-wpfjn"}}],"containers":[{"name":"nginx-app","image":"nginx","ports":[{"containerPort":80,"protocol":"TCP"}],"resources":{},"volumeMounts":[{"name":"default-token-wpfjn","readOnly":true,"mountPath":"/var/run/secrets/kubernetes.io/serviceaccount"}],"terminationMessagePath":"/dev/termination-log","imagePullPolicy":"Always"}],"restartPolicy":"Always","terminationGracePeriodSeconds":30,"dnsPolicy":"ClusterFirst","serviceAccountName":"default","serviceAccount":"default","nodeName":"10.240.0.4","securityContext":{}},"status":{"phase":"Pending","conditions":[{"type":"Ready","status":"False","lastProbeTime":null,"lastTransitionTime":"2016-03-15T08:00:51Z","reason":"ContainersNotReady","message":"containers with unready status: [nginx-app]"}],"hostIP":"10.240.0.4","startTime":"2016-03-15T08:00:51Z","containerStatuses":[{"name":"nginx-app","state":{"waiting":{"reason":"ContainerCreating","message":"Image: nginx is ready, container is creating"}},"lastState":{},"ready":false,"restartCount":0,"image":"nginx","imageID":""}]}}}
    {"type":"MODIFIED","object":{"kind":"Pod","apiVersion":"v1","metadata":{"name":"nginx-app-o0kvl","generateName":"nginx-app-","namespace":"default","selfLink":"/api/v1/namespaces/default/pods/nginx-app-o0kvl","uid":"090cc0c8-ea84-11e5-8c79-42010af00003","resourceVersion":"228094","creationTimestamp":"2016-03-15T08:00:51Z","labels":{"run":"nginx-app"},"annotations":{"kubernetes.io/created-by":"{\"kind\":\"SerializedReference\",\"apiVersion\":\"v1\",\"reference\":{\"kind\":\"ReplicationController\",\"namespace\":\"default\",\"name\":\"nginx-app\",\"uid\":\"090bfb57-ea84-11e5-8c79-42010af00003\",\"apiVersion\":\"v1\",\"resourceVersion\":\"228081\"}}\n"}},"spec":{"volumes":[{"name":"default-token-wpfjn","secret":{"secretName":"default-token-wpfjn"}}],"containers":[{"name":"nginx-app","image":"nginx","ports":[{"containerPort":80,"protocol":"TCP"}],"resources":{},"volumeMounts":[{"name":"default-token-wpfjn","readOnly":true,"mountPath":"/var/run/secrets/kubernetes.io/serviceaccount"}],"terminationMessagePath":"/dev/termination-log","imagePullPolicy":"Always"}],"restartPolicy":"Always","terminationGracePeriodSeconds":30,"dnsPolicy":"ClusterFirst","serviceAccountName":"default","serviceAccount":"default","nodeName":"10.240.0.4","securityContext":{}},"status":{"phase":"Running","conditions":[{"type":"Ready","status":"True","lastProbeTime":null,"lastTransitionTime":"2016-03-15T08:00:52Z"}],"hostIP":"10.240.0.4","podIP":"172.16.49.2","startTime":"2016-03-15T08:00:51Z","containerStatuses":[{"name":"nginx-app","state":{"running":{"startedAt":"2016-03-15T08:00:52Z"}},"lastState":{},"ready":true,"restartCount":0,"image":"nginx","imageID":"docker://sha256:af4b3d7d5401624ed3a747dc20f88e2b5e92e0ee9954aab8f1b5724d7edeca5e","containerID":"docker://b97168314ad58404dbce7cb94291db7a976d2cb824b39e5864bf4bdaf27af255"}]}}}

Raven Technical Design Overview
-------------------------------

Problem Statement
~~~~~~~~~~~~~~~~~

To conform to the I/O bound requirement described in :ref:`k8s-api-behaviour`,
the multiplexed concurrent network I/O is demanded. eventlet_ is used in
various OpenStack projects for this purpose as well as other libraries such as
Twisted_, Tornado_ and gevent_. However, it has problems as described in
"`What's wrong with eventlet?`_" on the OpenStack wiki page.

asyncio and Python 3 by default
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

asyncio_ was introduced as a standard asynchronous I/O library in Python 3.4.
Its event loop and coroutines provide the mechanism to multiplex network I/O
in the asynchronous fashion. Compared with eventlet, we can explicitly mark the
I/O operations asynchronous with ``yield from`` or ``await`` introduced in
Python 3.5.

Trollius_ is a port of asyncio to Python 2.x. However `Trollius documentation`_
is describing a list of problems and even promoting the migration to Python 3
with asyncio.

Kuryr is still a quite young project in OpenStack Neutron big tent. In addition
to that, since it's a container related project it should be able to be run
inside a container. So do Raven. Therefore we take a path to support for only
Python 3 and drop Python 2.

With asyncio we can achieve concurrent networking I/O operations required by
watchers watch multiple endpoints and translate their responses into requests
against Neutorn and K8s API server.

Watchers
~~~~~~~~

A watcher can be represented as a pair of an API endpoint and a function used
for the translation essentially. That is, the pair of what is translated and
how it is. The API endpoint URI is associated with the stream of the event
notifications and the translation function maps each event coming from the
apiserver into another form such as the request against Neutron API server.

Watchers can be considered as concerns and reactions. They should be decouped
from the actual task dispatcher and their consumers. A single or multiple
watchers can be mixed into the single class that leverages them, i.e., Raven,
or even mutliple classes leverage them can have the same concern and the same
reaction. The watchers can be able to be mixed into the single entity of the
watcher user but they should work independently. For instance, ``AliceWatcher``
does its work and knows nothing about other watchers such as ``BobWatcher``.
They don't work together depending on one or each.

A minimum watcher can be defined as follow.

.. code-block:: python

    from kuryr.raven import watchers

    class SomeWatcher(watchers.K8sApiWatcher):
        WATCH_ENDPOINT = '/'

        def translate(self, deserialized_json):
            pass

The watcher is defined in the declarative way and ideally doesn't care when it
is called and by whom. However, it needs to recongnize the context such as the
event type and behave appropriately according to the situation.

Raven
~~~~~

Raven acts as a daemon and it should be able to be started or stopped by
operators. It delegates the actual watch tasks to the watchers and dispatch
them with the single JSON response corresponds to each endpoint on which the
watcher has its concern.

Hence, Raven holds one or multiple watchers, opens connections for each
endpoint, makes HTTP requests, gets HTTP responses and parses every event
notification and dispatches the translate methods of the watchers routed based
on their corresponding endpoints.

To register the watchers to Raven or any class, ``register_watchers`` decorator
is used. It simply inserts the watchers into the dictionary in the class,
``WATCH_ENDPOINTS_AND_CALLBACKS`` and it's up to the class how use the
registerd watchers. The classes passed to ``register_watchers`` are defined in
the configuration file and you can specify only what you need.

In the case of Raven, it starts the event loop, open connections for each
registered watcher and keeps feeding the notified events to the translate
methods of the watchers.

Raven is a service implements ``oslo_service.service.Service``. When ``start``
method is called, it starts the event loop and delegatations of the watch tasks.
If ``SIGINT`` or ``SIGTERM`` signal is sent to Raven, it cancells all watch
tasks, closes connections and stops immediately. Otherwise Raven lets watchers
keep watching the API endpionts until the API server sends EOF strings. When
``stop`` is called, it cancells all watch tasks, closes connections and stops
as well.

Ideally, the translate method can be a pure function that doesn't depend on the
user of the watcher. However, the translation gets involved in requests against
Neutron and possibly the K8s API server. And it depends on the Neutron client
that shall be shared among the watchers. Hence, Raven calls the translate
methods of the watchers binding itself to ``self``. That is, Raven can
propagate its contexts to the watchers and in this way watchers can share the
same contexts. However, it's responsibilty of the writer of the watchers to
track which variables are defined in Raven and what they are.

Appendix A: JSON response from the apiserver for each resource
--------------------------------------------------------------

Pod
~~~

::

    /api/v1/pods?watch=true

ADDED
+++++

::
    {
      "type": "ADDED",
      "object": {
        "kind": "Pod",
        "apiVersion": "v1",
        "metadata": {
          "name": "my-nginx-y67ky",
          "generateName": "my-nginx-",
          "namespace": "default",
          "selfLink": "/api/v1/namespaces/default/pods/my-nginx-y67ky",
          "uid": "d42b0bb2-dc4e-11e5-8c79-42010af00003",
          "resourceVersion": "63355",
          "creationTimestamp": "2016-02-26T06:04:42Z",
          "labels": {
            "run": "my-nginx"
          },
          "annotations": {
            "kubernetes.io/created-by": {
              "kind": "SerializedReference",
              "apiVersion": "v1",
              "reference": {
                "kind": "ReplicationController",
                "namespace": "default",
                "name": "my-nginx",
                "uid": "d42a4ee1-dc4e-11e5-8c79-42010af00003",
                "apiVersion": "v1",
                "resourceVersion": "63348"
              }
            }
          }
        },
        "spec": {
          "volumes": [
            {
              "name": "default-token-wpfjn",
              "secret": {
                "secretName": "default-token-wpfjn"
              }
            }
          ],
          "containers": [
            {
              "name": "my-nginx",
              "image": "nginx",
              "ports": [
                {
                  "containerPort": 80,
                  "protocol": "TCP"
                }
              ],
              "resources": {},
              "volumeMounts": [
                {
                  "name": "default-token-wpfjn",
                  "readOnly": true,
                  "mountPath": "/var/run/secrets/kubernetes.io/serviceaccount"
                }
              ],
              "terminationMessagePath": "/dev/termination-log",
              "imagePullPolicy": "Always"
            }
          ],
          "restartPolicy": "Always",
          "terminationGracePeriodSeconds": 30,
          "dnsPolicy": "ClusterFirst",
          "serviceAccountName": "default",
          "serviceAccount": "default",
          "nodeName": "10.240.0.4",
          "securityContext": {}
        },
        "status": {
          "phase": "Pending",
          "conditions": [
            {
              "type": "Ready",
              "status": "False",
              "lastProbeTime": null,
              "lastTransitionTime": "2016-02-26T06:04:43Z",
              "reason": "ContainersNotReady",
              "message": "containers with unready status: [my-nginx]"
            }
          ],
          "hostIP": "10.240.0.4",
          "startTime": "2016-02-26T06:04:43Z",
          "containerStatuses": [
            {
              "name": "my-nginx",
              "state": {
                "waiting": {
                  "reason": "ContainerCreating",
                  "message": "Image: nginx is ready, container is creating"
                }
              },
              "lastState": {},
              "ready": false,
              "restartCount": 0,
              "image": "nginx",
              "imageID": ""
            }
          ]
        }
      }
    }

MODIFIED
~~~~~~~~

::

    {
      "type": "MODIFIED",
      "object": {
        "kind": "Pod",
        "apiVersion": "v1",
        "metadata": {
          "name": "my-nginx-y67ky",
          "generateName": "my-nginx-",
          "namespace": "default",
          "selfLink": "/api/v1/namespaces/default/pods/my-nginx-y67ky",
          "uid": "d42b0bb2-dc4e-11e5-8c79-42010af00003",
          "resourceVersion": "63425",
          "creationTimestamp": "2016-02-26T06:04:42Z",
          "deletionTimestamp": "2016-02-26T06:06:16Z",
          "deletionGracePeriodSeconds": 30,
          "labels": {
            "run": "my-nginx"
          },
          "annotations": {
            "kubernetes.io/created-by": {
              "kind": "SerializedReference",
              "apiVersion": "v1",
              "reference": {
                "kind": "ReplicationController",
                "namespace": "default",
                "name": "my-nginx",
                "uid": "d42a4ee1-dc4e-11e5-8c79-42010af00003",
                "apiVersion": "v1",
                "resourceVersion": "63348"
              }
            }
          }
        },
        "spec": {
          "volumes": [
            {
              "name": "default-token-wpfjn",
              "secret": {
                "secretName": "default-token-wpfjn"
              }
            }
          ],
          "containers": [
            {
              "name": "my-nginx",
              "image": "nginx",
              "ports": [
                {
                  "containerPort": 80,
                  "protocol": "TCP"
                }
              ],
              "resources": {},
              "volumeMounts": [
                {
                  "name": "default-token-wpfjn",
                  "readOnly": true,
                  "mountPath": "/var/run/secrets/kubernetes.io/serviceaccount"
                }
              ],
              "terminationMessagePath": "/dev/termination-log",
              "imagePullPolicy": "Always"
            }
          ],
          "restartPolicy": "Always",
          "terminationGracePeriodSeconds": 30,
          "dnsPolicy": "ClusterFirst",
          "serviceAccountName": "default",
          "serviceAccount": "default",
          "nodeName": "10.240.0.4",
          "securityContext": {}
        },
        "status": {
          "phase": "Pending",
          "conditions": [
            {
              "type": "Ready",
              "status": "False",
              "lastProbeTime": null,
              "lastTransitionTime": "2016-02-26T06:04:43Z",
              "reason": "ContainersNotReady",
              "message": "containers with unready status: [my-nginx]"
            }
          ],
          "hostIP": "10.240.0.4",
          "startTime": "2016-02-26T06:04:43Z",
          "containerStatuses": [
            {
              "name": "my-nginx",
              "state": {
                "waiting": {
                  "reason": "ContainerCreating",
                  "message": "Image: nginx is ready, container is creating"
                }
              },
              "lastState": {},
              "ready": false,
              "restartCount": 0,
              "image": "nginx",
              "imageID": ""
            }
          ]
        }
      }
    }

DELETED
+++++++

::

    {
      "type": "DELETED",
      "object": {
        "kind": "Pod",
        "apiVersion": "v1",
        "metadata": {
          "name": "my-nginx-y67ky",
          "generateName": "my-nginx-",
          "namespace": "default",
          "selfLink": "/api/v1/namespaces/default/pods/my-nginx-y67ky",
          "uid": "d42b0bb2-dc4e-11e5-8c79-42010af00003",
          "resourceVersion": "63431",
          "creationTimestamp": "2016-02-26T06:04:42Z",
          "deletionTimestamp": "2016-02-26T06:05:46Z",
          "deletionGracePeriodSeconds": 0,
          "labels": {
            "run": "my-nginx"
          },
          "annotations": {
            "kubernetes.io/created-by": {
              "kind": "SerializedReference",
              "apiVersion": "v1",
              "reference": {
                "kind": "ReplicationController",
                "namespace": "default",
                "name": "my-nginx",
                "uid": "d42a4ee1-dc4e-11e5-8c79-42010af00003",
                "apiVersion": "v1",
                "resourceVersion": "63348"
              }
            }
          }
        },
        "spec": {
          "volumes": [
            {
              "name": "default-token-wpfjn",
              "secret": {
                "secretName": "default-token-wpfjn"
              }
            }
          ],
          "containers": [
            {
              "name": "my-nginx",
              "image": "nginx",
              "ports": [
                {
                  "containerPort": 80,
                  "protocol": "TCP"
                }
              ],
              "resources": {},
              "volumeMounts": [
                {
                  "name": "default-token-wpfjn",
                  "readOnly": true,
                  "mountPath": "/var/run/secrets/kubernetes.io/serviceaccount"
                }
              ],
              "terminationMessagePath": "/dev/termination-log",
              "imagePullPolicy": "Always"
            }
          ],
          "restartPolicy": "Always",
          "terminationGracePeriodSeconds": 30,
          "dnsPolicy": "ClusterFirst",
          "serviceAccountName": "default",
          "serviceAccount": "default",
          "nodeName": "10.240.0.4",
          "securityContext": {}
        },
        "status": {
          "phase": "Pending",
          "conditions": [
            {
              "type": "Ready",
              "status": "False",
              "lastProbeTime": null,
              "lastTransitionTime": "2016-02-26T06:04:43Z",
              "reason": "ContainersNotReady",
              "message": "containers with unready status: [my-nginx]"
            }
          ],
          "hostIP": "10.240.0.4",
          "startTime": "2016-02-26T06:04:43Z",
          "containerStatuses": [
            {
              "name": "my-nginx",
              "state": {
                "waiting": {
                  "reason": "ContainerCreating",
                  "message": "Image: nginx is ready, container is creating"
                }
              },
              "lastState": {},
              "ready": false,
              "restartCount": 0,
              "image": "nginx",
              "imageID": ""
            }
          ]
        }
      }
    }

Service
~~~~~~~

::

    /api/v1/services?watch=true

ADDED
+++++

::

    {
      "type": "ADDED",
      "object": {
        "kind": "Service",
        "apiVersion": "v1",
        "metadata": {
          "name": "redis-master",
          "namespace": "default",
          "selfLink": "/api/v1/namespaces/default/services/redis-master",
          "uid": "7aecfdac-d54c-11e5-8cc5-42010af00002",
          "resourceVersion": "2074",
          "creationTimestamp": "2016-02-17T08:00:16Z",
          "labels": {
            "app": "redis",
            "role": "master",
            "tier": "backend"
          }
        },
        "spec": {
          "ports": [
            {
              "protocol": "TCP",
              "port": 6379,
              "targetPort": 6379
            }
          ],
          "selector": {
            "app": "redis",
            "role": "master",
            "tier": "backend"
          },
          "clusterIP": "10.0.0.102",
          "type": "ClusterIP",
          "sessionAffinity": "None"
        },
        "status": {
          "loadBalancer": {}
        }
      }
    }

MODIFIED
++++++++

The event could not be observed.

DELETED
+++++++

::

    {
      "type": "DELETED",
      "object": {
        "kind": "Service",
        "apiVersion": "v1",
        "metadata": {
          "name": "redis-master",
          "namespace": "default",
          "selfLink": "/api/v1/namespaces/default/services/redis-master",
          "uid": "7aecfdac-d54c-11e5-8cc5-42010af00002",
          "resourceVersion": "2806",
          "creationTimestamp": "2016-02-17T08:00:16Z",
          "labels": {
            "app": "redis",
            "role": "master",
            "tier": "backend"
          }
        },
        "spec": {
          "ports": [
            {
              "protocol": "TCP",
              "port": 6379,
              "targetPort": 6379
            }
          ],
          "selector": {
            "app": "redis",
            "role": "master",
            "tier": "backend"
          },
          "clusterIP": "10.0.0.102",
          "type": "ClusterIP",
          "sessionAffinity": "None"
        },
        "status": {
          "loadBalancer": {}
        }
      }
    }


.. _`Kubernetes API`: http://kubernetes.io/docs/api/
.. _CNI: https://github.com/appc/cni
.. _`in the deployment phase`: https://github.com/kubernetes/kubernetes/search?utf8=%E2%9C%93&q=FLANNEL_NET
.. _kube-proxy: http://kubernetes.io/docs/user-guide/services/#virtual-ips-and-service-proxies
.. _eventlet: http://eventlet.net/
.. _Twisted: https://twistedmatrix.com/trac/
.. _Tornado: http://tornadoweb.org/
.. _gevent: http://www.gevent.org/
.. _`What's wrong with eventlet?`: https://wiki.openstack.org/wiki/Oslo/blueprints/asyncio#What.27s_wrong_with_eventlet.3F
.. _asyncio: https://www.python.org/dev/peps/pep-3156/
.. _Trollius: http://trollius.readthedocs.org/
.. _`Trollius documentation`: http://trollius.readthedocs.org/deprecated.html
