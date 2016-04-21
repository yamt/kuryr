# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import abc
import asyncio

from neutronclient.common import exceptions as n_exceptions
from oslo_log import log
from oslo_serialization import jsonutils
import requests
import six

from kuryr._i18n import _LE
from kuryr.common import config
from kuryr.common import constants


K8S_API_ENDPOINT_BASE = config.CONF.k8s.api_root
K8S_API_ENDPOINT_V1 = K8S_API_ENDPOINT_BASE + '/api/v1'

ADDED_EVENT = 'ADDED'
DELETED_EVENT = 'DELETED'
MODIFIED_EVENT = 'MODIFIED'

LOG = log.getLogger(__name__)


@six.add_metaclass(abc.ABCMeta)
class K8sAPIWatcher(object):
    """A K8s API watcher interface for watching and translating K8s resources.

    This is an abstract class and intended to be interited and conformed its
    abstract property and method by its subclasses. ``WATCH_ENDPOINT``
    represents the API endpoint to watch and ``translate`` is called every time
    when the event notifications are propagated.
    """
    @abc.abstractproperty
    def WATCH_ENDPOINT(self):
        """Gives the K8s API endpoint to be watched and translated.

        This property represents the K8s API endpoint which response is
        consumed by ``translate`` method. Although this is defined as a
        property, the subclasses can just have it as the class level attribute,
        which hides this abstract property.
        """
        pass

    @abc.abstractmethod
    def translate(self, deserialized_json):
        """Translates an event notification from the apiserver.

        This method tranlates the piece of JSON responses into requests against
        the Neutron API. Subclasses of ``K8sAPIWatcher`` **must** implement
        this method to have the concrete translation logic for the specific
        one or more resources.

        This method may be a coroutine function, a decorated generator function
        or an ``async def`` function.

        :param deserialized_json: the deserialized JSON resoponse from the
                                  apiserver
        """
        pass


