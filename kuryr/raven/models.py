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
import ipaddress
import uuid


class PoolMember(object):
    def __init__(self, address, protocol_port, member_id=None):
        """Initializes a PoolMember instance

        :param address: IPv4 address where the LBaaS pool can access the member
        :param protocol_port: Port where the LBaaS pool can access the member
        :para member_id: uuid that identifies the pool member
        """
        self.address = ipaddress.ip_address(address)
        if 1 <= protocol_port <= 2 ** 16 - 1:
            self.protocol_port = protocol_port
        else:
            raise ValueError('Port value outside valid range 1-65535')
        if member_id is None:
            self.uuid = member_id
        else:
            self.uuid = uuid.UUID(member_id)

    def __hash__(self):
        return (hash(self.address) ^
                hash(self.protocol_port))

    def __eq__(self, other):
        if None in (self.uuid, other.uuid):
            return (self.address == other.address and
                    self.protocol_port == self.protocol_port)
        else:
            return (self.address == other.address and
                    self.protocol_port == self.protocol_port and
                    self.uuid == other.uuid)

    def __repr__(self):
        return ('PoolMember(uuid: {uuid}, address: {addr}, '
                'protocol_port: {port})'.format(
                    uuid=self.uuid,
                    addr=self.address,
                    port=self.protocol_port))
