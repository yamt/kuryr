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

"""Kuryr CNI Models.

CNI Message returns modeled in python classes for a better manipulation
"""

from oslo_serialization import jsonutils


class CNIError(object):
    """Message error for CNI response"""
    def __init__(self, code, msg, details=''):
        self.code = code
        self.msg = msg
        self.details = details

    def __repr__(self):
        error = {}
        error['cniVersion'] = '0.1.0'
        error['code'] = self.code
        error['msg'] = self.msg
        error['details'] = self.details
        error_json = jsonutils.dumps(error)
        return error_json


class CNIInfo(object):
    """CNI information returned to Kubelet through stdout.

    This is the class representation of the JSON data returned to Kubelet. See
    the following link for more details.

    - https://github.com/appc/cni/blob/master/SPEC.md#result
    """
    def __init__(self):
        self.ipv4_ip = ''
        self.ipv4_gateway = ''
        self.ipv4_routes = []
        self.ipv6_ip = ''
        self.ipv6_gateway = ''
        self.ipv6_routes = []
        self.dns_nameservers = []
        self.dns_domain = ''
        self.dns_search = []
        self.dns_options = []

    def set_ipv4_info(self, ip='', gateway='', routes=None):
        self.ipv4_ip = ip
        self.ipv4_gateway = gateway
        self.ipv4_routes = routes or []

    def set_ipv6_info(self, ip='', gateway='', routes=None):
        self.ipv6_ip = ip
        self.ipv6_gateway = gateway
        self.ipv6_routes = routes or []

    def set_dns_info(self, nameservers=None, domain='',
                     search=None, options=None):
        self.dns_nameservers = nameservers or []
        self.dns_domain = domain
        self.dns_search = search or []
        self.dns_options = options or []

    def __repr__(self):
        info = {}
        info['cniVersion'] = '0.1.0'

        info_ipv4 = {}
        info_ipv4['ip'] = self.ipv4_ip
        if self.ipv4_gateway:
            info_ipv4['gateway'] = self.ipv4_gateway
        if self.ipv4_routes:
            info_ipv4['routes'] = self.ipv4_routes
        info['ip4'] = info_ipv4

        # info_ipv6 = {}
        # info_ipv6['ip'] = self.ipv6_ip
        # info_ipv6['gateway'] = self.ipv6_gateway
        # info_ipv6['routes'] = self.ipv6_routes
        # info['ip6'] = info_ipv6

        info_dns = {}
        if self.dns_nameservers:
            info_dns['nameservers'] = self.dns_nameservers
        if self.dns_domain:
            info_dns['domain'] = self.dns_domain
        if self.dns_search:
            info_dns['search'] = self.dns_search
        if self.dns_options:
            info_dns['options'] = self.dns_options
        info['dns'] = info_dns

        return jsonutils.dumps(info)