class K8sPodsWatcher(K8sAPIWatcher):
    """A Pod watcher.

    ``K8sPodsWatcher`` makes a GET request against ``/api/v1/pods?watch=true``
    and receives the event notifications. Then it translates them, when
    applicable, into requests against the Neutron API.

    An example of a JSON response from the apiserver follows. It is
    pretty-printed but the actual response is provided as a single line of
    JSON.
    ::

      {
        "type": "ADDED",
        "object": {
          "kind": "Pod",
          "apiVersion": "v1",
          "metadata": {
            "name": "frontend-qr8d6",
            "generateName": "frontend-",
            "namespace": "default",
            "selfLink": "/api/v1/namespaces/default/pods/frontend-qr8d6",
            "uid": "8e174673-e03f-11e5-8c79-42010af00003",
            "resourceVersion": "107227",
            "creationTimestamp": "2016-03-02T06:25:27Z",
            "labels": {
              "app": "guestbook",
              "tier": "frontend"
            },
            "annotations": {
              "kubernetes.io/created-by": {
                "kind": "SerializedReference",
                "apiVersion": "v1",
                "reference": {
                  "kind": "ReplicationController",
                  "namespace": "default",
                  "name": "frontend",
                  "uid": "8e1657d9-e03f-11e5-8c79-42010af00003",
                  "apiVersion": "v1",
                  "resourceVersion": "107226"
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
                "name": "php-redis",
                "image": "gcr.io/google_samples/gb-frontend:v3",
                "ports": [
                  {
                    "containerPort": 80,
                    "protocol": "TCP"
                  }
                ],
                "env": [
                  {
                    "name": "GET_HOSTS_FROM",
                    "value": "dns"
                  }
                ],
                "resources": {
                  "requests": {
                    "cpu": "100m",
                    "memory": "100Mi"
                  }
                },
                "volumeMounts": [
                  {
                    "name": "default-token-wpfjn",
                    "readOnly": true,
                    "mountPath": "/var/run/secrets/kubernetes.io/serviceaccount"  # noqa
                  }
                ],
                "terminationMessagePath": "/dev/termination-log",
                "imagePullPolicy": "IfNotPresent"
              }
            ],
            "restartPolicy": "Always",
            "terminationGracePeriodSeconds": 30,
            "dnsPolicy": "ClusterFirst",
            "serviceAccountName": "default",
            "serviceAccount": "default",
            "securityContext": {}
          },
          "status": {
            "phase": "Pending"
          }
        }
      }
    """
    PODS_ENDPOINT = K8S_API_ENDPOINT_V1 + '/pods'
    WATCH_ENDPOINT = PODS_ENDPOINT + '?watch=true'

    @asyncio.coroutine
    def translate(self, decoded_json):
        LOG.debug("Pod notification {0}".format(decoded_json))
        event_type = decoded_json.get('type', '')
        content = decoded_json.get('object', {})
        metadata = content.get('metadata', {})
        annotations = metadata.get('annotations', {})
        labels = metadata.get('labels', {})
        if event_type == ADDED_EVENT:
            if constants.K8S_ANNOTATION_PORT_KEY in annotations:
                LOG.debug("Ignore ADD as the pod already has a neutron port")
                return
            sg = labels.get(constants.K8S_LABEL_SECURITY_GROUP_KEY,
                            self._default_sg)
            new_port = {
                'name': metadata.get('name', ''),
                'network_id': self._network['id'],
                'admin_state_up': True,
                'device_owner': constants.DEVICE_OWNER,
                'fixed_ips': [{'subnet_id': self._subnet['id']}],
                'security_groups': [sg]
            }
            try:
                created_port = yield from self.delegate(
                    self.neutron.create_port, {'port': new_port})
                port = created_port['port']
                LOG.debug("Successfully create a port {}.".format(port))
            except n_exceptions.NeutronClientException as ex:
                # REVISIT(yamamoto): We ought to report to a user.
                # eg. marking the pod error.
                LOG.error(_LE("Error happened during creating a"
                              " Neutron port: {0}").format(ex))
                raise
            path = metadata.get('selfLink', '')
            annotations.update(
                {constants.K8S_ANNOTATION_PORT_KEY: jsonutils.dumps(port)})
            annotations.update(
                {constants.K8S_ANNOTATION_SUBNETS_KEY: jsonutils.dumps(
                    [self._subnet])})
            if path:
                data = {
                    "kind": "Pod",
                    "apiVersion": "v1",
                }
                metadata = {}
                metadata.update({'annotations': annotations})
                data.update({'metadata': metadata})
                headers = {
                    'Content-Type': 'application/merge-patch+json',
                    'Accept': 'application/json',
                }
                response = yield from self.delegate(
                    requests.patch, K8S_API_ENDPOINT_BASE + path,
                    data=jsonutils.dumps(data), headers=headers)
                assert response.status_code == requests.codes.ok
                LOG.debug("Successfully updated the annotations.")
        elif event_type == DELETED_EVENT:
            neutron_port = jsonutils.loads(
                annotations.get(constants.K8S_ANNOTATION_PORT_KEY, '{}'))
            if neutron_port:
                port_id = neutron_port['id']
                try:
                    yield from self.delegate(self.neutron.delete_port, port_id)
                except n_exceptions.NeutronClientException as ex:
                    LOG.error(_LE("Error happend during deleting a"
                                  " Neutron port: {0}").format(ex))
                    raise
                LOG.debug("Successfully deleted the neutron port.")
            else:
                LOG.debug('Deletion event without neutron port information. '
                          'Ignoring it...')
        elif event_type == MODIFIED_EVENT:
            old_port = annotations.get(constants.K8S_ANNOTATION_PORT_KEY)
            if old_port:
                sg = labels.get(constants.K8S_LABEL_SECURITY_GROUP_KEY,
                                self._default_sg)
                port_id = jsonutils.loads(old_port)['id']
                update_req = {
                    'security_groups': [sg],
                }
                try:
                    updated_port = yield from self.delegate(
                        self.neutron.update_port,
                        port=port_id, body={'port': update_req})
                    port = updated_port['port']
                    LOG.debug("Successfully update a port {}.".format(port))
                except n_exceptions.NeutronClientException as ex:
                    # REVISIT(yamamoto): We ought to report to a user.
                    # eg. marking the pod error.
                    LOG.error(_LE("Error happened during updating a"
                                  " Neutron port: {0}").format(ex))
                    raise
                # REVISIT(yamamoto): Do we want to update the annotation
                # with the new SG?  Probably.  Note that updating
                # annotation here would yield another MODIFIED_EVENT.


class K8sServicesWatcher(K8sAPIWatcher):
    """A service watcher.

    ``K8sServicesWatcher`` makes a GET request against
    ``/api/v1/services?watch=true`` and receives the event notifications. Then
    it translates them into requrests against the Neutron API.

    An example of a JSON response follows. It is pretty-printed but the
    actual response is provided as a single line of JSON.
    ::

      {
        "type": "ADDED",
        "object": {
          "kind": "Service",
          "apiVersion": "v1",
          "metadata": {
            "name": "kubernetes",
            "namespace": "default",
            "selfLink": "/api/v1/namespaces/default/services/kubernetes",
            "uid": "7c8c674f-d6ed-11e5-8c79-42010af00003",
            "resourceVersion": "7",
            "creationTimestamp": "2016-02-19T09:45:18Z",
            "labels": {
              "component": "apiserver",
              "provider": "kubernetes"
            }
          },
          "spec": {
            "ports": [
              {
                "name": "https",
                "protocol": "TCP",
                "port": 443,
                "targetPort": 443
              }
            ],
            "clusterIP": "192.168.3.1",
            "type": "ClusterIP",
            "sessionAffinity": "None"
          },
          "status": {
            "loadBalancer": {}
          }
        }
      }
    """
    SERVICES_ENDPOINT = K8S_API_ENDPOINT_V1 + '/services'
    WATCH_ENDPOINT = SERVICES_ENDPOINT + '?watch=true'

    def translate(self, decoded_json):
        LOG.debug("Service notification {0}".format(decoded_json))
