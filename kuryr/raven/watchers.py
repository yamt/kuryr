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
import random

from neutronclient.common import exceptions as n_exceptions
from oslo_log import log
from oslo_serialization import jsonutils
from oslo_utils import excutils
import requests
import six

from kuryr._i18n import _LE
from kuryr._i18n import _LI
from kuryr._i18n import _LW
from kuryr.common import config
from kuryr.common import constants
from kuryr.raven import aio
from kuryr import utils


ADDED_EVENT = 'ADDED'
DELETED_EVENT = 'DELETED'
MODIFIED_EVENT = 'MODIFIED'

LOG = log.getLogger(__name__)

PATCH_HEADERS = {
    'Content-Type': 'application/merge-patch+json',
    'Accept': 'application/json',
}


@asyncio.coroutine
def _update_annotation(delegator, path, kind, annotations):
    data = {
        "kind": kind,
        "apiVersion": "v1",
    }
    metadata = {}
    metadata.update({'annotations': annotations})
    data.update({'metadata': metadata})

    response = yield from delegator(
        requests.patch, constants.K8S_API_ENDPOINT_BASE + path,
        data=jsonutils.dumps(data), headers=PATCH_HEADERS)
    assert response.status_code == requests.codes.ok
    LOG.debug("Successfully updated the annotations.")


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
    PODS_ENDPOINT = constants.K8S_API_ENDPOINT_V1 + '/pods'
    WATCH_ENDPOINT = PODS_ENDPOINT + '?watch=true'

    @asyncio.coroutine
    def translate(self, decoded_json):
        """Translates a K8s pod into a Neutron port.

        The service translation can be assumed to be done before replication
        controllers and pods are created based on the "best practice" of K8s
        resource definition. So in this method pods are translated into ports
        based on the service information.

        When the port is created, the pod information is updated with the port
        information to provide the necessary information for the bindings.

        If the pod belongs to the service and the pod is deleted, the
        associated pool member is deleted as well in the cascaded way.

        :param decoded_json: A pod event to be translated.
        """
        LOG.debug("Pod notification {0}".format(decoded_json))
        event_type = decoded_json.get('type', '')
        content = decoded_json.get('object', {})
        metadata = content.get('metadata', {})
        annotations = metadata.get('annotations', {})
        labels = metadata.get('labels', {})
        namespace = metadata.get('namespace')
        if event_type == ADDED_EVENT:
            namespace_network_name = namespace
            namespace_networks = self.neutron.list_networks(
                name=namespace_network_name)['networks']
            if not namespace_networks:
                # Network of the namespace for this pod is not created yet.
                # TODO(devvesa): maybe raising an error is better
                LOG.warning(_LW("Network namespace %(ns)s for pod %(pod)s "
                                "is not created yet"),
                            {'ns': namespace_network_name,
                             'pod': metadata.get('name', '')})
                return

            namespace_network = namespace_networks[0]

            namespace_subnet_name = utils.get_subnet_name(namespace)
            namespace_subnets = self.neutron.list_subnets(
                name=namespace_subnet_name)['subnets']
            if not namespace_subnets:
                # Subnet of the namespace for this pod is not created yet.
                # TODO(devvesa): maybe raising an error is better
                LOG.warning(_LW("Subnet namespace %(ns)s for pod %(pod)s "
                                "is not created yet"),
                            {'ns': namespace_subnet_name,
                             'pod': metadata.get('name', '')})
                return
            namespace_subnet = namespace_subnets[0]

            if constants.K8S_ANNOTATION_PORT_KEY in annotations:
                LOG.debug("Ignore ADD as the pod already has a neutron port")
                return
            sg = labels.get(constants.K8S_LABEL_SECURITY_GROUP_KEY,
                            self._default_sg)
            new_port = {
                'name': metadata.get('name', ''),
                'network_id': namespace_network['id'],
                'admin_state_up': True,
                'device_owner': constants.DEVICE_OWNER,
                'fixed_ips': [{'subnet_id': namespace_subnet['id']}],
                'security_groups': [sg]
            }
            try:
                created_port = yield from self.delegate(
                    self.neutron.create_port, {'port': new_port})
                port = created_port['port']
                LOG.debug("Successfully create a port {}.".format(port))
            except n_exceptions.NeutronClientException as ex:
                with excutils.save_and_reraise_exception():
                    # REVISIT(yamamoto): We ought to report to a user.
                    # eg. marking the pod error.
                    LOG.error(_LE("Error happened during creating a"
                                  " Neutron port: {0}").format(ex))
            path = metadata.get('selfLink', '')
            annotations.update(
                {constants.K8S_ANNOTATION_PORT_KEY: jsonutils.dumps(port)})
            annotations.update(
                {constants.K8S_ANNOTATION_SUBNET_KEY: jsonutils.dumps(
                    namespace_subnet)})
            if path:
                yield from _update_annotation(self.delegate, path, 'Pod',
                                              annotations)

        elif event_type == DELETED_EVENT:
            neutron_port = jsonutils.loads(
                annotations.get(constants.K8S_ANNOTATION_PORT_KEY, '{}'))
            if neutron_port:
                port_id = neutron_port['id']
                try:
                    yield from self.delegate(self.neutron.delete_port, port_id)
                except n_exceptions.NeutronClientException as ex:
                    with excutils.save_and_reraise_exception():
                        LOG.error(_LE("Error happend during deleting a"
                                      " Neutron port: {0}").format(ex))
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
                    with excutils.save_and_reraise_exception():
                        # REVISIT(yamamoto): We ought to report to a user.
                        # eg. marking the pod error.
                        LOG.error(_LE("Error happened during updating a"
                                      " Neutron port: {0}").format(ex))
                # REVISIT(yamamoto): Do we want to update the annotation
                # with the new SG?  Probably.  Note that updating
                # annotation here would yield another MODIFIED_EVENT.


