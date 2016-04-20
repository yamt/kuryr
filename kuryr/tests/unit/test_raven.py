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
import asyncio
import collections
import copy
import itertools
import os
import signal
import uuid

import ddt
from oslo_service import service

from kuryr.common import config
from kuryr.raven import raven
from kuryr.tests.unit import base
from kuryr import utils


SLEEP_TIME_IN_SEC = 0.5


@asyncio.coroutine
def _noop(self, endpoint, callback):
    yield from asyncio.sleep(SLEEP_TIME_IN_SEC, loop=self._event_loop)


@asyncio.coroutine
def _spin(self, endpoint, callback):
    while True:
        try:
            yield from asyncio.sleep(SLEEP_TIME_IN_SEC, loop=self._event_loop)
        except asyncio.CancelledError:
            break


@asyncio.coroutine
def _kill(pid, sig, loop):
    yield from asyncio.sleep(SLEEP_TIME_IN_SEC, loop=loop)
    os.kill(pid, sig)


@asyncio.coroutine
def _simplified_watch(self, endpoint, callback):
    yield from asyncio.sleep(2 * SLEEP_TIME_IN_SEC, loop=self._event_loop)
    fake_deserialized_json = {"type": "ADDED", "object": {}}
    callback(fake_deserialized_json)


def _inject_watch(raven, alternative_watch):
    raven.watch = alternative_watch.__get__(raven, raven.__class__)


class _FakeResponse(object):
    def __init__(self, content):
        self._content = content

    @asyncio.coroutine
    def read_line(self):
        if self._content:
            return self._content.popleft()
        else:
            return None

    @asyncio.coroutine
    def read_headers(self):
        return 200, 'OK', {raven.headers.TRANSFER_ENCODING: 'chunked'}


@asyncio.coroutine
def _fake_get_response(responses):
    return _FakeResponse(responses)


