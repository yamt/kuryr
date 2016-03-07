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

import os

import netaddr
from oslo_concurrency import processutils
from oslo_utils import excutils
import pyroute2

from kuryr.common import config
from kuryr.common import exceptions


CONTAINER_VETH_POSTFIX = '_c'
BINDING_SUBCOMMAND = 'bind'
DOWN = 'DOWN'
FALLBACK_VIF_TYPE = 'unbound'
FIXED_IP_KEY = 'fixed_ips'
IFF_UP = 0x1  # The last bit represents if the interface is up
IP_ADDRESS_KEY = 'ip_address'
KIND_VETH = 'veth'
MAC_ADDRESS_KEY = 'mac_address'
SUBNET_ID_KEY = 'subnet_id'
UNBINDING_SUBCOMMAND = 'unbind'
VETH_POSTFIX = '-veth'
VIF_TYPE_KEY = 'binding:vif_type'

_IPDB_CACHE = None
_IPROUTE_CACHE = None


def get_ipdb():
    """Returns the already cached or a newly created IPDB instance.

    IPDB reads the Linux specific file when it's instantiated. This behaviour
    prevents Mac OSX users from running unit tests. This function makes the
    loading IPDB lazyily and therefore it can be mocked after the import of
    modules that import this module.

    :returns: The already cached or newly created ``pyroute2.IPDB`` instance
    """
    global _IPDB_CACHE
    if not _IPDB_CACHE:
        _IPDB_CACHE = pyroute2.IPDB()
    return _IPDB_CACHE


def get_iproute():
    """Returns the already cached or a newly created IPRoute instance.

    IPRoute reads the Linux specific file when it's instantiated. This
    behaviour prevents Mac OSX users from running unit tests. This function
    makes the loading IPDB lazyily and therefore it can be mocked after the
    import of modules that import this module.

    :returns: The already cached or newly created ``pyroute2.IPRoute`` instance
    """
    global _IPROUTE_CACHE
    if not _IPROUTE_CACHE:
        _IPROUTE_CACHE = pyroute2.IPRoute()
    return _IPROUTE_CACHE


def _is_up(interface):
    flags = interface['flags']
    if not flags:
        return False
    return (flags & IFF_UP) == 1


def cleanup_veth(ifname):
    """Cleans the veth passed as an argument up.

    :param ifname: the name of the veth endpoint
    :returns: the index of the interface which name is the given ifname if it
              exists, otherwise None
    :raises: pyroute2.netlink.NetlinkError
    """
    ipr = get_iproute()

    veths = ipr.link_lookup(ifname=ifname)
    if veths:
        host_veth_index = veths[0]
        ipr.link_remove(host_veth_index)
        return host_veth_index
    else:
        return None


def port_bind(endpoint_id, neutron_port, neutron_subnets):
    """Binds the Neutron port to the network interface on the host.

    :param endpoint_id:     the ID of the endpoint as string
    :param neutron_port:    a port dictionary returned from
                            python-neutronclient
    :param neutron_subnets: a list of all subnets under network to which this
                            endpoint is trying to join
    :returns: the tuple of the names of the veth pair and the tuple of stdout
              and stderr returned by processutils.execute invoked with the
              executable script for binding
    :raises: kuryr.common.exceptions.VethCreationFailure,
             processutils.ProcessExecutionError
    """
    ip = get_ipdb()

    ifname = endpoint_id[:8] + VETH_POSTFIX
    peer_name = ifname + CONTAINER_VETH_POSTFIX
    subnets_dict = {subnet['id']: subnet for subnet in neutron_subnets}

    try:
        with ip.create(ifname=ifname, kind=KIND_VETH,
                       reuse=True, peer=peer_name) as host_veth:
            if not _is_up(host_veth):
                host_veth.up()
        with ip.interfaces[peer_name] as peer_veth:
            fixed_ips = neutron_port.get(FIXED_IP_KEY, [])
            if not fixed_ips and (IP_ADDRESS_KEY in neutron_port):
                peer_veth.add_ip(neutron_port[IP_ADDRESS_KEY])
            for fixed_ip in fixed_ips:
                if IP_ADDRESS_KEY in fixed_ip and (SUBNET_ID_KEY in fixed_ip):
                    subnet_id = fixed_ip[SUBNET_ID_KEY]
                    subnet = subnets_dict[subnet_id]
                    cidr = netaddr.IPNetwork(subnet['cidr'])
                    peer_veth.add_ip(fixed_ip[IP_ADDRESS_KEY], cidr.prefixlen)
            peer_veth.address = neutron_port[MAC_ADDRESS_KEY].lower()
            if not _is_up(peer_veth):
                peer_veth.up()
    except pyroute2.ipdb.common.CreateException:
        raise exceptions.VethCreationFailure(
            'Creating the veth pair was failed.')
    except pyroute2.ipdb.common.CommitException:
        raise exceptions.VethCreationFailure(
            'Could not configure the veth endpoint for the container.')

    vif_type = neutron_port.get(VIF_TYPE_KEY, FALLBACK_VIF_TYPE)
    binding_exec_path = os.path.join(config.CONF.bindir, vif_type)
    port_id = neutron_port['id']
    network_id = neutron_port['network_id']
    tenant_id = neutron_port['tenant_id']
    mac_address = neutron_port['mac_address']
    try:
        stdout, stderr = processutils.execute(
            binding_exec_path, BINDING_SUBCOMMAND, port_id, ifname,
            endpoint_id, mac_address, network_id, tenant_id,
            run_as_root=True)
    except processutils.ProcessExecutionError:
        with excutils.save_and_reraise_exception():
            cleanup_veth(ifname)

    return (ifname, peer_name, (stdout, stderr))


def port_unbind(endpoint_id, neutron_port):
    """Unbinds the Neutron port from the network interface on the host.

    :param endpoint_id: the ID of the Docker container as string
    :param neutron_port: a port dictionary returned from python-neutronclient
    :returns: the tuple of stdout and stderr returned by processutils.execute
              invoked with the executable script for unbinding
    :raises: processutils.ProcessExecutionError, pyroute2.netlink.NetlinkError
    """

    vif_type = neutron_port.get(VIF_TYPE_KEY, FALLBACK_VIF_TYPE)
    unbinding_exec_path = os.path.join(config.CONF.bindir, vif_type)
    ifname = endpoint_id[:8] + VETH_POSTFIX
    port_id = neutron_port['id']
    mac_address = neutron_port['mac_address']
    stdout, stderr = processutils.execute(
        unbinding_exec_path, UNBINDING_SUBCOMMAND, port_id, ifname,
        endpoint_id, mac_address, run_as_root=True)
    try:
        cleanup_veth(ifname)
    except pyroute2.netlink.NetlinkError:
        raise exceptions.VethDeleteionFailure(
            'Deleting the veth pair failed.')
    return (stdout, stderr)
