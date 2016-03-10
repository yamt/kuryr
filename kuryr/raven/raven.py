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
import functools
import signal
import sys
import traceback

import netaddr
from oslo_log import log
from oslo_serialization import jsonutils
from oslo_service import service
import requests

from kuryr._i18n import _LE
from kuryr.common import config
from kuryr import controllers
from kuryr.raven.aio import headers
from kuryr.raven.aio import methods
from kuryr.raven import watchers


LOG = log.getLogger(__name__)

HARDCODED_NET_NAME = 'raven-default'


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
    neutron = controllers.get_neutron_client()
    # For unit tests this is the ordered dictionary.
    WATCH_ENDPOINTS_AND_CALLBACKS = collections.OrderedDict()

    def __init__(self):
        super(Raven, self).__init__()
        self._event_loop = asyncio.new_event_loop()
        self._tasks = None
        assert not self._event_loop.is_closed()

    def _ensure_networking_base(self):
        networks = controllers._get_networks_by_attrs(
            unique=False, name=HARDCODED_NET_NAME)
        if networks:
            network = networks[0]
            LOG.debug('Reusing the existing network {0}'.format(network))
        else:
            network_response = self.neutron.create_network(
                {'network': {'name': HARDCODED_NET_NAME}})
            network = network_response['network']
            LOG.debug('Created a new network {0}'.format(network))
        self._network = network
        subnet_cidr = config.CONF.k8s.cluster_subnet
        subnets = controllers._get_subnets_by_attrs(
            unique=False, cidr=subnet_cidr)
        if subnets:
            subnet = subnets[0]
            LOG.debug('Reusing the existing subnet {0}'.format(subnet))
        else:
            ip = netaddr.IPNetwork(subnet_cidr)
            new_subnet = {
                'name': HARDCODED_NET_NAME + '-' + subnet_cidr,
                'network_id': network['id'],
                'ip_version': ip.version,
                'cidr': subnet_cidr,
                'enable_dhcp': False,
            }
            subnet_response = self.neutron.create_subnet(
                {'subnet': new_subnet})
            subnet = subnet_response['subnet']
            LOG.debug('Created a new subnet {0}'.format(subnet))
        self._subnet = subnet

        service_subnet_cidr = config.CONF.k8s.cluster_service_subnet
        service_subnets = controllers._get_subnets_by_attrs(
            unique=False, cidr=service_subnet_cidr)
        if service_subnets:
            service_subnet = service_subnets[0]
            LOG.debug('Reusing the existing service subnet {0}'
                      .format(service_subnet))
        else:
            ip = netaddr.IPNetwork(service_subnet_cidr)
            new_service_subnet = {
                'name': HARDCODED_NET_NAME + '-' + service_subnet_cidr,
                'network_id': network['id'],
                'ip_version': ip.version,
                'cidr': service_subnet_cidr,
                'enable_dhcp': False,
            }
            service_subnet_response = self.neutron.create_subnet(
                {'subnet': new_service_subnet})
            service_subnet = service_subnet_response['subnet']
            LOG.debug('Created a new service subnet {0}'
                      .format(service_subnet))
        self.service_subnet = service_subnet

    def restart(self):
        LOG.debug('Restarted the service: {0}'.format(self.__class__.__name__))
        super(Raven, self).restart()

    def start(self):
        """Starts the event loop and watch endpoints."""
        LOG.debug('Started the service: {0}'.format(self.__class__.__name__))
        super(Raven, self).start()
        LOG.debug('Watched endpoints: {0}'
                  .format(self.WATCH_ENDPOINTS_AND_CALLBACKS))
        self._ensure_networking_base()
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
    def delegate(self, func, *args, **kwargs):
        """Delegates the execution of the passed function to this instance.

        The passed function or the method is executed immediately in the
        different thread. This provides the generic abstraction for making the
        synchrounized processe asynchronous.

        :param func:   The function or the method to be executed.
        :param args:   The arguments for the function, which can be the mixutre
                       of the regular arguments and the arbitrary arguments
                       passed to the function.
        :param kwargs: The keyword arguments passed to the function.
        :returns: The result of the passed function with the arguments.
        """
        # run_in_executor of the event loop can't take the keyword args. So
        # all arguments are bound with functools.partial and create a new
        # function that takes no argument here.
        partiall_applied_func = functools.partial(func, *args, **kwargs)
        result = yield from self._event_loop.run_in_executor(
            None, partiall_applied_func)
        return result

    @asyncio.coroutine
    def watch(self, endpoint, callback):
        response = yield from methods.get(endpoint=endpoint,
                                          loop=self._event_loop,
                                          decoder=_utf8_decoder)

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
            if asyncio.iscoroutinefunction(callback):
                task = callback(content)
            else:
                task = self._event_loop.run_in_executor(
                    None, callback, content)

            try:
                yield from task
            except asyncio.CancelledError:
                LOG.debug('Watching endpoint %s was cancelled during callback'
                          'callback execution.', endpoint)


def _utf8_decoder(content):
    return jsonutils.loads(content.decode('utf8'))


def run_raven():
    """Launchs a Raven service."""
    raven = service.launch(config.CONF, Raven())
    raven.wait()
