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
from asyncio import test_utils
from collections import OrderedDict
import gc

import ddt

from kuryr.raven.aio import headers
from kuryr.raven.aio import methods
from kuryr.raven.aio import streams
from kuryr.tests.unit import base


@ddt.ddt
class TestAIOMethods(base.TestKuryrBase, test_utils.TestCase):
    data = (b'It is a truth universally acknowledged, that a single man in '
        b'possession of a good fortune, must be in want of a wife.')
    """The unit test for Raven's asynchronous IO for http requests"""
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.set_event_loop(self.loop)
        super().setUp()

    def tearDown(self):
        # just in case if we have transport close callbacks
        self.loop.close()
        gc.collect()
        super().tearDown()

    def test__auto_headers(self):
        url = 'https://docs.python.org/3.4/library/asyncio-stream.html'
        parsed_url = methods.parse.urlsplit(url)
        result = methods._auto_headers(parsed_url)
        self.assertIn((headers.HOST, 'docs.python.org'), result.items())
        self.assertIn(headers.USER_AGENT, result)

    def test__request_line(self):
        path = '/foo'
        self.assertEqual('GET /foo HTTP/1.1\r\n',
                         methods._request_line('GET', path))
        self.assertEqual('GET /foo HTTP/1.0\r\n',
                         methods._request_line('GET', path, '1.0'))
        self.assertEqual('PATCH /foo HTTP/1.1\r\n',
                         methods._request_line('PATCH', path))
        self.assertEqual('POST /foo HTTP/1.1\r\n',
                         methods._request_line('POST', path))

    @ddt.data(0, 2, 20, len(data))
    def test_response_read(self, length):
        reader = asyncio.streams.StreamReader(loop=self.loop)
        writer = self.mox.CreateMock(asyncio.StreamWriter)
        writer.close()

        reader.feed_data(self.data)
        response = methods.Response(reader, writer)
        response.headers = {headers.CONTENT_LENGTH: str(length)}

        self.mox.ReplayAll()
        body = self.loop.run_until_complete(response.read())
        self.assertEqual(body, self.data[:length])
        self.mox.VerifyAll()

    @ddt.data(
        (b'HTTP/1.1 200 OK\r\n'
         b'Server: nginx\r\n'
         b'Date: Wed, 23 Mar 2016 16:15:50 GMT\r\n'
         b'Content-Type: application/json\r\n'
         b'Content-Length: 31\r\n'
         b'Connection: keep-alive\r\n'
         b'Access-Control-Allow-Origin: *\r\n'
         b'Access-Control-Allow-Credentials: true\r\n'
         b'\r\n',
         (200, 'OK', {
          'SERVER': 'nginx',
          'DATE': 'Wed, 23 Mar 2016 16:15:50 GMT',
          'CONTENT-TYPE': 'application/json',
          'CONTENT-LENGTH': '31',
          'CONNECTION': 'keep-alive',
          'ACCESS-CONTROL-ALLOW-ORIGIN': '*',
          'ACCESS-CONTROL-ALLOW-CREDENTIALS': 'true'})),
        (b'HTTP/1.1 200 OK\r\n'
         b'Server: nginx\r\n'
         b'Date: Wed, 23 Mar 2016 18:14:04 GMT\r\n'
         b'Content-Type: application/json\r\n'
         b'Transfer-Encoding: chunked\r\n'
         b'\r\n',
         (200, 'OK', {
          'SERVER': 'nginx',
          'DATE': 'Wed, 23 Mar 2016 18:14:04 GMT',
          'CONTENT-TYPE': 'application/json',
          'TRANSFER-ENCODING': 'chunked'})))
    @ddt.unpack
    def test_response_read_headers(self, header, expected):
        reader = asyncio.StreamReader(loop=self.loop)
        writer = self.mox.CreateMock(asyncio.StreamWriter)

        reader.feed_data(header)
        response = methods.Response(reader, writer)

        result = self.loop.run_until_complete(response.read_headers())
        self. assertEqual(expected, result)

    def test__write_headers(self):
        expected = (b'GET /api/v1/pods HTTP/1.1\r\n'
                    b'HOST: 104.197.7.241:8080\r\n'
                    b'USER-AGENT: curl/7.48.0\r\n'
                    b'ACCEPT: */*\r\n'
                    b'\r\n')

        request_line = 'GET /api/v1/pods HTTP/1.1\r\n'
        ordered_headers = OrderedDict([(headers.HOST, '104.197.7.241:8080'),
                                       (headers.USER_AGENT, 'curl/7.48.0'),
                                       ('ACCEPT', '*/*')])

        writer = self.mox.CreateMock(asyncio.StreamWriter)
        writer.write(expected)
        self.mox.ReplayAll()

        methods._write_headers(writer=writer, headers=ordered_headers,
                               request_line=request_line)
        self.mox.VerifyAll()

    @ddt.data(
        (b'4\r\nWiki\r\n5\r\npedia\r\nE\r\n in\r\n\r\nchunks.\r\n0\r\n\r\n',
         (b'Wiki', b'pedia', b' in\r\n\r\nchunks.')),
        (b'3c\r\nabcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefgh'
         b'\r\n3c\r\nijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijklm'
         b'nop\r\n3c\r\nqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijklmnopqr'
         b'stuvwx\r\n3c\r\nyzabcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvw'
         b'xyzabcdef\r\n3c\r\nghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzab'
         b'cdefghijklmn\r\n3c\r\nopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefg'
         b'hijklmnopqrstuv\r\n3c\r\nwxyzabcdefghijklmnopqrstuvwxyzabcdefghijkl'
         b'mnopqrstuvwxyzabcd\r\n3c\r\nefghijklmnopqrstuvwxyzabcdefghijklmnopq'
         b'rstuvwxyzabcdefghijkl\r\n20\r\nmnopqrstuvwxyzabcdefghijklmnopqr\r\n'
         b'0\r\n\r\n',
         (b'abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefgh',
          b'ijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijklmnop',
          b'qrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwx',
          b'yzabcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdef',
          b'ghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijklmn',
          b'opqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuv',
          b'wxyzabcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcd',
          b'efghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijkl',
          b'mnopqrstuvwxyzabcdefghijklmnopqr')))
    @ddt.unpack
    def test_response_read_chunk(self, data, expected):
        reader = streams.ChunkedStreamReader(loop=self.loop)
        writer = self.mox.CreateMock(asyncio.StreamWriter)
        writer.close()

        reader.feed_data(data)
        response = methods.Response(reader, writer)

        @asyncio.coroutine
        def get_all_chunks(response):
            chunks = []
            while True:
                chunk = yield from response.read_chunk()
                if chunk is None:
                    break
                else:
                    chunks.append(chunk)
            return chunks

        self.mox.ReplayAll()
        chunks = self.loop.run_until_complete(get_all_chunks(response))
        for got, expect in zip(chunks, expected):
            self.assertEqual(got, expect)
        self.mox.VerifyAll()

    @ddt.data(
        (b'140\r\n'
         b'{"url": "http://httpbin.org/stream/2", '
         b'"headers": {"Host": "httpbin.org", '
         b'"User-Agent": "Python/3.4 raven/1.0"}, '
         b'"args": {}, "id": 0, "origin": "5.22.152.248"}\n'
         b'{"url": "http://httpbin.org/stream/2", '
         b'"headers": {"Host": "httpbin.org", '
         b'"User-Agent": "Python/3.4 raven/1.0"}, '
         b'"args": {}, "id": 1, "origin": "5.22.152.248"}\n\r\n0\r\n\r\n',
         (b'{"url": "http://httpbin.org/stream/2", '
          b'"headers": {"Host": "httpbin.org", '
          b'"User-Agent": "Python/3.4 raven/1.0"}, '
          b'"args": {}, "id": 0, "origin": "5.22.152.248"}\n',
          b'{"url": "http://httpbin.org/stream/2", '
          b'"headers": {"Host": "httpbin.org", '
          b'"User-Agent": "Python/3.4 raven/1.0"}, '
          b'"args": {}, "id": 1, "origin": "5.22.152.248"}\n')),)
    @ddt.unpack
    def test_response_read_line(self, data, expected):
        reader = streams.ChunkedStreamReader(loop=self.loop)
        writer = self.mox.CreateMock(asyncio.StreamWriter)
        writer.close()

        reader.feed_data(data)
        response = methods.Response(reader, writer)

        @asyncio.coroutine
        def get_all_lines(response):
            lines = []
            while True:
                line = yield from response.read_line()
                if line is None:
                    break
                else:
                    lines.append(line)
            return lines

        self.mox.ReplayAll()
        lines = self.loop.run_until_complete(get_all_lines(response))
        for got, expect in zip(lines, expected):
            self.assertEqual(expect, got)
        self.mox.VerifyAll()
