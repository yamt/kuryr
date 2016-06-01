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
from concurrent import futures
import functools
import hashlib
import ipaddress
import signal
import sys
import traceback

import netaddr
from oslo_log import log
from oslo_service import service
import requests

from kuryr._i18n import _LE
from kuryr._i18n import _LI
from kuryr.common import collections as k_collections
from kuryr.common import config
from kuryr import controllers
from kuryr.raven.aio import headers
from kuryr.raven.aio import methods
from kuryr.raven import watchers
from kuryr import utils


LOG = log.getLogger(__name__)

HARDCODED_NET_NAME = 'raven-default'
HARDCODED_SG_NAME = 'raven-default-sg'
DEFAULT_PREFIX_LEN = 24


def register_watchers(*watchers):
    """Registers one or more watchers to ``WATCH_ENDPOINT_AND_CALLBACKS``.

    This functions is intended to be used as a decorator for a class. The
    watchers **must** conform to the requirements of ``K8sApiWatcher`` abstract
    class, that is to implement ``WATCH_ENDPOINT`` property and ``translate``
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


# TODO(devvesa): refactor current decorator approach to allow not intrusive
#                way to add more watchers.
@register_watchers(watchers.K8sPodsWatcher,
                   watchers.K8sServicesWatcher,
                   watchers.K8sNamespaceWatcher)
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
        self._executor = futures.ThreadPoolExecutor(
            max_workers=config.CONF.raven.max_workers)
        self._sequential_executor = futures.ThreadPoolExecutor(max_workers=1)
        self._event_loop = asyncio.new_event_loop()
        self._event_loop.set_default_executor(self._executor)
        self._event_cache = k_collections.Cache()
        self._tasks = {}
        self._reconnect = True
        assert not self._event_loop.is_closed()

    @staticmethod
    def _get_router_ports_by_subnet_id(neutron_subnet_id, neutron_port_list):
        router_ports = [
            port for port in neutron_port_list
            if ((neutron_subnet_id in [fip['subnet_id']
                                       for fip in port.get('fixed_ips', [])])
                or (neutron_subnet_id == port.get('subnet_id', '')))]

        return router_ports

    def _get_or_create_service_router(self):
        router_name = HARDCODED_NET_NAME + '-router'
        routers = controllers._get_routers_by_attrs(
            unique=False, name=router_name)
        if routers:
            router = routers[0]
            LOG.debug('Reusing the existing router {0}'.format(router))
        else:
            created_router_response = self.neutron.create_router(
                {'router': {'name': router_name}})
            router = created_router_response['router']
            LOG.debug('Created a new router {0}'.format(router))

        return router

    def _create_default_security_group(self):
        sgs = controllers._get_security_groups_by_attrs(
            unique=False, name=HARDCODED_SG_NAME)
        if sgs:
            sg = sgs[0]
            LOG.debug('Reusing the existing SG {0}'.format(sg))
        else:
            sg_response = self.neutron.create_security_group(
                {'security_group': {'name': HARDCODED_SG_NAME}})
            sg = sg_response['security_group']
            # Create ingress rules similarly to Neutron Default SG
            for ethertype in ['IPv4', 'IPv6']:
                rule = {
                    'security_group_id': sg['id'],
                    'ethertype': ethertype,
                    'direction': 'ingress',
                    'remote_group_id': sg['id'],
                }
                req = {
                    'security_group_rule': rule,
                }
                LOG.debug('Creating SG rule {0}'.format(req))
                self.neutron.create_security_group_rule(req)
            LOG.debug('Created a new default SG {0}'.format(sg))
        self._default_sg = sg['id']

    def _construct_subnetpool(self, namespace_router):
        subnetpool_name = HARDCODED_NET_NAME + '-pool'
        subnetpool_prefix = config.CONF.k8s.cluster_subnet_pool
        subnetpools = controllers._get_subnetpools_by_attrs(
            unique=False, name=subnetpool_name)
        if subnetpools:
            subnetpool = subnetpools[0]
            LOG.debug(
                'Reusing the existing subnet pool %s', subnetpool)
        else:
            subnetpool_response = self.neutron.create_subnetpool(
                {'subnetpool': {'name': subnetpool_name,
                                'prefixes': [subnetpool_prefix],
                                'default_prefixlen': DEFAULT_PREFIX_LEN}})
            subnetpool = subnetpool_response['subnetpool']
        self._subnetpool = subnetpool

    def _construct_cluster_network(self, namespace_router):
        network_name = HARDCODED_NET_NAME + '-cluster-pool'
        subnet_name = HARDCODED_NET_NAME + '-cluster-pool-subnet'
        networks = controllers._get_networks_by_attrs(name=network_name)
        if networks:
            self._cluster_network = networks[0]
        else:
            network_response = self.neutron.create_network(
                {'network': {'name': network_name}})
            self._cluster_network = network_response['network']
            LOG.debug('Created a new cluster network %s',
                self._cluster_network)

        # Ensure the subnet exists
        subnets = controllers._get_subnets_by_attrs(
            name=subnet_name,
            network_id=self._cluster_network['id'])
        if subnets:
            self._cluster_subnet = subnets[0]['subnet']
        else:
            subnet_range = ipaddress.ip_network(
                config.CONF.k8s.cluster_vip_subnet)
            new_subnet = {
                'name': subnet_name,
                'network_id': self._cluster_network['id'],
                'ip_version': subnet_range.version,
                'cidr': str(subnet_range),
                'enable_dhcp': False
            }
            subnet_response = self.neutron.create_subnet(
                {'subnet': new_subnet})
            self._cluster_subnet = subnet_response['subnet']
            LOG.debug('Created a new cluster subnet %s', self._cluster_subnet)

        self._ensure_router_port(
            self._cluster_network['id'],
            self._cluster_subnet['id'])

    def _ensure_router_port(self, port_network_id, port_subnet_id):

        filtered_service_ports = controllers._get_ports_by_attrs(
            unique=False, device_owner='network:router_interface',
            device_id=self._router['id'], network_id=port_network_id)

        service_router_ports = self._get_router_ports_by_subnet_id(
            port_subnet_id, filtered_service_ports)

        if not service_router_ports:
            self.neutron.add_interface_router(
                self._router['id'], {'subnet_id': port_subnet_id})
        else:
            LOG.debug('The cluster IP subnet %s is already bound to the '
                      'router.', port_subnet_id)

    def _construct_service_network(self, namespace_router):
        service_network_name = HARDCODED_NET_NAME + '-service'
        service_networks = controllers._get_networks_by_attrs(
            unique=False, name=service_network_name)
        if service_networks:
            service_network = service_networks[0]
            LOG.debug('Reusing the existing service network {0}'
                      .format(service_network))
        else:
            service_network_response = self.neutron.create_network(
                {'network': {'name': service_network_name}})
            service_network = service_network_response['network']
            LOG.debug('Created a new service network {0}'
                      .format(service_network))
            self._service_network = service_network

        service_subnet_cidr = config.CONF.k8s.cluster_service_subnet
        service_subnets = controllers._get_subnets_by_attrs(
            unique=False, cidr=service_subnet_cidr,
            network_id=service_network['id'])
        if service_subnets:
            service_subnet = service_subnets[0]
            LOG.debug('Reusing the existing service subnet {0}'
                      .format(service_subnet))
        else:
            ip = netaddr.IPNetwork(service_subnet_cidr)
            new_service_subnet = {
                'name': HARDCODED_NET_NAME + '-' + service_subnet_cidr,
                'network_id': service_network['id'],
                'ip_version': ip.version,
                'cidr': service_subnet_cidr,
                'enable_dhcp': False,
            }
            service_subnet_response = self.neutron.create_subnet(
                {'subnet': new_service_subnet})
            service_subnet = service_subnet_response['subnet']
            LOG.debug('Created a new service subnet {0}'
                      .format(service_subnet))
        self._service_subnet = service_subnet

        neutron_service_network_id = service_network['id']
        neutron_router_id = namespace_router['id']

        filtered_service_ports = controllers._get_ports_by_attrs(
            unique=False, device_owner='network:router_interface',
            device_id=neutron_router_id,
            network_id=neutron_service_network_id)

        service_subnet_id = service_subnet['id']
        service_router_ports = self._get_router_ports_by_subnet_id(
            service_subnet_id, filtered_service_ports)

        if not service_router_ports:
            self.neutron.add_interface_router(
                neutron_router_id, {'subnet_id': service_subnet_id})
        else:
            LOG.debug('The cluster IP subnet {0} is already bound to the '
                      'router.'
                      .format(service_subnet_id))

    def _ensure_networking_base(self):
        self._create_default_security_group()

        router = self._get_or_create_service_router()
        self._router = router

        self._construct_subnetpool(router)
        self._construct_cluster_network(router)
        self._construct_service_network(router)

    def _task_done_callback(self, task):
        endpoint = self._tasks.pop(task)
        LOG.info(_LI('Finished watcher for endpoint "%s"'), endpoint)
        if not self._tasks:
            LOG.info(_LI('No more tasks to handle. Shutting down...'))
            self.stop()

    def restart(self):
        """Restarts Raven instance."""
        LOG.debug('Restarted the service: {0}'.format(self.__class__.__name__))
        super(Raven, self).restart()

    def start(self):
        """Starts the event loop and watch endpoints.

        Before starting the event loop and the watch, Raven creates the Neutron
        network and subnet for the services with the router to be shared among
        the namespaces.

        Then Raven creates tasks consumed in the event loop with the registered
        callbacks for each endpoint and their cancellation callbacks. The
        signal handlers are specified for the manual termination by users as
        well.

        Finally, Raven starts running the event loop until all tasks are
        completed.
        """
        LOG.debug('Started the service: {0}'.format(self.__class__.__name__))
        super(Raven, self).start()
        LOG.debug('Watched endpoints: {0}'
                  .format(self.WATCH_ENDPOINTS_AND_CALLBACKS))
        self._ensure_networking_base()

        for endpoint, callback in self.WATCH_ENDPOINTS_AND_CALLBACKS.items():
            task = self._event_loop.create_task(self.watch(
                endpoint, callback.__get__(self, Raven)))
            task.add_done_callback(self._task_done_callback)
            self._tasks[task] = endpoint

        self._event_loop.add_signal_handler(signal.SIGTERM, self.stop)
        self._event_loop.add_signal_handler(signal.SIGINT, self.stop)

        try:
            self._event_loop.run_forever()
        except Exception as e:
            LOG.error(_LE('Caught the exception in the event loop: {0}')
                      .format(e))
            LOG.error(traceback.format_exc())
            err_code = 1
        else:
            err_code = 0
        finally:
            if not self._event_loop.is_closed():
                self._event_loop.run_until_complete(
                    asyncio.gather(*asyncio.Task.all_tasks(
                        loop=self._event_loop)))
                self._event_loop.close()
            sys.exit(err_code)

    def stop(self, graceful=False):
        """Stops the event loop if it's not stopped already."""
        if hasattr(self, '_tasks') and self._tasks:
            LOG.info(_LI('Cancelling all the scheduled tasks'))
            for task, endpoint in self._tasks.items():
                LOG.info(_LI('Cancelling the watcher for "%s"'), endpoint)
                task.cancel()
        if self._event_loop.is_running():
            self._event_loop.stop()
        self._executor.shutdown(wait=True)
        self._sequential_executor.shutdown(wait=True)
        self._event_loop.close()

        super(Raven, self).stop(graceful)
        LOG.debug('Stopped the service: {0}'.format(self.__class__.__name__))

    def wait(self):
        """Waits for Raven to complete."""
        LOG.debug('Wait for the service: {0}'.format(self.__class__.__name__))
        super(Raven, self).wait()

    @asyncio.coroutine
    def _delegate(self, executor, func, *args, **kwargs):
        # run_in_executor of the event loop can't take the keyword args. So
        # all arguments are bound with functools.partial and create a new
        # function that takes no argument here.
        partially_applied_func = functools.partial(func, *args, **kwargs)
        result = yield from self._event_loop.run_in_executor(
            executor, partially_applied_func)
        return result

    @asyncio.coroutine
    def delegate(self, func, *args, **kwargs):
        """Delegates the execution of the passed function to this instance.

        The passed function or method is executed immediately in a different
        thread. This provides a generic abstraction for making the synchronized
        processes asynchronous.

        :param func:   The function or the method to be executed.
        :param args:   The arguments for the function, which can be the mixture
                       of regular and arbitrary arguments passed to the
                       function.
        :param kwargs: The keyword arguments passed to the function.
        :returns: The result of the execution of the passed function with the
                  arguments.
        """
        result = yield from self._delegate(
            self._executor, func, *args, **kwargs)
        return result

    @asyncio.coroutine
    def sequential_delegate(self, func, *args, **kwargs):
        """Delegates the sequential execution of the passed function.

        The passed function or the method is executed immediately in a
        different thread, but in a sequential way. This provides a generic
        abstraction for making the synchronized processes asynchronous.

        :param func:   The function or the method to be executed.
        :param args:   The arguments for the function, which can be the mixture
                       of regular and arbitrary arguments passed to the
                       function.
        :param kwargs: The keyword arguments passed to the function.
        :returns: The result of the execution of the passed function with the
                  arguments.
        """
        result = yield from self._delegate(
            self._sequential_executor, func, *args, **kwargs)
        return result

    @asyncio.coroutine
    def watch(self, endpoint, callback):
        """Watches the endpoint and calls the callback with its response.

        In this method the endpoint is assumed it keeps returning a JSON object
        line by line as its response. Otherwise the first line is consumed and
        the watch is finished after that.

        :param endpoint: The string of the API endpoint to be watched.
        :param callback: The function that is called with the decoded JSON
                         response returned by the HTTP call agaisnt the
                         endpoint.
        """
        response = yield from methods.get(endpoint=endpoint,
                                          loop=self._event_loop,
                                          decoder=utils.utf8_json_decoder)

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
                LOG.debug(
                    'Watch task of endpoint {} has been cancelled'.format(
                        endpoint))
                break
            if content is None:
                LOG.debug(
                    'Watch task of endpoint {} has arrived at EOF'.format(
                        endpoint))

                # Let's schedule another watch
                if self._reconnect:
                    next_watch = self._event_loop.create_task(self.watch(
                        endpoint, callback))
                    next_watch.add_done_callback(self._task_done_callback)
                    self._tasks[next_watch] = endpoint
                break
            else:
                hashed_content = hashlib.md5(str(content).encode()).hexdigest()
                if hashed_content in self._event_cache:
                    LOG.info(_LI(
                        'Event with content "%(content)r" already seen at loop'
                        ' time "%(old_time)s". Current loop time '
                        '"%(new_time)s". Skipping this already processed '
                        'event...'),
                        {'content': content,
                         'old_time': self._event_cache[hashed_content],
                         'new_time': self._event_loop.time()})
                    continue

                self._event_cache[hashed_content] = self._event_loop.time()

                if asyncio.iscoroutinefunction(callback):
                    task = callback(content)
                else:
                    task = self.delegate(callback, content)

                try:
                    yield from task
                except asyncio.CancelledError:
                    LOG.debug('Watching endpoint %s was cancelled during '
                              'callback execution.', endpoint)
                    break


def run_raven():
    """Launchs a Raven service."""
    config.init(sys.argv[1:])
    log.setup(config.CONF, 'Raven')
    raven = service.launch(config.CONF, Raven())
    raven.wait()
