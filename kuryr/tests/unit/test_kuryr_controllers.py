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
import ddt

from kuryr import controllers
from kuryr.tests.unit import base


@ddt.ddt
class TestKuryrControllerHelpers(base.TestKuryrBase):
    """Unit tests for controller helpers."""
    @ddt.data(
        {'subnets': [{
            'name': 'foo4',
            'network_id': 'f7271ca7-3dd8-4a5e-8615-1b8a8a2bf48e',
            'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
            'allocation_pools': [{'start': '192.168.1.2',
                                  'end': '192.168.1.254'}],
            'gateway_ip': '192.168.1.1',
            'ip_version': 4,
            'cidr': '192.168.1.0/24',
            'id': 'a6b73736-6d87-4e5a-9afd-ec40a1e8c4c9',
            'enable_dhcp': True
        }, {
            'name': 'foo6',
            'network_id': 'f7271ca7-3dd8-4a5e-8615-1b8a8a2bf48e',
            'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
            'allocation_pools': [{'start': 'fe80::f816:3eff:fe20:57c4',
                                  'end': 'fe80::ffff:ffff:ffff:ffff'}],
            'gateway_ip': 'fe80::f816:3eff:fe20:57c3',
            'ip_version': 6,
            'cidr': 'fe80::/64',
            'id': '639771be-9436-4011-8a90-8dcf252bee24',
            'enable_dhcp': True
        }]},
        {'subnets': [{
            'name': 'foo4',
            'network_id': 'f7271ca7-3dd8-4a5e-8615-1b8a8a2bf48e',
            'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
            'allocation_pools': [{'start': '192.168.1.2',
                                  'end': '192.168.1.254'}],
            'gateway_ip': '192.168.1.1',
            'ip_version': 4,
            'cidr': '192.168.1.0/24',
            'id': 'a6b73736-6d87-4e5a-9afd-ec40a1e8c4c9',
            'enable_dhcp': True
        }]})
    def test__get_subnets_by_attrs_unique(self, response):
        net_id = response['subnets'][0]['network_id']

        self.mox.StubOutWithMock(controllers.app.neutron, 'list_subnets')
        controllers.app.neutron.list_subnets(
            network_id=net_id,
            cidr='192.168.1.0/24').AndReturn(response)

        self.mox.ReplayAll()
        controllers._get_subnets_by_attrs(
            unique=True, network_id=net_id, cidr='192.168.1.0/24')

    @ddt.data(
        {'subnets': [{
            'name': 'boo4',
            'network_id': 'f7271ca7-3dd8-4a5e-8615-1b8a8a2bf48e',
            'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
            'allocation_pools': [{'start': '192.168.1.2',
                                  'end': '192.168.1.254'}],
            'gateway_ip': '192.168.1.1',
            'ip_version': 4,
            'cidr': '192.168.1.0/24',
            'id': 'a6b73736-6d87-4e5a-9afd-ec40a1e8c4c9',
            'enable_dhcp': True
        }, {
            'name': 'foo6',
            'network_id': 'f7271ca7-3dd8-4a5e-8615-1b8a8a2bf48e',
            'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
            'allocation_pools': [{'start': 'fe80::f816:3eff:fe20:57c4',
                                  'end': 'fe80::ffff:ffff:ffff:ffff'}],
            'gateway_ip': 'fe80::f816:3eff:fe20:57c3',
            'ip_version': 6,
            'cidr': 'fe80::/64',
            'id': '639771be-9436-4011-8a90-8dcf252bee24',
            'enable_dhcp': True
        }, {
            'name': 'boourns4',
            'network_id': 'f7271ca7-3dd8-4a5e-8615-1b8a8a2bf48e',
            'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
            'allocation_pools': [{'start': '192.168.1.2',
                                  'end': '192.168.1.254'}],
            'gateway_ip': '192.168.1.1',
            'ip_version': 4,
            'cidr': '192.168.1.0/24',
            'id': 'e99bd0c3-bdde-4f2f-8ff8-401c670c71c4',
            'enable_dhcp': True
        }]},
        {'subnets': [{
            'name': 'boourns4',
            'network_id': 'f7271ca7-3dd8-4a5e-8615-1b8a8a2bf48e',
            'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
            'allocation_pools': [{'start': '192.168.1.2',
                                  'end': '192.168.1.254'}],
            'gateway_ip': '192.168.1.1',
            'ip_version': 4,
            'cidr': '192.168.1.0/24',
            'id': 'e99bd0c3-bdde-4f2f-8ff8-401c670c71c4',
            'enable_dhcp': True
        }, {
            'name': 'boo4',
            'network_id': 'f7271ca7-3dd8-4a5e-8615-1b8a8a2bf48e',
            'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
            'allocation_pools': [{'start': '192.168.1.2',
                                  'end': '192.168.1.254'}],
            'gateway_ip': '192.168.1.1',
            'ip_version': 4,
            'cidr': '192.168.1.0/24',
            'id': 'a6b73736-6d87-4e5a-9afd-ec40a1e8c4c9',
            'enable_dhcp': True
        }]},
        {'subnets': [{
            'name': 'boo6',
            'network_id': 'f7271ca7-3dd8-4a5e-8615-1b8a8a2bf48e',
            'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
            'allocation_pools': [{'start': 'fe80::f816:3eff:fe20:57c4',
                                  'end': 'fe80::ffff:ffff:ffff:ffff'}],
            'gateway_ip': 'fe80::f816:3eff:fe20:57c3',
            'ip_version': 6,
            'cidr': 'fe80::/64',
            'id': '639771be-9436-4011-8a90-8dcf252bee24',
            'enable_dhcp': True
        }, {
            'name': 'boourns6',
            'network_id': 'f7271ca7-3dd8-4a5e-8615-1b8a8a2bf48e',
            'tenant_id': 'c1210485b2424d48804aad5d39c61b8f',
            'allocation_pools': [{'start': 'fe80::f816:3eff:fe20:57c4',
                                  'end': 'fe80::ffff:ffff:ffff:ffff'}],
            'gateway_ip': 'fe80::f816:3eff:fe20:57c3',
            'ip_version': 6,
            'cidr': 'fe80::/64',
            'id': '6565eb44-8267-4170-b892-95d59346c5d2',
            'enable_dhcp': True
        }]})
    def test__get_subnets_by_attrs_unique_exc(self, response):
        net_id = response['subnets'][0]['network_id']

        self.mox.StubOutWithMock(controllers.app.neutron, 'list_subnets')
        controllers.app.neutron.list_subnets(
            network_id=net_id).AndReturn(response)
        self.mox.ReplayAll()

        self.assertRaises(
            controllers.exceptions.DuplicatedResourceException,
            lambda: controllers._get_subnets_by_attrs(
                unique=True, network_id=net_id))

    @ddt.data({'networks': [
        {'admin_state_up': True,
         'id': '3a06dfc7-d239-4aad-9a57-21cd171c72e5',
         'name': 'network_1',
         'shared': False,
         'status': 'ACTIVE',
         'subnets': [],
         'tenant_id': 'c1210485b2424d48804aad5d39c61b8f'},
        {'admin_state_up': True,
         'id': '7db8c5a4-6eb0-478d-856b-7cfda2b25e13',
         'name': 'network-2',
         'shared': False,
         'status': 'ACTIVE',
         'subnets': [],
         'tenant_id': 'c1210485b2424d48804aad5d39c61b8f'},
        {'admin_state_up': True,
         'id': 'afc75773-640e-403c-9fff-62ba98db1f19',
         'name': 'network_3',
         'shared': True,
         'status': 'ACTIVE',
         'subnets': ['e12f0c45-46e3-446a-b207-9474b27687a6'],
         'tenant_id': 'ed680f49ff714162ab3612d7876ffce5'}]})
    def test__get_networks_by_attrs_unique_exc(self, response):
        self.mox.StubOutWithMock(controllers.app.neutron, 'list_networks')
        controllers.app.neutron.list_networks(status='ACTIVE').AndReturn(
            response)
        self.mox.ReplayAll()

        self.assertRaises(
            controllers.exceptions.DuplicatedResourceException,
            lambda: controllers._get_networks_by_attrs(unique=True,
                                                       status='ACTIVE'))
