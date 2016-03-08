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

from kuryr.cni import constants as const
from kuryr.cni import driver
from kuryr.tests.unit import base


@ddt.ddt
class TestCNIHelpers(base.TestKuryrBase):
    """Tests the helper methods in the Kuryr CNI driver"""
    basic_env = {
        const.ARGS: 'FOO=BAR',
        const.PATH: '/usr/bin/kuryr_cni',
        const.CONTAINERID: '7ed0919e-c835-4e1b-b788-cc952ba95ff1',
        const.NETNS: '/proc/11/ns/net',
        const.COMMAND: 'ADD',
        const.IFNAME: 'eth0'}

    @ddt.data(
        {},
        {'CNI_PATH': '/usr/bin/kuryr_cni',
         'CNI_CONTAINERID': '7ed0919e-c835-4e1b-b788-cc952ba95ff1',
         'CNI_NETNS': '/proc/11/ns/net',
         'CNI_IFNAME': 'eth0'})
    def test__check_vars_exc(self, env):
        self.mox.StubOutWithMock(driver.os.environ, 'copy')
        driver.os.environ.copy().AndReturn(env)
        self.mox.ReplayAll()

        self.assertRaises(driver.exceptions.KuryrException,
                          driver.KuryrCNIDriver)

    @ddt.data(
        ('FOO=A;BAR=B;BELL=BAR',
         {'BAR': 'B', 'BELL': 'BAR', 'FOO': 'A'}),
        ('',
         {}),
        (';',
         {}),
        ('BOO=URNS',
         {'BOO': 'URNS'}))
    @ddt.unpack
    def test__parse_cni_args_as_dict(self, data, expected):
        self.mox.StubOutWithMock(driver.os.environ, 'copy')
        driver.os.environ.copy().AndReturn(self.basic_env)
        self.mox.ReplayAll()

        dri = driver.KuryrCNIDriver()
        self.assertEqual(dri._parse_cni_args_as_dict(data), expected)