@ddt.ddt
class TestRaven(base.TestKuryrBase):
    """The unit tests for Raven service.

    This test validates if Raven works as the service as it's intended.
    """
    def test_wait(self):
        """Checks if the service stops correctly with the noop watch."""
        r = raven.Raven()
        self.mox.StubOutWithMock(r, '_ensure_networking_base')
        r._ensure_networking_base()

        self.mox.ReplayAll()
        _inject_watch(r, _noop)
        self.assertFalse(r._event_loop.is_closed())
        launch = service.launch(config.CONF, r)
        launch.wait()
        self.assertTrue(r._event_loop.is_closed())

    @ddt.data(signal.SIGINT, signal.SIGTERM)
    def test_signals(self, sig):
        """Checks if the service stops when it received SIGINT and SIGTERM."""
        r = raven.Raven()
        self.mox.StubOutWithMock(r, '_ensure_networking_base')
        r._ensure_networking_base()

        self.mox.ReplayAll()
        _inject_watch(r, _spin)
        self.assertFalse(r._event_loop.is_closed())
        launcher = service.launch(config.CONF, r)
        pid = os.getpid()
        r._event_loop.create_task(_kill(pid, sig, r._event_loop))
        launcher.wait()
        self.assertTrue(r._event_loop.is_closed())

    def test_simplified_watch(self):
        """Checks if Raven works if the watch method just returns JSON data."""
        r = raven.Raven()
        self.mox.StubOutWithMock(r, '_ensure_networking_base')
        r._ensure_networking_base()

        self.mox.ReplayAll()
        _inject_watch(r, _simplified_watch)
        self.assertFalse(r._event_loop.is_closed())
        launcher = service.launch(config.CONF, r)
        launcher.wait()
        self.assertTrue(r._event_loop.is_closed())

    @ddt.data(asyncio.coroutine,  # Coroutine
              lambda x: x)  # Non-coroutine
    def test_watch_cb(self, wrapper):
        """Checks if Raven can asynchronously execute callbacks

        Since mox does not support coroutines, for testing when the callback
        is a coroutine, we make a real coroutine out of `_callback` with the
        wrapper. `_callback` then calls a simple method called
        `response_checker` and we prepare the replay with it.
        """
        endpoint = 'test_endpoint'

        watcher_callback = self.mox.CreateMockAnything()
        response_checker = self.mox.CreateMockAnything()

        def _callback(content):
            response_checker(content)

        callback = wrapper(_callback)

        responses = collections.deque((
            {'foo': 'bar'},
            {1: '1', 2: '2'},
            {'kind': 'Pod', 'metadata': {}}))

        r = raven.Raven()
        r._reconnect = False
        r.WATCH_ENDPOINTS_AND_CALLBACKS = {
            endpoint: watcher_callback
        }

        self.mox.StubOutWithMock(r, '_ensure_networking_base')
        r._ensure_networking_base()

        self.mox.StubOutWithMock(raven.methods, 'get')
        raven.methods.get(endpoint=endpoint, loop=r._event_loop,
                          decoder=utils.utf8_json_decoder).AndReturn(
            _fake_get_response(responses))

        watcher_callback.__get__(r, r.__class__).AndReturn(callback)

        for response in responses:
            response_checker(response)

        self.mox.ReplayAll()
        launcher = service.launch(config.CONF, r)
        launcher.wait()
        self.mox.VerifyAll()

    def test__ensure_networking_base_not_set(self):
        """Check that it creates net/subnet when none are reported"""
        r = raven.Raven()

        self.mox.StubOutWithMock(raven.controllers,
                                 '_get_security_groups_by_attrs')
        self.mox.StubOutWithMock(raven.controllers, '_get_networks_by_attrs')
        self.mox.StubOutWithMock(raven.controllers, '_get_subnets_by_attrs')
        self.mox.StubOutWithMock(r.neutron, 'create_security_group')
        self.mox.StubOutWithMock(r.neutron, 'create_security_group_rule')
        self.mox.StubOutWithMock(raven.controllers, '_get_routers_by_attrs')
        self.mox.StubOutWithMock(raven.controllers, '_get_ports_by_attrs')
        self.mox.StubOutWithMock(r.neutron, 'create_network')
        self.mox.StubOutWithMock(r.neutron, 'create_subnet')
        self.mox.StubOutWithMock(r.neutron, 'create_router')
        self.mox.StubOutWithMock(r.neutron, 'add_interface_router')

        subnet_cidr = config.CONF.k8s.cluster_subnet
        service_subnet_cidr = config.CONF.k8s.cluster_service_subnet
        raven.controllers._get_security_groups_by_attrs(
            unique=False, name=raven.HARDCODED_SG_NAME).AndReturn([])
        raven.controllers._get_networks_by_attrs(
            unique=False, name=raven.HARDCODED_NET_NAME).AndReturn([])
        raven.controllers._get_networks_by_attrs(
            unique=False,
            name=raven.HARDCODED_NET_NAME + '-service').AndReturn([])
        raven.controllers._get_routers_by_attrs(
            unique=False,
            name=raven.HARDCODED_NET_NAME + '-router').AndReturn([])

        router_id = str(uuid.uuid4())
        cluster_network_id = str(uuid.uuid4())
        service_network_id = str(uuid.uuid4())
        cluster_subnet_id = str(uuid.uuid4())
        service_subnet_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())

        raven.controllers._get_subnets_by_attrs(
            unique=False, cidr=subnet_cidr,
            network_id=cluster_network_id).AndReturn([])
        raven.controllers._get_subnets_by_attrs(
            unique=False, cidr=service_subnet_cidr,
            network_id=service_network_id).AndReturn([])

        raven.controllers._get_ports_by_attrs(
            unique=False, device_owner='network:router_interface',
            device_id=router_id, network_id=cluster_network_id).AndReturn([])
        raven.controllers._get_ports_by_attrs(
            unique=False, device_owner='network:router_interface',
            device_id=router_id, network_id=service_network_id).AndReturn([])

        router_name = raven.HARDCODED_NET_NAME + '-router'
        fake_router_request = {
            'router': {
                'name': router_name,
            },
        }
        fake_router_response = copy.deepcopy(fake_router_request)
        fake_router_response['router']['id'] = router_id
        r.neutron.create_router(
            fake_router_request).AndReturn(fake_router_response)

        sg_id = str(uuid.uuid4())
        r.neutron.create_security_group(
            {'security_group': {'name': raven.HARDCODED_SG_NAME}}).AndReturn(
            {'security_group': {'id': sg_id}})
        for ethertype in ['IPv4', 'IPv6']:
            r.neutron.create_security_group_rule(
                {'security_group_rule': {
                    'security_group_id': sg_id,
                    'direction': 'ingress',
                    'remote_group_id': sg_id,
                    'ethertype': ethertype}}) \
                .AndReturn({})

        fake_cluster_network_response = {
            'network': {
                'name': raven.HARDCODED_NET_NAME,
                'subnets': [],
                'admin_state_up': False,
                'shared': False,
                'status': 'ACTIVE',
                'tenant_id': tenant_id,
                'id': cluster_network_id,
            },
        }
        r.neutron.create_network(
            {'network': {'name': raven.HARDCODED_NET_NAME}}).AndReturn(
                fake_cluster_network_response)

        fake_service_network_response = copy.deepcopy(
            fake_cluster_network_response)
        fake_service_network_response['network']['name'] += '-service'
        fake_service_network_response['network']['id'] = service_network_id
        service_network_name = raven.HARDCODED_NET_NAME + '-service'
        r.neutron.create_network(
            {'network': {'name': service_network_name}}).AndReturn(
            fake_service_network_response)
        new_cluster_subnet = {
            'subnet': {
                'name': '{0}-{1}'.format(raven.HARDCODED_NET_NAME,
                                         subnet_cidr),
                'network_id': cluster_network_id,
                'ip_version': 4,
                'gateway_ip': config.CONF.k8s.cluster_gateway_ip,
                'cidr': subnet_cidr,
                'enable_dhcp': False,
            },
        }
        fake_cluster_subnet_response = copy.deepcopy(new_cluster_subnet)
        fake_cluster_subnet_response['subnet']['id'] = cluster_subnet_id
        r.neutron.create_subnet(new_cluster_subnet).AndReturn(
            fake_cluster_subnet_response)
        new_service_subnet = {
            'subnet': {
                'name': '-'.join([raven.HARDCODED_NET_NAME,
                                  service_subnet_cidr]),
                'network_id': service_network_id,
                'ip_version': 4,
                'cidr': service_subnet_cidr,
                'enable_dhcp': False
            },
        }
        fake_service_subnet_response = copy.deepcopy(new_service_subnet)
        fake_service_subnet_response['subnet']['id'] = service_subnet_id
        r.neutron.create_subnet(new_service_subnet).AndReturn(
            fake_service_subnet_response)

        r.neutron.add_interface_router(
            router_id, {'subnet_id': cluster_subnet_id}).AndReturn(None)
        r.neutron.add_interface_router(
            router_id, {'subnet_id': service_subnet_id}).AndReturn(None)

        self.mox.ReplayAll()
        r._ensure_networking_base()

    def test_watch_reconnect(self):
        """Checks if Raven can reconnect to an endpoint when it gets EOF

        Since mox does not support coroutines, for testing when the callback
        is a coroutine, we make a real coroutine out of `_callback` with the
        wrapper. `_callback` then calls a simple method called
        `response_checker` and we prepare the replay with it.
        """
        endpoint = 'test_endpoint'

        watcher_callback = self.mox.CreateMockAnything()
        response_checker = self.mox.CreateMockAnything()

        first_responses = collections.deque(
            ({'foo': 'bar'},
             {1: '1', 2: '2'},
             {'kind': 'Pod', 'metadata': {}}))

        final_responses = collections.deque(
            ({'foo': 'barbarian'},
             {1: '1', 2: '2', 'stop_reconnecting': True},
             {'kind': 'service', 'metadata': {}}))

        r = raven.Raven()
        r._reconnect = True
        r.WATCH_ENDPOINTS_AND_CALLBACKS = {
            endpoint: watcher_callback
        }

        @asyncio.coroutine
        def callback(content):
            response_checker(content)
            if content.get('stop_reconnecting'):
                r._reconnect = False

        self.mox.StubOutWithMock(r, '_ensure_networking_base')
        r._ensure_networking_base()

        self.mox.StubOutWithMock(raven.methods, 'get')
        raven.methods.get(endpoint=endpoint, loop=r._event_loop,
                          decoder=utils.utf8_json_decoder).AndReturn(
            _fake_get_response(first_responses))

        # We'll reconnect once
        raven.methods.get(endpoint=endpoint, loop=r._event_loop,
                          decoder=utils.utf8_json_decoder).AndReturn(
            _fake_get_response(final_responses))

        watcher_callback.__get__(r, r.__class__).AndReturn(callback)

        for response in itertools.chain(first_responses, final_responses):
            response_checker(response)

        self.mox.ReplayAll()
        launcher = service.launch(config.CONF, r)
        launcher.wait()
        self.mox.VerifyAll()

    def test_watch_ignore_repeated_events(self):
        """Checks that Raven does not use the callback with repeated events

        Since mox does not support coroutines, for testing when the callback
        is a coroutine, we make a real coroutine out of `_callback` with the
        wrapper. `_callback` then calls a simple method called
        `response_checker` and we prepare the replay with it.

        In this case, we check that when the second response is sending already
        seen events, we ignore them when deciding to execute the callback.
        """
        endpoint = 'test_endpoint'

        watcher_callback = self.mox.CreateMockAnything()
        response_checker = self.mox.CreateMockAnything()

        first_responses = collections.deque(
            ({'foo': 'bar'},
             {1: '1', 2: '2'},
             {'kind': 'Pod', 'metadata': {}}))

        final_responses = collections.deque(
            ({1: '1', 2: '2'},  # Repeated
             {'kind': 'Pod', 'metadata': {}},  # Repeated
             {'foo': 'barbarian'},
             {1: '1', 2: '2', 'stop_reconnecting': True},
             {'kind': 'service', 'metadata': {}}))

        r = raven.Raven()
        r._reconnect = True
        r.WATCH_ENDPOINTS_AND_CALLBACKS = {
            endpoint: watcher_callback
        }

        @asyncio.coroutine
        def callback(content):
            response_checker(content)
            if content.get('stop_reconnecting'):
                r._reconnect = False

        self.mox.StubOutWithMock(r, '_ensure_networking_base')
        r._ensure_networking_base()

        self.mox.StubOutWithMock(raven.methods, 'get')
        raven.methods.get(endpoint=endpoint, loop=r._event_loop,
                          decoder=utils.utf8_json_decoder).AndReturn(
            _fake_get_response(first_responses))

        # We'll reconnect once
        raven.methods.get(endpoint=endpoint, loop=r._event_loop,
                          decoder=utils.utf8_json_decoder).AndReturn(
            _fake_get_response(final_responses))

        watcher_callback.__get__(r, r.__class__).AndReturn(callback)

        processed = set()
        for response in itertools.chain(first_responses, final_responses):
            textual_response = str(response)
            if textual_response not in processed:
                processed.add(textual_response)
                response_checker(response)

        self.mox.ReplayAll()
        launcher = service.launch(config.CONF, r)
        launcher.wait()
        self.mox.VerifyAll()

    def test__ensure_networking_base_noop(self):
        """Check that it creates net/subnet when nothing needs to be done"""
        r = raven.Raven()

        self.mox.StubOutWithMock(raven.controllers,
                                 '_get_security_groups_by_attrs')
        self.mox.StubOutWithMock(raven.controllers, '_get_networks_by_attrs')
        self.mox.StubOutWithMock(raven.controllers, '_get_subnets_by_attrs')
        self.mox.StubOutWithMock(raven.controllers, '_get_routers_by_attrs')
        self.mox.StubOutWithMock(raven.controllers, '_get_ports_by_attrs')

        cluster_network_id = str(uuid.uuid4())
        service_network_id = str(uuid.uuid4())
        router_id = str(uuid.uuid4())
        cluster_subnet_id = str(uuid.uuid4())
        service_subnet_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())
        port_id = str(uuid.uuid4())

        router_name = raven.HARDCODED_NET_NAME + '-router'
        fake_router = {
            'id': router_id,
            'name': router_name,
        }
        raven.controllers._get_routers_by_attrs(
            unique=False,
            name=raven.HARDCODED_NET_NAME + '-router').AndReturn([fake_router])

        fake_cluster_network = {
            'name': raven.HARDCODED_NET_NAME,
            'subnets': [],
            'admin_state_up': False,
            'shared': False,
            'status': 'ACTIVE',
            'tenant_id': tenant_id,
            'id': cluster_network_id,
        }
        raven.controllers._get_networks_by_attrs(
            unique=False, name=raven.HARDCODED_NET_NAME).AndReturn(
            [fake_cluster_network])

        fake_service_network = copy.deepcopy(fake_cluster_network)
        fake_service_network['name'] += '-service'
        fake_service_network['id'] = service_network_id
        raven.controllers._get_networks_by_attrs(
            unique=False,
            name=raven.HARDCODED_NET_NAME + '-service').AndReturn(
            [fake_service_network])

        sg_id = str(uuid.uuid4())
        raven.controllers._get_security_groups_by_attrs(
            unique=False, name=raven.HARDCODED_SG_NAME).AndReturn([{
                'id': sg_id,
                'name': raven.HARDCODED_SG_NAME}])

        cluster_subnet_cidr = config.CONF.k8s.cluster_subnet
        service_subnet_cidr = config.CONF.k8s.cluster_service_subnet

        fake_cluster_subnet = {
            'name': '{0}-{1}'.format(raven.HARDCODED_NET_NAME,
                                     cluster_subnet_cidr),
            'network_id': cluster_network_id,
            'tenant_id': tenant_id,
            'cidr': cluster_subnet_cidr,
            'id': cluster_subnet_id,
            'enable_dhcp': True,
        }
        raven.controllers._get_subnets_by_attrs(
            unique=False, cidr=cluster_subnet_cidr,
            network_id=cluster_network_id).AndReturn(
            [fake_cluster_subnet])

        fake_service_subnet = {
            'name': '-'.join([raven.HARDCODED_NET_NAME, service_subnet_cidr]),
            'network_id': service_network_id,
            'ip_version': 4,
            'cidr': service_subnet_cidr,
            'id': service_subnet_id,
            'enable_dhcp': False,
        }
        raven.controllers._get_subnets_by_attrs(
            unique=False, cidr=service_subnet_cidr,
            network_id=service_network_id).AndReturn([fake_service_subnet])

        fake_cluster_port = {
            "network_id": cluster_network_id,
            "tenant_id": tenant_id,
            "device_owner": "network:router_interface",
            "mac_address": "fa:16:3e:20:57:c3",
            "fixed_ips": [{
                'subnet_id': cluster_subnet_id,
                'ip_address': '192.168.1.42',
            }],
            "id": port_id,
            "device_id": router_id,
        }
        raven.controllers._get_ports_by_attrs(
            unique=False, device_owner='network:router_interface',
            device_id=router_id, network_id=cluster_network_id).AndReturn(
            [fake_cluster_port])

        fake_service_port = copy.deepcopy(fake_cluster_port)
        fake_service_port['fixed_ips'][0]['subnet_id'] = service_subnet_id
        fake_service_port['network_id'] = service_network_id
        raven.controllers._get_ports_by_attrs(
            unique=False, device_owner='network:router_interface',
            device_id=router_id, network_id=service_network_id).AndReturn(
            [fake_service_port])

        self.mox.ReplayAll()
        r._ensure_networking_base()
