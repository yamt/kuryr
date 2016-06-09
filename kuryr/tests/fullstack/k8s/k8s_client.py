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

    def _wait_until_created(self, obj, max_attempts=1000):
        """Waits until a kubernetes object is in 'Ready' status. """

        # TODO(devvesa): Improve this loop somehow
        attempts = 0
        while attempts < max_attempts and not obj.ready:
            time.sleep(0.5)
            obj.reload()
            attempts += 1

        if obj.ready:
            return

        obj.delete()
        raise Exception("%(kind)s %(name)s took too much time to be created." %
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
        self._wait_until_created(pod)
        return pod

    def delete_all_pods(self):
        """Delete pod."""
        query = pykube.Pod.objects(self.api).filter(
            selector={'environment__in': {'test'}})
        for pod in query:
            pod.delete()
