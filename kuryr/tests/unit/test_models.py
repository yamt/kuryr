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

import ddt
import testtools

from kuryr.raven import models
from kuryr.tests.unit import base


@ddt.ddt
class TestKuryrPoolMember(base.TestKuryrBase):

    @ddt.data(('0.0.0.260', 80, 'b0a21d73-1e0c-461b-81ed-0cb0142a925c'),
              ('192.168.0.111', 70000, 'a3261981-97ab-4000-ace3-79a32b55ddb8'),
              ('10.10.11.2', 8080, 'notauuid'))
    @ddt.unpack
    def test_failed_initialization(self, address, port, member_id):
        with testtools.ExpectedException(ValueError):
            models.PoolMember(address, port, member_id)

    @ddt.data(('172.16.0.2', 1, 'b0a21d73-1e0c-461b-81ed-0cb0142a925c'),
              ('192.168.0.111', 65535, 'a3261981-97ab-4000-ace3-79a32b55ddb8'),
              ('10.10.11.2', 8080, None))
    @ddt.unpack
    def test_initialization(self, address, port, member_id):
        models.PoolMember(address, port, member_id)

    @ddt.data(
        (models.PoolMember('172.16.0.2',
                           1,
                           'b0a21d73-1e0c-461b-81ed-0cb0142a925c'),
         models.PoolMember('172.16.0.2',
                           1,
                           None)),
        (models.PoolMember('192.168.11.10',
                           8000,
                           '0614732d-d2d9-4a7a-9053-b7e3db262101'),
         models.PoolMember('192.168.11.10',
                           8000,
                           '0614732d-d2d9-4a7a-9053-b7e3db262101')))
    @ddt.unpack
    def test_equality(self, left, right):
        self.assertEqual(left, right)

    @ddt.data(
        (frozenset([
            models.PoolMember('172.16.0.2',
                              80,
                              'a2ecf111-ce98-4cc2-94e7-b8f0b20724dd'),
            models.PoolMember('172.16.0.3',
                              80),
            models.PoolMember('172.16.0.4',
                              8080)]),
         models.PoolMember('172.16.0.2',
                           80,
                           'a2ecf111-ce98-4cc2-94e7-b8f0b20724dd')),
        (frozenset([
            models.PoolMember('172.16.0.2',
                              80,
                              'a2ecf111-ce98-4cc2-94e7-b8f0b20724dd'),
            models.PoolMember('172.16.0.3',
                              80),
            models.PoolMember('172.16.0.4',
                              8080)]),
         models.PoolMember('172.16.0.2',
                           80)),
        (frozenset([
            models.PoolMember('172.16.0.2',
                              80,
                              'a2ecf111-ce98-4cc2-94e7-b8f0b20724dd'),
            models.PoolMember('172.16.0.3',
                              80),
            models.PoolMember('172.16.0.4',
                              8080)]),
         models.PoolMember('172.16.0.4',
                           8080,
                           'a2ecf111-ce98-4cc2-94e7-b8f0b20724dd')))
    @ddt.unpack
    def test_contains(self, collection, member):
        self.assertIn(member, collection)

    @ddt.data(
        (frozenset([
            models.PoolMember('172.16.0.2',
                              80,
                              'a2ecf111-ce98-4cc2-94e7-b8f0b20724dd'),
            models.PoolMember('172.16.0.3',
                              80),
            models.PoolMember('172.16.0.4',
                              8080)]),
         models.PoolMember('172.16.0.2',
                           90,
                           'a2ecf111-ce98-4cc2-94e7-b8f0b20724dd')),
        (frozenset([
            models.PoolMember('172.16.0.2',
                              80,
                              'a2ecf111-ce98-4cc2-94e7-b8f0b20724dd'),
            models.PoolMember('172.16.0.3',
                              80),
            models.PoolMember('172.16.0.4',
                              8080)]),
         models.PoolMember('172.16.0.5',
                           80)),
        (frozenset([
            models.PoolMember('172.16.0.2',
                              80,
                              'a2ecf111-ce98-4cc2-94e7-b8f0b20724dd'),
            models.PoolMember('172.16.0.3',
                              80),
            models.PoolMember('172.16.0.4',
                              8080)]),
         models.PoolMember('172.16.0.4',
                           8081,
                           'a2ecf111-ce98-4cc2-94e7-b8f0b20724dd')))
    @ddt.unpack
    def test_doesnt_contain(self, collection, member):
        self.assertNotIn(member, collection)

    @ddt.data(
        ('172.16.0.4', 2000, '2f974c67-1acf-4d90-9803-b2d5e7f9ede6'),
        ('172.16.0.4', 2000, None),
        ('10.10.10.10', 80, 'bc349d6b-de41-4d8b-b843-698b269df08b'))
    @ddt.unpack
    def test_representation(self, addr, port, member_id):
        text = '{}'.format(models.PoolMember(addr, port, member_id))
        self.assertIn(str(addr), text)
        self.assertIn(str(port), text)
        self.assertIn(str(member_id), text)
        self.assertIn(models.PoolMember.__name__, text)
