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


class ServicesTest(k8s_base_test.K8sBaseTest):

    def test_define_service(self):
        num_members = 3
        labels = {'app': 'test_deployment'}
        deployment = self.k8s.create_deployment(
            name='demo-test',
            num_replicas=num_members,
            labels=labels)
        service = self.k8s.create_service(
            deployment, name='service-test')
        self.assertNeutronLoadBalancer(service, num_members)