class K8sNamespaceWatcher(K8sAPIWatcher):
    """A namespace watcher.

    ``K8sNamespacesWatcher`` makes a GET request against
    ``/api/v1/namespaces?watch=true`` and receives the event notifications.
    Then it translates them into requrests against the Neutron API.

    An example of a JSON response follows. It is pretty-printed but the
    actual response is provided as a single line of JSON.
    ::

      {
        "type": "ADDED",
        "object": {
          "kind": "Namespace",
          "apiVersion": "v1",
          "metadata": {
            "name": "test",
            "selfLink": "/api/v1/namespaces/test",
            "uid": "f094ea6b-06c2-11e6-8128-42010af00003",
            "resourceVersion": "497821",
            "creationTimestamp": "2016-04-20T06:41:41Z"
          },
          "spec": {
            "finalizers": [
              "kubernetes"
            ]
          },
          "status": {
            "phase": "Active"
          }
        }
      }
    """
    NAMESPACES_ENDPOINT = constants.K8S_API_ENDPOINT_V1 + '/namespaces'
    WATCH_ENDPOINT = NAMESPACES_ENDPOINT + '?watch=true'

    @asyncio.coroutine
    def translate(self, decoded_json):
        """Translates a K8s namespace into two Neutron networks and subnets.

        The two pairs of the network and the subnet are created for the cluster
        network. Each subnet is associated with its dedicated network. They're
        named in the way the administrator can recognise what they're easily
        based on the names of the namespaces.

        :param decoded_json: A namespace event to be translated.
        """
        LOG.debug("Namespace notification %s", decoded_json)
        event_type = decoded_json.get('type', '')
        content = decoded_json.get('object', {})
        metadata = content.get('metadata', {})
        annotations = metadata.get('annotations', {})
        if event_type == ADDED_EVENT:

            namespace_network_name = metadata['name']
            namespace_subnet_name = namespace_network_name + '-subnet'
            namespace_networks = self.neutron.list_networks(
                name=namespace_network_name)['networks']
            # Ensure the network exists
            if namespace_networks:
                namespace_network = namespace_networks[0]
            else:
                # NOTE(devvesa): To avoid name collision, we should add the uid
                #                of the namespace in the neutron tags info
                network_response = self.neutron.create_network(
                    {'network': {'name': namespace_network_name}})
                namespace_network = network_response['network']
                LOG.debug('Created a new network {0}'.format(
                    namespace_network))
                annotations.update(
                    {constants.K8S_ANNOTATION_NETWORK_KEY: jsonutils.dumps(
                        namespace_network)})

            # Ensure the subnet exists
            namespace_subnets = self.neutron.list_subnets(
                name=namespace_subnet_name)['subnets']
            if (namespace_subnets
                    and constants.K8S_ANNOTATION_SUBNET_KEY):
                namespace_subnet = namespace_subnets[0]
            else:
                new_subnet = {
                    'name': namespace_subnet_name,
                    'network_id': namespace_network['id'],
                    'ip_version': 4,  # TODO(devvesa): parametrize this value
                    'subnetpool_id': self._subnetpool['id'],
                }
                subnet_response = self.neutron.create_subnet(
                    {'subnet': new_subnet})
                namespace_subnet = subnet_response['subnet']
                LOG.debug('Created a new subnet %s', namespace_subnet)

            annotations.update(
                {constants.K8S_ANNOTATION_SUBNET_KEY: jsonutils.dumps(
                    namespace_subnet)})

            neutron_network_id = namespace_network['id']
            # Router is created in the subnet pool at raven start time.
            neutron_router_id = self._router['id']
            neutron_subnet_id = namespace_subnet['id']
            filtered_ports = self.neutron.list_ports(
                device_owner='network:router_interface',
                device_id=neutron_router_id,
                network_id=neutron_network_id)['ports']

            router_ports = self._get_router_ports_by_subnet_id(
                neutron_subnet_id, filtered_ports)

            if not router_ports:
                self.neutron.add_interface_router(
                    neutron_router_id, {'subnet_id': neutron_subnet_id})
            else:
                LOG.debug('The subnet {0} is already bound to the router'
                          .format(neutron_subnet_id))

            path = metadata.get('selfLink', '')
            metadata.update({'annotations': annotations})
            content.update({'metadata': metadata})
            headers = {
                'Content-Type': 'application/merge-patch+json',
                'Accept': 'application/json',
            }
            response = yield from self.delegate(
                requests.patch, constants.K8S_API_ENDPOINT_BASE + path,
                data=jsonutils.dumps(content), headers=headers)
            assert response.status_code == requests.codes.ok
            LOG.debug("Successfully updated the annotations.")
        elif event_type == DELETED_EVENT:
            namespace_network = jsonutils.loads(
                annotations.get(constants.K8S_ANNOTATION_NETWORK_KEY, '{}'))
            namespace_subnet = jsonutils.loads(
                annotations.get(constants.K8S_ANNOTATION_SUBNET_KEY, '{}'))

            neutron_network_id = namespace_network.get('id', None)
            neutron_router_id = self._router.get('id', None)
            neutron_subnet_id = namespace_subnet.get('id', None)

            if namespace_network:

                try:
                    self.neutron.remove_interface_router(
                        neutron_router_id,
                        {'subnet_id': neutron_subnet_id})
                    self.neutron.delete_network(
                        neutron_network_id)
                except n_exceptions.NeutronClientException as ex:
                    with excutils.save_and_reraise_exception():
                        LOG.error(_LE("Error happend during deleting a"
                                      " Neutron Network: {0}"), ex)
                LOG.debug("Successfully deleted the neutron network.")
            else:
                LOG.debug('Deletion event without neutron network information.'
                          'Ignoring it...')

        LOG.debug('Successfully translated the namespace')


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
    SERVICES_ENDPOINT = constants.K8S_API_ENDPOINT_V1 + '/services'
    WATCH_ENDPOINT = SERVICES_ENDPOINT + '?watch=true'

    @asyncio.coroutine
    def translate(self, decoded_json):
        """Translates a K8s service into a Neutron Pool and a Neutron VIP.

        The service translation can be assumed to be done before replication
        controllers and pods are created based on the "best practice" of K8s
        resource definition. So in this mothod only the Neutorn Pool and the
        Neutorn VIP are created. The Neutron Pool Members are added in the
        namespace translations.

        When the Neutron Pool is created, the service is updated with the Pool
        information in order that the namespace event translator can associate
        the Neutron Pool Members with the Pool. The namspace event traslator
        inspects the service information in the apiserver and retrieve the
        necessary Pool information.

        :param decoded_json: A service event to be translated.
        """
        LOG.debug("Service notification {0}".format(decoded_json))
        event_type = decoded_json.get('type', '')
        content = decoded_json.get('object', {})
        metadata = content.get('metadata', {})
        annotations = metadata.get('annotations', {})
        if event_type == ADDED_EVENT:
            if constants.K8S_ANNOTATION_POOL_KEY in annotations:
                LOG.debug('Ignore an ADDED event as the pool already has a '
                          'neutron port')
                return
            service_name = metadata.get('name', '')
            namespace = metadata.get(
                'namespace', constants.K8S_DEFAULT_NAMESPACE)
            cluster_subnet_name = utils.get_subnet_name(namespace)
            # TODO(tfukushima): Make the following line non-blocking.
            # Since K8sNamespaceWatcher and K8sPodsWatcher depend on the
            # blocking requests against Neutron, I just leave this. However,
            # this should be replaced with the non-blocking call with
            # self.delegate with some synchronization mechanism.
            cluster_subnet_response = self.neutron.list_subnets(
                name=cluster_subnet_name)
            cluster_subnets = cluster_subnet_response['subnets']
            if not cluster_subnets:
                LOG.warning(
                    _LW('The namespace %s is not translated yet.'), namespace)
                return
            cluster_subnet = cluster_subnets[0]

            service_spec = content.get('spec', {})
            service_type = service_spec.get('type', 'ClusterIP')
            if service_type != 'ClusterIP':
                LOG.warning(
                    _LW('Non-ClusterIP type service is not supported. '
                        'Ignoring the event.'))
                return

            service_ports = service_spec.get('ports', [])
            # Assume there's the only single port spec.
            port = service_ports[0]
            protocol = port['protocol']
            protocol_port = port['targetPort']
            pool_request = {
                'pool': {
                    'name': service_name,
                    'protocol': protocol,
                    'subnet_id': cluster_subnet['id'],
                    'lb_method': config.CONF.raven.lb_method,
                },
            }
            try:
                created_pool = yield from self.delegate(
                    self.neutron.create_pool, pool_request)
                pool = created_pool['pool']
                LOG.debug('Succeeded to created a pool %s', pool)
            except n_exceptions.NeutronClientException as ex:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE("Error happened during creating a"
                                  " Neutron pool: %s"), ex)

            path = metadata.get('selfLink', '')
            annotations.update(
                {constants.K8S_ANNOTATION_POOL_KEY: jsonutils.dumps(pool)})

            pool_id = pool['id']
            cluster_ip = service_spec['clusterIP']
            vip_request = {
                'vip': {
                    # name is not necessarily unique and the service name is
                    # used for the group of the vips.
                    'name': service_name,
                    'pool_id': pool_id,
                    'subnet_id': self._service_subnet['id'],
                    'address': cluster_ip,
                    'protocol': protocol,
                    'protocol_port': protocol_port,
                },
            }
            try:
                created_vip = yield from self.delegate(
                    self.neutron.create_vip, vip_request)
                vip = created_vip['vip']
                LOG.debug('Succeeded to created a VIP {0}'.format(vip))
            except n_exceptions.NeutronClientException as ex:
                LOG.error(_LE("Error happened during creating a"
                              " Neutron VIP: %s"), ex)
                try:
                    yield from self.delegate(
                        self.neutron.delete_pool, pool_id)
                except n_exceptions.NeutronClientException as ex:
                    LOG.error(_LE('Error happened during cleaning up a '
                                  'Neutron pool: %s on creating the VIP.'), ex)
                    raise
                raise
            annotations.update(
                {constants.K8S_ANNOTATION_VIP_KEY: jsonutils.dumps(vip)})

            if path:
                yield from _update_annotation(self.delegate, path, 'Service',
                                              annotations)

        elif event_type == DELETED_EVENT:
            neutron_pool = jsonutils.loads(
                annotations.get(constants.K8S_ANNOTATION_POOL_KEY, '{}'))
            if not neutron_pool:
                LOG.debug('Deletion event without neutron pool information. '
                          'Ignoring it.')
                return
            neutron_vip = jsonutils.loads(
                annotations.get(constants.K8S_ANNOTATION_VIP_KEY, '{}'))
            if not neutron_vip:
                LOG.debug('Deletion event without neutron VIP information. '
                          'Ignoring it.')
                return

            # VIP should be delete before the pool.
            try:
                vip_id = neutron_vip['id']
                neutron_vips_response = yield from self.delegate(
                    self.neutron.list_vips, id=vip_id)
                neutron_vips = neutron_vips_response['vips']
                if neutron_vips:
                    yield from self.delegate(self.neutron.delete_vip, vip_id)
                else:
                    LOG.warning(_LW("The VIP {0} doesn't exist. Ignoring the "
                                    "deletion of the VIP.")
                                .format(vip_id))
            except n_exceptions.NeutronClientException as ex:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE("Error happened during deleting a"
                                  " Neutron VIP: {0}").format(ex))
            LOG.debug('Successfully deleted the Neutron VIP {0}'
                      .format(neutron_vip))

            try:
                pool_id = neutron_pool['id']
                neutron_pools_response = yield from self.delegate(
                    self.neutron.list_pools, id=pool_id)
                neutron_pools = neutron_pools_response['pools']
                if neutron_pools:
                    yield from self.delegate(self.neutron.delete_pool, pool_id)
                else:
                    LOG.warning(_LW("The pool {0} doesn't exist. Ignoring the "
                                    "deletion of the pool.")
                                .format(vip_id))
            except n_exceptions.NeutronClientException as ex:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE("Error happened during deleting a"
                                  " Neutron pool: {0}").format(ex))
            LOG.debug('Successfully deleted the Neutron pool {0}'
                      .format(neutron_pool))


