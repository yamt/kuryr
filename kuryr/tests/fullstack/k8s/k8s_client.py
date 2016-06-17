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

    def _wait_until_created(self, obj, label, max_attempts=1000):
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
                   namespace='default'):
        """Create a pod. """

        obj = {
            'apiVersion': 'v1',
            'kind': 'Pod',
            'metadata': {
                'name': name,
                'namespace': namespace,
                'labels': {
                    'environment': 'test'
                },
                'annotations': {}
            },
            'spec': {
                'containers': [{
                    'name': name,
                    'image': image
                }]
            }
        }
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

    def delete_all(self):
        """Delete all pods created."""
        query_ns = pykube.Namespace.objects(self.api).all()
        for ns in query_ns:
            query = pykube.Pod.objects(self.api).filter(
                namespace=ns.name,
                selector={'environment__in': {'test'}})
            for pod in query:
                self.delete_obj(pod)
            if ns.name != 'default':
                self.delete_obj(ns)
