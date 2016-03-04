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
