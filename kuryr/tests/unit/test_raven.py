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
import os
import signal

import ddt
from oslo_service import service

from kuryr.common import config
from kuryr.raven import raven
from kuryr.tests.unit import base


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

    def test__ensure_networking_base_not_set(self):
        """Check that it creates net/subnet when none are reported"""
        r = raven.Raven()

        self.mox.StubOutWithMock(raven.controllers, '_get_networks_by_attrs')
        self.mox.StubOutWithMock(raven.controllers, '_get_subnets_by_attrs')
        self.mox.StubOutWithMock(r.neutron, 'create_network')
        self.mox.StubOutWithMock(r.neutron, 'create_subnet')

        raven.controllers._get_networks_by_attrs(
            unique=False, name=raven.HARDCODED_NET_NAME).AndReturn([])
        raven.controllers._get_subnets_by_attrs(
            unique=False, cidr=raven.HARDCODED_CIDR).AndReturn([])

        net_id = '73b7056d-ff6a-450c-9d1b-da222b910330'
        subnet_id = '6245fe1e-8ed2-4f51-8ea9-e78e410bef3b'
        tenant_id = '511b9871-66df-448c-bea1-de85c95e3289'
        r.neutron.create_network(
            {'network': {'name': raven.HARDCODED_NET_NAME}}).AndReturn(
                {'network': {
                    'name': raven.HARDCODED_NET_NAME,
                    'subnets': [],
                    'admin_state_up': False,
                    'shared': False,
                    'status': 'ACTIVE',
                    'tenant_id': tenant_id,
                    'id': net_id}})
        r.neutron.create_subnet(
            {'subnet': {
                'name': '{0}-{1}'.format(raven.HARDCODED_NET_NAME,
                                         raven.HARDCODED_CIDR),
                'network_id': net_id,
                'ip_version': 4,
                'cidr': raven.HARDCODED_CIDR,
                'enable_dhcp': False}}).AndReturn(
                    {'subnet': {
                        'name': '{0}-{1}'.format(raven.HARDCODED_NET_NAME,
                                         raven.HARDCODED_CIDR),
                        'network_id': net_id,
                        'tenant_id': tenant_id,
                        'cidr': raven.HARDCODED_CIDR,
                        'id': subnet_id,
                        'enable_dhcp': True}})

        self.mox.ReplayAll()
        r._ensure_networking_base()

    def test__ensure_networking_base_noop(self):
        """Check that it creates net/subnet when nothing needs to be done"""
        r = raven.Raven()

        self.mox.StubOutWithMock(raven.controllers, '_get_networks_by_attrs')
        self.mox.StubOutWithMock(raven.controllers, '_get_subnets_by_attrs')
        self.mox.StubOutWithMock(r.neutron, 'create_network')
        self.mox.StubOutWithMock(r.neutron, 'create_subnet')

        net_id = '73b7056d-ff6a-450c-9d1b-da222b910330'
        subnet_id = '6245fe1e-8ed2-4f51-8ea9-e78e410bef3b'
        tenant_id = '511b9871-66df-448c-bea1-de85c95e3289'

        raven.controllers._get_networks_by_attrs(
            unique=False, name=raven.HARDCODED_NET_NAME).AndReturn([{
                'status': 'ACTIVE',
                'subnets': [subnet_id],
                'name': raven.HARDCODED_NET_NAME,
                'admin_state_up': True,
                'tenant_id': tenant_id,
                'id': net_id,
                'shared': False}])
        raven.controllers._get_subnets_by_attrs(
            unique=False, cidr=raven.HARDCODED_CIDR).AndReturn([{
                        'name': '{0}-{1}'.format(raven.HARDCODED_NET_NAME,
                                         raven.HARDCODED_CIDR),
                        'network_id': net_id,
                        'tenant_id': tenant_id,
                        'cidr': raven.HARDCODED_CIDR,
                        'id': subnet_id,
                        'enable_dhcp': True}])

        self.mox.ReplayAll()
        r._ensure_networking_base()
