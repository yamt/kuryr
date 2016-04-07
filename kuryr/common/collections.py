#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
from __future__ import absolute_import

import collections


class Cache(collections.OrderedDict):
    """FIFO cache

    This cache collection is a Map designed to be of limited size by specifying
    a max_size keyword argument. Such collection can be useful when you want
    to have a reasonably sized map for things like memoization or book keeping
    of already seen events.
    """
    DEFAULT_CACHE_SIZE = 20

    def __init__(self, *args, **kwargs):
        self._max_size = kwargs.pop('max_size', self.DEFAULT_CACHE_SIZE)
        super(Cache, self).__init__(*args, **kwargs)
        self._adjust_size()

    def _adjust_size(self):
        """Postcondition: the length is at most self._max_size

        This is a house keeping method to be used after inserting/updating
        the cache
        """
        diff = len(self) - self._max_size
        while diff > 0:
            self.popitem(last=False)  # Pops the oldest item
            diff -= 1

    def __setitem__(self, key, value):
        """Sets an item respecting the cache size"""
        super(Cache, self).__setitem__(key, value)
        self._adjust_size()
