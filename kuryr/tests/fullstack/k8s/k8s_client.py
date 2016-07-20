# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from tempfile import NamedTemporaryFile

from kuryr.common import constants

from oslo_serialization import jsonutils
import pykube
import time
import yaml


def generate_basic_config():
    """Generates a K8s configuration file.

    :returns: the name of the file to be open for another function.
    """
    context = {
        'apiVersion': 'v1',
        'clusters': [{
            'cluster': {
                'server': 'http://localhost:8080'},
            'name': 'test-cluster'}
        ],
        'contexts': [{
            'context': {
                'cluster': 'test-cluster',
                'user': 'test-user'},
            'name': 'test-context'}],
        'current-context': 'test-context',
        # The sandbox k8s api does not have authentication.
        # However, pykube forces us to define this object
        'users': [{
            'name': 'test-user',
            'user': {
                'username': 'admin',
                'token': 'bar'}}]
    }
    with NamedTemporaryFile(mode='w+b', suffix='.yml', delete=False) as tf:
        tf.write(yaml.dump(context, encoding='ascii'))
    return tf.name


class K8sTestClient(object):
    """Kubernetes test client.

    Wraps all the calls to Kubernetes and keeps the session.
    """

    def __init__(self, context_file):
        self.api = pykube.HTTPClient(pykube.KubeConfig.from_file(context_file))

    def _wait_until_created(self, obj, label, max_attempts=100):
        """Waits until a kubernetes object is in 'Ready' status. """

        # TODO(devvesa): Improve this loop somehow
        if hasattr(obj, 'ready'):
            attempts_ready = 0
            while attempts_ready < max_attempts and not obj.ready:
                time.sleep(0.5)
                obj.reload()
                attempts_ready += 1

            if not obj.ready:
                obj.delete()
                raise Exception("%(kind)s %(name)s took too much time "
                                "to be created." %
                                {'kind': obj.kind, 'name': obj.name})

        # Make sure the neutron object has been created and the
        # kubernetes object updated
        attempts_neutron = 0
        while attempts_neutron < max_attempts:
            if 'annotations' in obj.obj['metadata']:
                if label in obj.obj['metadata']['annotations']:
                    return

            time.sleep(0.5)
            obj.reload()
            attempts_neutron += 1

        raise Exception("%(kind)s %(name)s took too much time "
                        "to be created." %
                        {'kind': obj.kind, 'name': obj.name})

    def create_pod(self,
                   name='testpod',
                   image='nginx',
                   namespace='default',
                   labels=None):
        """Create a pod. """

        obj = {
            'apiVersion': 'v1',
            'kind': 'Pod',
            'metadata': {
                'name': name,
                'namespace': namespace,
                'labels': {'environment': 'test'},
                'annotations': {}
            },
            'spec': {
                'containers': [{
                    'name': name,
                    'image': image
                }]
            }
        }

        if labels is not None:
            for k in labels:
                obj['metadata']['labels'][k] = labels[k]

        pod = pykube.Pod(self.api, obj)
        pod.create()
        self._wait_until_created(pod, label='kuryr.org/neutron-port')
        return pod

    def create_namespace(self,
                         name='test-namespace'):
        """Create a namespace. """
        obj = {
            'apiVersion': 'v1',
            'kind': 'Namespace',
            'metadata': {
                'name': name,
                'labels': {
                    'environment': 'test'
                },
            }
        }
        ns = pykube.Namespace(self.api, obj)
        ns.create()
        self._wait_until_created(ns, label='kuryr.org/neutron-network')
        return ns

    def create_deployment(self,
                          num_replicas='3',
                          name='test-deployment',
                          image='nginx',
                          port='80',
                          namespace='default',
                          labels=None):
        """Create a deployment. """
        if not labels:
            labels = []
        labels['environment'] = 'test'
        obj = {
            # 'apiVersion': 'extensions/v1beta1',
            # 'kind': 'Deployment',
            'metadata': {
                'name': name,
                'labels': labels
            },
            'spec': {
                'replicas': num_replicas,
                'template': {
                    'metadata': {
                        'labels': labels
                    },
                    'spec': {
                        'containers': [{
                            'name': name + '-container',
                            'image': image,
                            'ports': [{'containerPort': port}]
                        }]
                    }
                }
            }
        }
        dp = pykube.Deployment(self.api, obj)
        dp.create()

        query = pykube.Pod.objects(self.api).filter(
            selector=labels)

        # Deployment has been created. Now we have to wait until all the
        # pods have been created
        for pod in query.all():
            self._wait_until_created(pod, label='kuryr.org/neutron-port')

        return dp

    def create_service(self,
                       deployment,
                       name='test-service',
                       service_port=80,
                       external_ips=None):

        labels = deployment.obj['metadata']['labels']
        rpcs = deployment.obj['spec']['replicas']
        obj = {
            'metadata': {
                'name': name,
                'labels': labels
            },
            'spec': {
                'ports': [
                    {'port': service_port}
                ],
                'selector': labels
            }
        }
        if external_ips:
            obj['spec']['externalIPs'] = external_ips

        service = pykube.Service(self.api, obj)
        service.create()

        self._wait_until_created(service,
                                 label=constants.K8S_ANNOTATION_VIP_KEY)

        query_endpoint = pykube.Endpoint.objects(self.api).filter(
            selector={'environment__in': {'test'}})

        # Wait for the endpoints of the service to be created
        attempts_endpoint = 0
        max_attempts_endpoint = 100
        found = False
        for endpoint in query_endpoint:
            if endpoint.obj['metadata']['name'] == name:
                found = True
                while ((not endpoint.obj['subsets'] or
                        len(endpoint.obj['subsets'][0]['addresses']) != rpcs)
                        and attempts_endpoint < max_attempts_endpoint):
                    attempts_endpoint += 1
                    time.sleep(0.5)
                    endpoint.reload()
                if attempts_endpoint > max_attempts_endpoint:
                    raise Exception("Endpoint %(name)s took too much time "
                                    "to be created." %
                                    {'name': endpoint.name})
                else:
                    break

        if not found:
            raise Exception("Endpoints not created for service %s", name)

        return service

    def modify_service(self, service,
                       external_ips=None, max_attempts=100):

        # We right now only consider the modification of external IPs
        # TODO(devvesa): ensure multiple ips
        service.reload()
        if external_ips:
            service.obj['spec']['externalIPs'] = [external_ips]
            service.obj['spec']['deprecatedPublicIPs'] = [external_ips]
        elif 'externalIPs' in service.obj['spec']:
            # Way to delete keys on merge-patches according to RFC:
            #     https://tools.ietf.org/html/rfc7386
            service.obj['spec']['externalIPs'] = None
            service.obj['spec']['deprecatedPublicIPs'] = None

        service.update()

        attempts_neutron = 0
        while attempts_neutron < max_attempts:
            annotations = service.obj['metadata']['annotations']
            if (external_ips and
                constants.K8S_ANNOTATION_FIP_KEY in annotations and
                jsonutils.loads(annotations[constants.K8S_ANNOTATION_FIP_KEY])
                    ['floating_ip_address'] == external_ips):

                # New external IP is assigned
                break

            if (not external_ips and
                constants.K8S_ANNOTATION_FIP_KEY not in annotations):

                # Deleted external IP is removed
                break

            time.sleep(0.5)
            service.reload()
            attempts_neutron += 1

    def delete_obj(self, obj, max_attempts=120):

        try:
            obj.delete()
        except pykube.exceptions.HTTPError:
            # There is a conflict error raised eventually that just
            # tells the K8s api requester to wait. Skip it
            pass

        attempts = 0
        while attempts < max_attempts and obj.exists():
            time.sleep(0.5)
            attempts += 1

        if not obj.exists():
            return

        raise Exception("%(kind)s %(name)s took too much time to be deleted."
                        "Manual cleaning is required!" %
                        {'kind': obj.kind, 'name': obj.name})

    def add_pod_labels(self, pod, labels):
        """Add labels o a Pod

        Add labels to the already existing labels for a pod
        Assumes the pod already has labels as the environment is set
        at creation time
        """
        pod_labels = pod.obj['metadata']['labels']
        for k in labels:
            pod_labels[k] = labels[k]
        pod.update()

    def delete_all(self):
        """Delete all pods created."""
        query_ns = pykube.Namespace.objects(self.api).all()
        for ns in query_ns:

            # Remove services
            query_service = pykube.Service.objects(self.api).filter(
                namespace=ns.name,
                selector={'environment__in': {'test'}})
            for service in query_service:
                self.delete_obj(service)

            # Remove deployments
            query_deployment = pykube.Deployment.objects(self.api).filter(
                namespace=ns.name,
                selector={'environment__in': {'test'}})
            for deployment in query_deployment:
                self.delete_obj(deployment)

            # Remove replica sets
            query_rs = pykube.ReplicaSet.objects(self.api).filter(
                namespace=ns.name,
                selector={'environment__in': {'test'}})
            for rs in query_rs:
                self.delete_obj(rs)

            # Remove Pods
            query_pod = pykube.Pod.objects(self.api).filter(
                namespace=ns.name,
                selector={'environment__in': {'test'}})
            for pod in query_pod:
                self.delete_obj(pod)

            if ns.name != 'default':
                self.delete_obj(ns)
