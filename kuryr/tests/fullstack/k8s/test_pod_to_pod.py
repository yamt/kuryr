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

from kuryr.tests.fullstack.k8s import k8s_base_test


class PodToPodTest(k8s_base_test.K8sBaseTest):

    def test_create_connected_pods_same_namespace(self):
        pod1 = self.k8s.create_pod(name='testpod1')
        pod2 = self.k8s.create_pod(name='testpod2')
        self.assertNeutronPort(pod1)
        self.assertNeutronPort(pod2)
        self.assertPingConnection(pod1, pod2)

    def test_create_connected_pods_different_namespace(self):
        ns = self.k8s.create_namespace(name='ns1')
        self.assertNeutronNetwork(ns)
        pod1 = self.k8s.create_pod(name='testpod3')
        pod2 = self.k8s.create_pod(name='testpod4', namespace=ns.name)
        self.assertNeutronPort(pod1)
        self.assertNeutronPort(pod2)
        self.assertPingConnection(pod1, pod2)
