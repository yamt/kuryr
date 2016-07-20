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
import ipaddress
import random
import time

from kuryr.raven import raven

from kuryr.common import config
from kuryr.tests.fullstack.k8s import k8s_base_test


class ServicesTest(k8s_base_test.K8sBaseTest):

    def test_create_service(self):
        num_members = 3
        labels = {'app': 'test_deployment'}
        deployment = self.k8s.create_deployment(
            name='demo-test',
            num_replicas=num_members,
            labels=labels)
        service = self.k8s.create_service(
            deployment, name='service-test')
        self.assertNeutronLoadBalancer(service, num_members)

    def test_create_and_delete_external_service(self):
        """Test a whole service lifecycle with public access.

        * Create a K8S service with public access
        * Remove this service
        * Check that all neutron entities have been removed.
        """
        num_members = 1
        labels = {'app': 'test_deployment'}
        deployment = self.k8s.create_deployment(
            name='demo-test-external',
            num_replicas=num_members,
            labels=labels)
        subnet_range = ipaddress.ip_network(
            config.CONF.k8s.cluster_external_subnet)
        fip = subnet_range[random.randint(1, 254)]
        service = self.k8s.create_service(
            deployment, name='service-test-external',
            external_ips=[str(fip)])
        self.assertNeutronLoadBalancer(service, num_members)
        self.assertNeutronFloatingIP(service, fip)

        self.k8s.delete_obj(service)
        # TODO(devvesa): This timeout should be handled by the
        # k8s.delete_obj function
        time.sleep(5)
        self.assertNotNeutronFloatingIP(service, fip)

    def test_create_external_service_unexisting_ip(self):
        """Test that a floating ip is not created.

        When the IP does not exist on Neutron, it does not
        assign the any external IP to the vip, but the
        service is created
        """
        num_members = 1
        labels = {'app': 'test_deployment'}
        deployment = self.k8s.create_deployment(
            name='demo-test-external',
            num_replicas=num_members,
            labels=labels)
        fip = '12.23.34.45'
        service = self.k8s.create_service(
            deployment, name='service-test-external',
            external_ips=[fip])
        self.assertNeutronLoadBalancer(service, num_members)
        self.assertNotNeutronFloatingIP(service, fip)

    def test_external_service_remove_ip(self):
        """Remove public access to a K8S service

        * Create a K8S service with public access
        * Remove the externalIP (and hence the public address)
        * Check out that Neutron has removed the associated FIP
        """
        num_members = 1
        labels = {'app': 'test_deployment'}
        deployment = self.k8s.create_deployment(
            name='demo-test-external',
            num_replicas=num_members,
            labels=labels)
        subnet_range = ipaddress.ip_network(
            config.CONF.k8s.cluster_external_subnet)
        fip_1 = str(subnet_range[random.randint(1, 254)])
        service = self.k8s.create_service(
            deployment, name='service-test-external',
            external_ips=[fip_1])

        self.assertNeutronLoadBalancer(service, num_members)
        self.assertNeutronFloatingIP(service, fip_1)

        # Remove the floating ip and make sure it is not anymore
        # on Neutron
        self.k8s.modify_service(service, external_ips=[])
        self.assertNotNeutronFloatingIP(service, fip_1)

    def test_add_external_service_ip(self):
        """Add an external IP to a existing service

        * Create a K8S service without public access
        * Add an external IP to that service
        * Check out Neutron has assigned the external IP
        """
        num_members = 1
        labels = {'app': 'test_deployment'}
        deployment = self.k8s.create_deployment(
            name='demo-test-external',
            num_replicas=num_members,
            labels=labels)
        subnet_range = ipaddress.ip_network(
            config.CONF.k8s.cluster_external_subnet)
        fip_1 = str(subnet_range[random.randint(1, 254)])

        # Create the service without external ip
        service = self.k8s.create_service(
            deployment, name='service-test-external')
        self.assertNeutronLoadBalancer(service, num_members)
        self.assertNotNeutronFloatingIP(service, fip_1)

        # Add an external ip to the service
        self.k8s.modify_service(service, external_ips=fip_1)
        self.assertNeutronFloatingIP(service, fip_1)

    def test_modify_external_service_ip(self):
        """Modify an externalIP for a service.

        * Create a service and assign it a valid IP
        * Modify the external IP and send the update
        * Check out the new IP is assigned in Neutron
        """
        num_members = 1
        labels = {'app': 'test_deployment'}
        deployment = self.k8s.create_deployment(
            name='demo-test-external',
            num_replicas=num_members,
            labels=labels)
        subnet_range = ipaddress.ip_network(
            config.CONF.k8s.cluster_external_subnet)
        fip_1 = str(subnet_range[random.randint(1, 254)])
        service = self.k8s.create_service(
            deployment, name='service-test-external',
            external_ips=[fip_1])

        self.assertNeutronLoadBalancer(service, num_members)
        self.assertNeutronFloatingIP(service, fip_1)

        fip_2 = str(subnet_range[random.randint(1, 254)])
        self.k8s.modify_service(service, fip_2)
        self.assertNeutronFloatingIP(service, fip_2)

    def test_create_service_with_existing_floating_ip(self):
        """Create a service with an unassociated FIP.

        * Create a FIP in Neutron
        * Create a service with public access with this FIP
        * Check out that Neutron has associated the FIP to
          the service's Load Balancer.
        """
        subnet_range = ipaddress.ip_network(
            config.CONF.k8s.cluster_external_subnet)
        fip = subnet_range[random.randint(1, 254)]

        # Find out External Network ID
        ext_net_name = raven.HARDCODED_NET_NAME + '-external-net'
        ext_net = self.neutron.list_networks(
            name=ext_net_name)['networks'][0]

        # Create a FIP without associate it to any port
        self.neutron.create_floatingip({
            'floatingip': {
                'floating_network_id': ext_net['id'],
                'floating_ip_address': fip}
        })

        num_members = 1
        labels = {'app': 'test_deployment'}
        deployment = self.k8s.create_deployment(
            name='demo-test-external',
            num_replicas=num_members,
            labels=labels)
        service = self.k8s.create_service(
            deployment, name='service-test-external',
            external_ips=[str(fip)])
        self.assertNeutronLoadBalancer(service, num_members)
        self.assertNeutronFloatingIP(service, fip)
