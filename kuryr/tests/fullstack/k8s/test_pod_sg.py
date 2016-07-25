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

import time


SG_ANNOTATION = 'kuryr.org/neutron-security-group'


class PodSGTest(k8s_base_test.K8sBaseTest):

    def setUp(self):
        super(PodSGTest, self).setUp()

        # Create the Security group used by tests
        #FIXME: check for exeptions
        sg_body = {'security_group': {'name': 'test-sg'}}
        self.sg = self.neutron.create_security_group(
                        body=sg_body)['security_group']

    def tearDown(self):
        #tead down neutron resources
        super(PodSGTest, self).tearDown()
        #wait for pods to be destroyed before attempting to destroy sg
        time.sleep(10)
        self.neutron.delete_security_group(self.sg['id'])

    def test_create_pod_with_sg(self):
        """Tests creating a pod with a sg different of the default"""
        sg_label = {SG_ANNOTATION: self.sg['id']}
        pod1 = self.k8s.create_pod(name='testpod', labels=sg_label)
        self.assertNeutronPort(pod1)
        self.assertNeutronSG(pod1, self.sg['id'])

    def test_set_pod_sg(self):
        """"Tests changing the security group after creating the pod"""
        pod = self.k8s.create_pod(name='testpod')
        self.assertNeutronPort(pod)
        sg_label = {SG_ANNOTATION: self.sg['id']}
        self.k8s.add_pod_labels(pod, sg_label)
        time.sleep(10)
        self.assertNeutronSG(pod, self.sg['id'])

    def test_unset_pod_sg(self):
        """Tests un-setting the sg label returns the pod to the default sg

        Note: Actually only is checked that the sg has changed,not which
        one is assigned
        """
        pod = self.k8s.create_pod(name='testpod')
        self.assertNeutronPort(pod)
        self.k8s.add_pod_labels(pod, {SG_ANNOTATION: self.sg['id']})
        time.sleep(10)
        self.assertNeutronSG(pod, self.sg['id'])
        self.k8s.add_pod_labels(pod, {SG_ANNOTATION: None})
        time.sleep(10)
        self.assertNeutronSG(pod, self.sg['id'], False)
