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
import ddt
import netaddr

from oslo_serialization import jsonutils

from kuryr.cni import constants as cni_const
from kuryr.cni import driver
from kuryr.common import config
from kuryr.common import constants
from kuryr.raven import raven
from kuryr.tests.unit import base


@ddt.ddt
class TestCNIHelpers(base.TestKuryrBase):
    """Tests the helper methods in the Kuryr CNI driver"""
    basic_env = {
        cni_const.ARGS: 'FOO=BAR',
        cni_const.PATH: '/usr/bin/kuryr_cni',
        cni_const.CONTAINERID: '7ed0919e-c835-4e1b-b788-cc952ba95ff1',
        cni_const.NETNS: '/proc/11/ns/net',
        cni_const.COMMAND: 'ADD',
        cni_const.IFNAME: 'eth0'}

    @ddt.data(
        {},
        {'CNI_PATH': '/usr/bin/kuryr_cni',
         'CNI_CONTAINERID': '7ed0919e-c835-4e1b-b788-cc952ba95ff1',
         'CNI_NETNS': '/proc/11/ns/net',
         'CNI_IFNAME': 'eth0'})
    def test__check_vars_exc(self, env):
        self.mox.StubOutWithMock(driver.os.environ, 'copy')
        driver.os.environ.copy().AndReturn(env)
        self.mox.ReplayAll()

        self.assertRaises(driver.exceptions.KuryrException,
                          driver.KuryrCNIDriver)

    @ddt.data(
        ('FOO=A;BAR=B;BELL=BAR',
         {'BAR': 'B', 'BELL': 'BAR', 'FOO': 'A'}),
        ('',
         {}),
        (';',
         {}),
        ('BOO=URNS',
         {'BOO': 'URNS'}))
    @ddt.unpack
    def test__parse_cni_args_as_dict(self, data, expected):
        self.mox.StubOutWithMock(driver.os.environ, 'copy')
        driver.os.environ.copy().AndReturn(self.basic_env)
        self.mox.ReplayAll()

        dri = driver.KuryrCNIDriver()
        self.assertEqual(dri._parse_cni_args_as_dict(data), expected)


@ddt.ddt
class TestNeutronCNIDriver(base.TestKuryrBase):
    basic_env = {
        cni_const.ARGS: (
            'K8S_POD_NAMESPACE=default;'
            'K8S_POD_NAME=nginx-app-722l8;'
            'K8S_POD_INFRA_CONTAINER_ID=8ceb00926acf251b34d70065a6158370953ab9'
            '09b0745f5f4647ee6b9ec5c250;'),
        cni_const.PATH: '/usr/bin/kuryr_cni',
        cni_const.CONTAINERID: '7ed0919e-c835-4e1b-b788-cc952ba95ff1',
        cni_const.NETNS: '/proc/11/ns/net',
        cni_const.COMMAND: 'ADD',
        cni_const.IFNAME: 'eth0'}

    class TestKuryrCNIK8sNeutronDriver(driver.KuryrCNIK8sNeutronDriver):
        def __init__(self, env, path, container_id, netns, ifname, command,
                     cni_args, pod_namespace, pod_name, pod_container_id):
            self.env = env
            self.path = path
            self.container_id = container_id
            self.netns = netns
            self.ifname = ifname
            self.command = command
            self.cni_args = cni_args
            self.pod_namespace = pod_namespace
            self.pod_name = pod_name
            self.pod_container_id = pod_container_id

    def test_add(self):
        """Tests the isolated CNI add functionality

        It relies on a subclassing of the KuryrCNIK8sNeutronDriver to unit test
        only the add functionality and avoid the __init__ verifications that
        are done by KuryrCNIK8sNeutronDriver and KuryrCNIDriver
        """
        net_id = '44a51c51-3e2a-4e81-805f-ba8abef15ec5'
        subnet_id = '7b392f0b-ab76-481a-956d-bfeaae2a8e42'
        tenant_id = '39dd23d1-7d7c-4586-a105-bc6f84f9a769'
        port_id = '7a12ebf0-ed19-4819-94cd-150acf9f5c1f'

        net = netaddr.IPNetwork(config.CONF.k8s.cluster_subnet)
        port_ip = str(netaddr.IPAddress(net.first + 11))
        gateway_ip = config.CONF.k8s.cluster_gateway_ip

        port = {
            'admin_state_up': True,
            'device_id': '34640abf-cf2a-48eb-afb8-c30f99a97056',
            'device_owner': constants.DEVICE_OWNER,
            'fixed_ips': [{
                'ip_address': port_ip,
                'subnet_id': subnet_id}],
            'id': port_id,
            'mac_address': '00:11:22:33:44:55',
            'name': 'test_port',
            'network_id': net_id,
            'status': 'ACTIVE',
            'tenant_id': tenant_id}

        subnets = {
            'name': raven.HARDCODED_NET_NAME + '-' + str(net),
            'network_id': net_id,
            'tenant_id': tenant_id,
            'allocation_pools': [{
                'start': str(netaddr.IPAddress(net.first + 2)),
                'end': str(netaddr.IPAddress(net.last - 1))}],
            'gateway_ip': gateway_ip,
            'ip_version': 4,
            'cidr': str(net),
            'id': subnet_id,
            'enable_dhcp': False}

        neutron_driver = self.TestKuryrCNIK8sNeutronDriver(
            self.basic_env,
            self.basic_env[cni_const.PATH],
            self.basic_env[cni_const.CONTAINERID],
            self.basic_env[cni_const.NETNS],
            self.basic_env[cni_const.IFNAME],
            self.basic_env[cni_const.COMMAND],
            self.basic_env[cni_const.ARGS],
            pod_namespace='default',
            pod_name='ngingx-app-722l8',
            pod_container_id=('8ceb00926acf251b34d70065a6158370953ab909b0745f5'
                              'f4647ee6b9ec5c250'))

        self.mox.StubOutWithMock(neutron_driver, '_get_pod_annotaions')

        neutron_driver._get_pod_annotaions().AndReturn({
            constants.K8S_ANNOTATION_PORT_KEY: jsonutils.dumps(port),
            constants.K8S_ANNOTATION_SUBNET_KEY: jsonutils.dumps(subnets)})

        self.mox.StubOutWithMock(driver.binding, 'port_bind')
        ifname = self.basic_env[cni_const.IFNAME]
        driver.binding.port_bind(
            self.basic_env[cni_const.CONTAINERID], port, subnets,
            ifname=ifname, netns=self.basic_env[cni_const.NETNS],
            default_gateway=gateway_ip).AndReturn(
                (ifname, 'peer42', ('', '')))

        self.mox.ReplayAll()

        self.assertEqual(
            jsonutils.dumps({
                'cniVersion': '0.1.0',
                'ip4': {
                    'ip': '{0}/{1}'.format(port_ip, net.prefixlen),
                    'gateway': gateway_ip
                },
                'dns': {}}),
            neutron_driver.add())

    def test_delete(self):
        pass
