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

import abc
import asyncio
import copy
import uuid

import ddt
from mox3 import mox
from oslo_serialization import jsonutils
import requests
import six

from kuryr.common import config
from kuryr.common import constants
from kuryr.raven import raven
from kuryr.raven import watchers
from kuryr.tests.unit import base


class TestK8sAPIWatchers(base.TestKuryrBase):
    """The unit tests for K8sAPIWatcher interface.

    This test checks if k8sApiWatcher works as it's intended. In this class,
    subclasses of K8sAPIWatcher are instantiated but they will not be
    instantiated in the real use cases. These instantiations are considered
    as a sort of the type checking.
    """
    def test_k8s_api_watcher(self):
        """A  watcher implemented K8sAPIWatcher can be instantiated."""
        class SomeWatcher(watchers.K8sAPIWatcher):
            WATCH_ENDPOINT = '/'

            def translate(self, deserialized_json):
                pass
        SomeWatcher()

    def test_k8s_api_watcher_watch_endpoind(self):
        """A watcher without ``WATCH_ENDPOINT`` can't be instantiated."""
        class SomeWatcherWithoutWatchEndpoint(watchers.K8sAPIWatcher):
            def translate(self, deserialized_json):
                pass
        self.assertRaises(TypeError, SomeWatcherWithoutWatchEndpoint)

    def test_k8s_api_watcher_translate(self):
        """A watcher without ``translate`` can't be instantiated."""
        class SomeWatcherWithoutTranslate(watchers.K8sAPIWatcher):
            WATCH_ENDPOINT = '/'
        self.assertRaises(TypeError, SomeWatcherWithoutTranslate)


@ddt.ddt
class TestWatchers(base.TestKuryrBase):
    """The unit tests for the watchers.

    This tests checks the watchers conform to the requirements, register
    appropriately. In this class, the watchers are instantiated but they
    will not be instantiated in the real use cases. These instantiations
    are considered as a sort of the type checking.
    """
    @ddt.data(watchers.K8sPodsWatcher, watchers.K8sServicesWatcher)
    def test_watchers(self, Watcher):
        """Every watcher has ``WATCH_ENDPOINT`` and ``translate``."""
        self.assertIsNotNone(Watcher.WATCH_ENDPOINT)
        self.assertTrue(callable(Watcher.translate))
        Watcher()

    def test_register_watchers(self):
        """``register_watchers`` injects ``WATCH_ENDPOINT`` and ``translate``.

        ``register_watchers`` should inject ``WATCH_ENDPOINT`` attribute (or
        property) and ``translate`` method of the given class into the class
        which is the target of it.
        """
        class DoNothingWatcher(object):
            WATCH_ENDPOINT = '/watch_me'

            def translate(self, deserialized_json):
                pass
        DoNothingWatcher()

        @raven.register_watchers(DoNothingWatcher)
        class Foo(object):
            pass
        Foo()

        self.assertIsNotNone(Foo.WATCH_ENDPOINTS_AND_CALLBACKS)
        self.assertEqual(1, len(Foo.WATCH_ENDPOINTS_AND_CALLBACKS))
        self.assertEqual(DoNothingWatcher.translate,
                         Foo.WATCH_ENDPOINTS_AND_CALLBACKS[
                             DoNothingWatcher.WATCH_ENDPOINT])


class _FakeRaven(raven.Raven):
    def _ensure_networking_base(self):
        self._default_sg = str(uuid.uuid4())
        self._network = {
            'id': str(uuid.uuid4()),
            'name': raven.HARDCODED_NET_NAME,
        }
        subnet_cidr = config.CONF.k8s.cluster_subnet
        fake_subnet = base.TestKuryrBase._get_fake_v4_subnet(
            self._network['id'],
            name=raven.HARDCODED_NET_NAME + '-' + subnet_cidr,
            subnet_v4_id=uuid.uuid4())
        self._subnet = fake_subnet['subnet']

        self._service_network = {
            'id': str(uuid.uuid4()),
            'name': raven.HARDCODED_NET_NAME + '-service'
        }
        service_subnet_cidr = config.CONF.k8s.cluster_service_subnet
        fake_service_subnet = base.TestKuryrBase._get_fake_v4_subnet(
            self._network['id'],
            name=raven.HARDCODED_NET_NAME + '-' + service_subnet_cidr,
            subnet_v4_id=uuid.uuid4())
        self._service_subnet = fake_service_subnet['subnet']

        self._router = {
            "router": {
                "status": "ACTIVE",
                "name": "fake_router",
                "admin_state_up": True,
                "tenant_id": str(uuid.uuid4()),
                "distributed": False,
                "routes": [],
                "ha": False,
                "id": str(uuid.uuid4()),
            },
        }


class _FakeSuccessResponse(object):
    status_code = 200
    content = ""


