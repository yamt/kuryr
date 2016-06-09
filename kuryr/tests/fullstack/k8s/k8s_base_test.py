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

import docker
from oslo_serialization import jsonutils
from oslotest import base

from kuryr.tests.fullstack.k8s import k8s_client
from kuryr import utils
from neutronclient.common import exceptions


class K8sBaseTest(base.BaseTestCase):
    """Basic test class.

    Ensure the connection is done and set the configuration
    """
    def setUp(self):
        # Get the IP addresses of keystone and neutron container services
        super(K8sBaseTest, self).setUp()
        config = k8s_client.generate_basic_config()
        self.k8s = k8s_client.K8sTestClient(config)
        self.docker_client = docker.Client()
        self.neutron = self._get_neutron_client()

    def tearDown(self):
        """Delete all the objects generated on the tests."""
        self.k8s.delete_all_pods()
        super(K8sBaseTest, self).tearDown()

    def assertNeutronPort(self, pod):
        """Ensure that the pod has a neutron port.

        For a given pod, get its metadata and ensure that Neutron
        has the port in its database.

        :param pod: the created K8s pod that should have a corresponding
                    Neutron port
        """
        self.assertIn('annotations', pod.obj['metadata'])
        annotations = pod.obj['metadata']['annotations']
        self.assertIn('kuryr.org/neutron-port', annotations)
        port_annotation = jsonutils.loads(
            annotations['kuryr.org/neutron-port'])

        exception_raised = False
        try:
            port = self.neutron.show_port(port_annotation['id'])['port']
        except exceptions.NotFound:
            exception_raised = True
        self.assertFalse(exception_raised, "Neutron port not created")

        port_ip = port['fixed_ips'][0]
        annotations_ip = port_annotation['fixed_ips'][0]

        # Ensure the port has the same ip as the pod
        self.assertEqual(pod.obj['status']['podIP'], port_ip['ip_address'])

        # Ensure the port has the same name as the pod
        self.assertEqual(pod.obj['metadata']['name'], port['name'])

        # Ensure matching between neutron port and annotations
        self.assertEqual(port_annotation['id'], port['id'])
        self.assertEqual(port_annotation['network_id'], port['network_id'])
        self.assertEqual(port_annotation['name'], port['name'])
        self.assertEqual(annotations_ip['ip_address'], port_ip['ip_address'])
        self.assertEqual(annotations_ip['subnet_id'], port_ip['subnet_id'])

    def assertPingConnection(self, pod1, pod2):
        # I am going to assume single container pods
        pod1_id = pod1.obj['status']['containerStatuses'][0]['containerID']
        pod2_ip = pod2.obj['status']['podIP']

        # ping container2 from container1
        exc = self.docker_client.exec_create(
            container=pod1_id[len('docker://'):], cmd='ping %s -c 1' % pod2_ip)
        resp = self.docker_client.exec_start(exc.get('Id'), tty=True)
        self.assertIn('0% packet loss', str(resp),
                      'Containers communication not working')

    def _get_neutron_client(self):
        """Get neutron client.

        Use docker python client to find out the IPAddress of OpenStack
        services.
        """
        docker_api_version = self.docker_client.version()['ApiVersion']
        keystone_container = self.docker_client.containers(
            filters={'name': 'mnsandboxk8s_keystone_1'})[0]
        neutron_container = self.docker_client.containers(
            filters={'name': 'mnsandboxk8s_neutron_1'})[0]
        if docker_api_version < '1.22':
            # For versions < 1.22, the NetworkSettings only are informed
            # in case of calling inspect. Not when you retrieve the list.
            # So we have to reload the containers
            keystone_id = keystone_container['Id']
            neutron_id = neutron_container['Id']
            keystone_container = self.docker_client.inspect_container(
                keystone_id)
            neutron_container = self.docker_client.inspect_container(
                neutron_id)

        keystone_ns = keystone_container['NetworkSettings']
        neutron_ns = neutron_container['NetworkSettings']
        keystone_ip = keystone_ns['Networks']['bridge']['IPAddress']
        neutron_ip = neutron_ns['Networks']['bridge']['IPAddress']

        return utils.get_neutron_client(
            url="http://%(neutron_ip)s:9696" % {'neutron_ip': neutron_ip},
            username='admin',
            tenant_name='admin',
            password='admin',
            auth_url=("http://%(keystone_ip)s:35357/v2.0" %
                      {'keystone_ip': keystone_ip}),
            ca_cert=None,
            insecure=True)
