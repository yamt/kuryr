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

"""Kuryr CNI Driver.

This module provides the abstract methods and entry points to implement
the CNI spec: https://github.com/appc/cni
"""

import abc
import os

import netaddr
import requests

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import excutils

from kuryr._i18n import _LE
from kuryr import binding
from kuryr.cni import constants as cni_consts
from kuryr.cni import models
from kuryr.common import constants
from kuryr.common import exceptions


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class KuryrCNIDriver(object):
    """Abstracted CNI driver interface.

    This class requires the users to implement add and delete methods.
    """
    MANDATORY_ENV_VARS = frozenset([
        cni_consts.PATH, cni_consts.CONTAINERID, cni_consts.NETNS,
        cni_consts.IFNAME, cni_consts.COMMAND, cni_consts.ARGS])

    def __init__(self):
        self.env = os.environ.copy()
        self._check_envvars()
        self.path = self.env[cni_consts.PATH]
        self.container_id = self.env[cni_consts.CONTAINERID]
        self.netns = self.env[cni_consts.NETNS]
        self.ifname = self.env[cni_consts.IFNAME]
        self.command = self.env[cni_consts.COMMAND]
        self.cni_args = self._parse_cni_args_as_dict(
            self.env[cni_consts.ARGS])
        LOG.debug('%s %s %s %s %s', self.path, self.container_id, self.netns,
                  self.ifname, self.command)

    @abc.abstractmethod
    def add(self):
        """Adds an interface."""

    @abc.abstractmethod
    def delete(self):
        """Deletes an interface."""

    def run_command(self):
        """Runs the command defined by CNI_COMMAND, either "ADD" or "DEL"."""
        if self.command == cni_consts.METHOD_ADD:
            return self.add()
        if self.command == cni_consts.METHOD_DEL:
            return self.delete()

    def _check_envvars(self):
        for var in self.MANDATORY_ENV_VARS:
            if var not in self.env:
                msg_error = "Missing ENV VAR '%s'" % var
                kuryr_error = models.CNIError(1, msg_error)
                LOG.error(_LE('Lacking environment %s'), kuryr_error)
                raise exceptions.KuryrException(str(kuryr_error))

    def _parse_cni_args_as_dict(self, cni_args):
        """Returns the resulting dictionary from parsing cni args (can be {})

        Turns FOO=A;BAR=B;BELL=BAR
        into {'BAR': 'B', 'BELL': 'BAR', 'FOO': 'A'}
        """
        return {key: value for key, value in (
                item.split('=') for item in cni_args.split(';') if item)}


class KuryrCNIK8sNeutronDriver(KuryrCNIDriver):
    """CNI Driver for K8s that binds Neutron ports."""
    def __init__(self):
        super(KuryrCNIK8sNeutronDriver, self).__init__()
        self.pod_namespace = self.cni_args['K8S_POD_NAMESPACE']
        self.pod_name = self.cni_args['K8S_POD_NAME']
        self.pod_container_id = self.cni_args['K8S_POD_INFRA_CONTAINER_ID']

    def _get_pod_annotaions(self):
        k8s_url = "%s/api/v1/namespaces/%s/pods/%s" % (
            CONF.k8s.api_root,
            self.pod_namespace,
            self.pod_name)
        LOG.debug('URL of the pod %s', k8s_url)
        response = requests.get(k8s_url)
        pod = response.json()
        return pod['metadata']['annotations']

    def add(self):
        """Binds the container to the Neutron port given by the API watcher."""
        LOG.debug('Binding the pod %s into network', self.container_id)

        endpoint_id = self.container_id
        pod_annotations = self._get_pod_annotaions()
        neutron_port = jsonutils.loads(
            pod_annotations[constants.K8S_ANNOTATION_PORT_KEY])
        neutron_subnets = jsonutils.loads(
            pod_annotations[constants.K8S_ANNOTATION_SUBNETS_KEY])

        try:
            ifname, peer_name, (stdout, stderr) = binding.port_bind(
                endpoint_id, neutron_port, neutron_subnets,
                ifname=self.ifname, netns=self.netns)
            LOG.debug(stdout)
            if stderr:
                LOG.error(stderr)
        except exceptions.VethCreationFailure as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Preparing the veth pair was failed: {0}.')
                          .format(ex))
        except processutils.ProcessExecutionError:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE(
                    'Could not bind the Neutron port to the veth endpoint.'))

        info = models.CNIInfo()
        cidr = netaddr.IPNetwork(neutron_subnets[0]['cidr'])
        ip_address = neutron_port.get('ip_address', '')
        fixed_ips = neutron_port.get('fixed_ips', [])
        if not ip_address and fixed_ips:
            ip_address = fixed_ips[0].get('ip_address', '')
        port_ip = '/'.join([ip_address, str(cidr.prefixlen)])
        gateway_ip = neutron_subnets[0]['gateway_ip']
        info.set_ipv4_info(ip=port_ip, gateway=gateway_ip)
        LOG.debug(str(info))
        return str(info)

    def delete(self):
        """Unbinds the Neutron port from the pod."""
        endpoint_id = self.container_id
        pod_annotations = self._get_pod_annotaions()
        neutron_port = jsonutils.loads(
            pod_annotations[constants.K8S_ANNOTATION_PORT_KEY])

        try:
            stdout, stderr = binding.port_unbind(endpoint_id, neutron_port)
            LOG.debug(stdout)
            if stderr:
                LOG.error(stderr)
        except processutils.ProcessExecutionError:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE(
                    'Could not unbind the Neutron port from the veth '
                    'endpoint.'))
        except exceptions.VethDeletionFailure:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Cleaning the veth pair up was failed.'))


def run_driver():
    """Runs the CNI driver."""
    driver = KuryrCNIK8sNeutronDriver()
    return driver.run_command()