@six.add_metaclass(abc.ABCMeta)
class TestK8sWatchersBase(base.TestKuryrBase):
    """The base class for the unit tests of the K8s watcher classes.

    This class has the common fake data and utility methods for each watcher
    test.
    """
    fake_pod_object = {
        "kind": "Pod",
        "apiVersion": "v1",
        "metadata": {
            "name": "frontend-qr8d6",
            "generateName": "frontend-",
            "namespace": "default",
            "selfLink": "/api/v1/namespaces/default/pods/frontend-qr8d6",  # noqa
            "uid": "8e174673-e03f-11e5-8c79-42010af00003",
            "resourceVersion": "107227",
            "creationTimestamp": "2016-03-02T06:25:27Z",
            "labels": {
                "app": "guestbook",
                "tier": "frontend",
            },
            "annotations": {
                "kubernetes.io/created-by": {
                    "kind": "SerializedReference",
                    "apiVersion": "v1",
                    "reference": {
                        "kind": "ReplicationController",
                        "namespace": "default",
                        "name": "frontend",
                        "uid": "8e1657d9-e03f-11e5-8c79-42010af00003",
                        "apiVersion": "v1",
                        "resourceVersion": "107226",
                    },
                },
            },
        },
    }

    @abc.abstractproperty
    def TEST_WATCHER(self):
        """The watcher class to be tested.

        This is defined as the abstract property and the sub classes derived
        from this class MUST define this class attribute. This class is used
        ``setUp`` method to instantiate the fake Raven instance.
        """

    def setUp(self):
        """Sets up the fake Raven instance registering WATCHER to it.

        This method instantiates the Raven isntance with the watcher class for
        the test registered, holds the translate method of the watcher binding
        it to the fake Raven instance and sets up the cleanup processes. The
        fake Raven instance and the translate method of the watcher class
        specified in ``TEST_WATCHER`` are accessible by ``self.fake_raven``
        and ``self.translate`` for each other.
        """
        super(TestK8sWatchersBase, self).setUp()
        FakeRaven = raven.register_watchers(
            self.TEST_WATCHER)(_FakeRaven)
        self.fake_raven = FakeRaven()
        self.fake_raven._ensure_networking_base()
        self.translate = self.TEST_WATCHER.translate.__get__(
            self.fake_raven, FakeRaven)
        self.addCleanup(self.fake_raven.stop)


class TestK8sPodsWatcher(TestK8sWatchersBase):
    """The unit test for the translate method of TestK8sPodsWatcher.

    The following tests validate if translate method works appropriately.
    """
    TEST_WATCHER = watchers.K8sPodsWatcher

    def test_translate_added(self):
        """Tests if K8sServicesWatcher.translate works as intended."""
        fake_pod_added_event = {
            "type": "ADDED",
            "object": self.fake_pod_object,
        }
        fake_port_name = fake_pod_added_event['object']['metadata']['name']
        fake_network_id = self.fake_raven._network['id']
        fake_port_id = str(uuid.uuid4())
        fake_port = self._get_fake_port(
            fake_port_name, fake_network_id, fake_port_id)['port']
        fake_port_future = asyncio.Future(loop=self.fake_raven._event_loop)
        fake_port_future.set_result({'port': fake_port})
        metadata = fake_pod_added_event['object']['metadata']
        new_port = {
            'name': metadata.get('name', ''),
            'network_id': self.fake_raven._network['id'],
            'admin_state_up': True,
            'device_owner': constants.DEVICE_OWNER,
            'fixed_ips': [{'subnet_id': self.fake_raven._subnet['id']}],
            'security_groups': [self.fake_raven._default_sg],
        }
        self.mox.StubOutWithMock(self.fake_raven, 'delegate')
        self.fake_raven.delegate(
            mox.IsA(self.fake_raven.neutron.create_port),
            {'port': new_port}).AndReturn(fake_port_future)
        path = metadata.get('selfLink', '')
        annotations = copy.deepcopy(metadata['annotations'])
        metadata = {}
        metadata.update({'annotations': annotations})
        annotations.update(
            {constants.K8S_ANNOTATION_PORT_KEY: jsonutils.dumps(fake_port)})
        fake_subnet = self.fake_raven._subnet
        annotations.update(
            {constants.K8S_ANNOTATION_SUBNETS_KEY: jsonutils.dumps(
                [fake_subnet])})
        fake_pod_update_data = {
            "kind": "Pod",
            "apiVersion": "v1",
            "metadata": metadata,
        }
        headers = {
            'Content-Type': 'application/merge-patch+json',
            'Accept': 'application/json',
        }

        fake_patch_response = _FakeSuccessResponse()
        fake_patch_response_future = asyncio.Future(
            loop=self.fake_raven._event_loop)
        fake_patch_response_future.set_result(fake_patch_response)
        self.fake_raven.delegate(
            requests.patch, watchers.K8S_API_ENDPOINT_BASE + path,
            data=jsonutils.dumps(fake_pod_update_data),
            headers=headers).AndReturn(fake_patch_response_future)
        self.mox.ReplayAll()
        self.fake_raven._event_loop.run_until_complete(
            self.translate(fake_pod_added_event))

    def test_translate_deleted(self):
        """Tests DELETED events for watcher.

        Tests if K8sServicesWatcher.translate works as intended for DELETED.
        """
        fake_pod_deleted_event = {
            "type": "DELETED",
            "object": self.fake_pod_object,
        }
        fake_port_name = fake_pod_deleted_event['object']['metadata']['name']
        fake_network_id = self.fake_raven._network['id']
        fake_port_id = str(uuid.uuid4())
        fake_port = self._get_fake_port(
            fake_port_name, fake_network_id, fake_port_id)['port']
        metadata = fake_pod_deleted_event['object']['metadata']
        annotations = metadata['annotations']
        annotations.update(
            {constants.K8S_ANNOTATION_PORT_KEY: jsonutils.dumps(fake_port)})
        self.mox.StubOutWithMock(self.fake_raven, 'delegate')
        none_future = asyncio.Future(loop=self.fake_raven._event_loop)
        none_future.set_result(None)
        self.fake_raven.delegate(
            mox.IsA(self.fake_raven.neutron.delete_port),
            fake_port_id).AndReturn(none_future)
        self.mox.ReplayAll()
        self.fake_raven._event_loop.run_until_complete(
            self.translate(fake_pod_deleted_event))