class K8sEndpointsWatcher(K8sAPIWatcher):
    """An endpoints watcher.

    ``K8sEndpointsWatcher`` makes a GET request against
    ``/api/v1/endpoints?watch=true`` and receives the event notifications. Then
    it translates them into requrests against the Neutron API.

    An example of a JSON response follows. It is pretty-printed but the
    actual response is provided as a single line of JSON.
    ::

      {
        "type": "ADDED",
        "object": {
          "kind": "Endpoints",
          "apiVersion": "v1",
          "metadata": {
            "name": "frontend",
            "namespace": "default",
            "selfLink": "/api/v1/namespaces/default/endpoints/frontend",
            "uid": "436bf3f9-1e53-11e6-8128-42010af00003",
            "resourceVersion": "1034915",
            "creationTimestamp": "2016-05-20T06:22:44Z",
            "labels": {
              "app": "guestbook",
              "tier": "frontend"
            }
          },
          "subsets": [
            {
              "addresses": [
                {
                  "ip": "172.16.0.77",
                  "targetRef": {
                    "kind": "Pod",
                    "namespace": "default",
                    "name": "frontend-g607i",
                    "uid": "43748958-1e53-11e6-8128-42010af00003",
                    "resourceVersion": "1034914"
                  }
                },
                {
                  "ip": "172.16.0.78",
                  "targetRef": {
                    "kind": "Pod",
                    "namespace": "default",
                    "name": "frontend-hl8ic",
                    "uid": "4374c8f0-1e53-11e6-8128-42010af00003",
                    "resourceVersion": "1034899"
                  }
                },
                {
                  "ip": "172.16.0.79",
                  "targetRef": {
                    "kind": "Pod",
                    "namespace": "default",
                    "name": "frontend-blc48",
                    "uid": "4374dd81-1e53-11e6-8128-42010af00003",
                    "resourceVersion": "1034912"
                  }
                }
              ],
              "ports": [
                {
                  "port": 80,
                  "protocol": "TCP"
                }
              ]
            }
          ]
        }
      }
    """
    SERVICES_ENDPOINT = constants.K8S_API_ENDPOINT_V1 + '/endpoints'
    WATCH_ENDPOINT = SERVICES_ENDPOINT + '?watch=true'

    @asyncio.coroutine
    def translate(self, decoded_json):
        """Translates a K8s endpoints into a Neutorn Pool Member.

        The endpoints translation can be assumed to be done after the service
        translation, which creates the Neutron Pool and the VIP.

        :param decoded_json: An endpoint event to be translated.
        """
        @asyncio.coroutine
        def create_pool_members(pool_id, subsets, reuse=False):
            """Creates pool members from the given subsets of the endpoints.

            :param pool_id: The ID of the pool with which the pool members are
                            associated.
            :param subsets: The dictionary represents the subsets property.
            :param reuse: Whether to check for the existence of the pool
                          members. Defaults to False, which is what you want
                          for new pools that have had no members created yet.
            """
            for subset in subsets:
                ports = subset['ports']
                addresses = subset['addresses']
                # Create members for each combination of the address and the
                # port.
                for port in ports:
                    protocol_port = port['port']
                    for address in addresses:
                        ip_address = address['ip']
                        if reuse:
                            members_response = yield from \
                                self.sequential_delegate(
                                    self.neutron.list_members, pool_id=pool_id,
                                    address=ip_address,
                                    protocol_port=protocol_port)
                            members = members_response['members']
                            if members:
                                continue

                        member_request = {
                            'member': {
                                'pool_id': pool_id,
                                'address': ip_address,
                                'protocol_port': protocol_port,
                                'weight': 1,
                            },
                        }
                        try:
                            # Make sure the requests against Neutron API are
                            # scheduled sequentially.
                            member_response = yield from \
                                self.sequential_delegate(
                                    self.neutron.create_member, member_request)
                            member = member_response['member']
                            LOG.debug('Successfully created a new member '
                                      '%(member)s for the pool %(pool_id)s',
                                      {'member': member, 'pool_id': pool_id})
                        except n_exceptions.NeutronClientException as ex:
                            with excutils.save_and_reraise_exception():
                                LOG.error(_LE('Error happend during creating '
                                              'a Neutron loadbalancer pool '
                                              'member: %s'), ex)

        LOG.debug('Endpoints notification %s', decoded_json)
        event_type = decoded_json.get('type', '')
        content = decoded_json.get('object', {})
        metadata = content.get('metadata', {})
        subsets = content.get('subsets', [])

        namespace = metadata.get('namespace',
                                 constants.K8S_DEFAULT_NAMESPACE)
        service_name = metadata['name']
        # FIXME(tfukushima): Ignore kubernetes service for now.
        if service_name == 'kubernetes':
            LOG.info(_LI('Ignoring "kubernetes" service since it is not '
                         'supported yet'))
            return
        service_endpoint = utils.get_service_endpoint(namespace, service_name)

        # Poll until K8sServicesWatcher finishes the translation of the
        # corresponding service.
        retries = 0
        while retries < constants.MAX_RETRIES:
            service_response = yield from aio.methods.get(
                endpoint=service_endpoint, loop=self._event_loop)
            status, _, _ = yield from service_response.read_headers()
            assert status == 200
            service_response_body = yield from service_response.read()
            service = utils.utf8_json_decoder(service_response_body)
            service_metadata = service.get('metadata', {})
            service_annotations = service_metadata.get('annotations', {})
            serialized_pool = service_annotations.get(
                constants.K8S_ANNOTATION_POOL_KEY, '{}')
            pool = jsonutils.loads(serialized_pool)
            if pool:
                break
            else:
                retries += 1
                backoff_unit = constants.BACKOFF_UNIT
                backoff_time = backoff_unit * random.randint(
                    0, (2 ** retries) - 1)
                wait_time = min(backoff_time, constants.MAX_WAIT_INTERVAL)
                LOG.debug('The service is not translated yet. Retried {0} '
                          'times and the next interval is {1:.2f} seconds.'
                          .format(retries, wait_time))
                yield from self.wait_for(wait_time)

        if retries >= constants.MAX_RETRIES:
            LOG.error(_LE('Failed to fetch the pool information in the '
                          'service %s. The service translation might have '
                          'been failed.'), service_name)
            return
        pool_id = pool['id']
        # The pool member deletion is done by K8sServicesWatcher by deleting
        # the associated pool that deletes its members in the cascaded way.
        if event_type == ADDED_EVENT:
            yield from create_pool_members(pool_id, subsets)
        elif event_type == MODIFIED_EVENT:
            # The pool members in subnets could be created already.
            yield from create_pool_members(pool_id, subsets, reuse=True)
