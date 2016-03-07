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
import signal
import sys
import traceback

from oslo_log import log
from oslo_serialization import jsonutils
from oslo_service import service
import requests

from kuryr._i18n import _LE
from kuryr.common import config
from kuryr.raven.aio import headers
from kuryr.raven.aio import methods
from kuryr.raven import watchers


LOG = log.getLogger(__name__)


def register_watchers(*watchers):
    """Registers one or more watchers to ``WATCH_ENDPONT_AND_CALL_BACKS``.

    This functions is intended to be used as a decorator for a class. The
    watchers **must** conform to the requirements of ``K8sApiWatcher`` abstract
    class, that is to implement ``WATCH_ENDPONT`` property and ``translate``
    method.

    >>> from kuryr.raven import watchers
    >>> class SomeWatcher(watchers.K8sApiWatcher):
    ...     WATCH_ENDPONT = '/'
    ...     def translate(self, deserialized_json):
    ...         print(deserialized_json)
    ...
    >>> @register_watchers(SomeWatcher)
    ... class Foo(object)
    ...     pass
    ...
    """
    def wrapper(cls):
        if not hasattr(cls, 'WATCH_ENDPOINTS_AND_CALLBACKS'):
            # For unit tests, we preserve the order of items.
            cls.WATCH_ENDPOINTS_AND_CALLBACKS = collections.OrderedDict()
        for watcher in watchers:
            slot = cls.WATCH_ENDPOINTS_AND_CALLBACKS
            slot[watcher.WATCH_ENDPOINT] = watcher.translate
        return cls
    return wrapper


@register_watchers(watchers.K8sPodsWatcher, watchers.K8sServicesWatcher)
class Raven(service.Service):
    """A K8s API watcher service watches and translates K8s resources.

    This class makes the GET requests against the K8s integration related
    resource endpoints with ``?watch=true`` query string and receive a series
    of event notifications on the watched resource endpoints. The event
    notifications are given in the JSON format. Then this class translates
    the events into the creations, deletions or updates of Neutron resources.
    """
    # TODO(tfukushima): Initialize the global neutronclient here.
    neutron = None
    # For unit tests this is the ordered dictionary.
    WATCH_ENDPOINTS_AND_CALLBACKS = collections.OrderedDict()

    def __init__(self):
        super(Raven, self).__init__()
        self._event_loop = asyncio.new_event_loop()
        self._tasks = None
        assert not self._event_loop.is_closed()

    def restart(self):
        LOG.debug('Restarted the service: {0}'.format(self.__class__.__name__))
        super(Raven, self).restart()

    def start(self):
        """Starts the event loop and watch endpoints."""
        LOG.debug('Started the service: {0}'.format(self.__class__.__name__))
        super(Raven, self).start()
        LOG.debug('Watched endpoints: {0}'
                  .format(self.WATCH_ENDPOINTS_AND_CALLBACKS))
        try:
            futures = [
                asyncio.async(self.watch(
                    endpoint, callback.__get__(self, Raven)),
                    loop=self._event_loop)
                for endpoint, callback in
                self.WATCH_ENDPOINTS_AND_CALLBACKS.items()]
            self._tasks = asyncio.gather(*futures, loop=self._event_loop)
            self._event_loop.add_signal_handler(
                signal.SIGTERM, self._tasks.cancel)
            self._event_loop.add_signal_handler(
                signal.SIGINT, self._tasks.cancel)
            self._event_loop.run_until_complete(self._tasks)
        except Exception as e:
            LOG.error(_LE('Caught the exception in the event loop: {0}')
                      .format(e))
            LOG.error(traceback.format_exc())
            self._event_loop.close()
            sys.exit(1)
        else:
            self._event_loop.close()
            sys.exit(0)

    def stop(self, graceful=False):
        """Stops the event loop if it's not stopped already."""
        if hasattr(self, '_tasks') and (not self._tasks.done()):
            self._tasks.cancel()
            self._tasks.exception()
            self._event_loop.run_forever()
        if self._event_loop.is_running():
            self._event_loop.stop()
        if not self._event_loop.is_closed():
            self._event_loop.close()
        super(Raven, self).stop(graceful)
        LOG.debug('Stopped the service: {0}'.format(self.__class__.__name__))

    def wait(self):
        LOG.debug('Wait for the service: {0}'.format(self.__class__.__name__))
        super(Raven, self).wait()

    @asyncio.coroutine
    def watch(self, endpoint, callback):
        response = yield from methods.get(
            endpoint=endpoint,
            loop=self._event_loop,
            decoder=lambda x: jsonutils.loads(x.decode('utf8')))

        # Get headers
        status, reason, hdrs = yield from response.read_headers()
        if status != 200:
            LOG.error(_LE('GET request to endpoint {} failed with status {} '
                          'and reason {}').format(endpoint, status, reason))
            raise requests.exceptions.HTTPError('{}: {}. Endpoint {}'.format(
                status, reason, endpoint))
        if hdrs.get(headers.TRANSFER_ENCODING) != 'chunked':
            LOG.error(_LE('watcher GET request to endpoint {} is not chunked. '
                          'headers: {}').format(endpoint, hdrs))
            raise IOError('Can only watch endpoints that returned chunked '
                          'encoded transfers')
        while True:
            try:
                content = yield from response.read_line()
            except asyncio.CancelledError:
                LOG.debug('Watch task of endpoint {} has been cancelled'
                    .format(endpoint))
                break
            if content is None:
                LOG.debug('Watch task of endpoint {} has arrived at EOF'
                    .format(endpoint))
                break
            callback(content)


def run_raven():
    """Launchs a Raven service."""
    raven = service.launch(config.CONF, Raven())
    raven.wait()
