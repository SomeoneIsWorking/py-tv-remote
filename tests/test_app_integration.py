import asyncio
from unittest.mock import patch, MagicMock
import socket

import pytest


@pytest.mark.asyncio
class TestAsyncWorkflow:
    """Verify the async patterns used by the app work correctly."""

    async def test_run_in_executor_basics(self):
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: 42)
        assert result == 42

    async def test_run_in_executor_blocking_call(self):
        def blocking_fn():
            import time
            time.sleep(0.1)
            return "done"

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, blocking_fn)
        assert result == "done"

    async def test_discover_in_executor(self):
        with patch("tv_remote.discovery.discover_tvs") as mock:
            expected = [{"name": "Mock TV", "host": "tv.local", "ips": ["10.0.0.1"]}]
            mock.return_value = expected

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: mock())
            assert result == expected

    async def test_pair_timeout_in_executor(self):
        with patch("tv_remote.protocol._create_tls_connection") as mock_tls:
            with patch("tv_remote.protocol.generate_cert") as mock_cert:
                mock_cert.return_value = ("/tmp/cert.pem", "/tmp/key.pem")

                mock_sock = MagicMock(spec=socket.socket)
                mock_sock.recv.side_effect = socket.timeout("timed out")
                mock_sock.settimeout = MagicMock()
                mock_tls.return_value = mock_sock

                from tv_remote.protocol import TVClient
                client = TVClient("10.0.0.1")
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: client.pair(connect_timeout=1, response_timeout=1))
                assert result == ("no_response", None)

    async def test_send_key_in_executor(self):
        with patch("tv_remote.protocol._create_tls_connection") as mock_tls:
            with patch("tv_remote.protocol.generate_cert") as mock_cert:
                mock_cert.return_value = ("/tmp/cert.pem", "/tmp/key.pem")
                mock_sock = MagicMock()
                mock_tls.return_value = mock_sock

                from tv_remote.protocol import TVClient
                client = TVClient("10.0.0.1")
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, lambda: client.connect(timeout=1))

                with patch("tv_remote.protocol._send_message") as mock_send:
                    await loop.run_in_executor(None, lambda: client.send_key(19))
                    assert mock_send.call_count == 2

    async def test_pair_success_flow_in_executor(self):
        with patch("tv_remote.protocol._create_tls_connection") as mock_tls:
            with patch("tv_remote.protocol.generate_cert") as mock_cert:
                mock_cert.return_value = ("/tmp/cert.pem", "/tmp/key.pem")

                from tv_remote.remote_pb2 import PairingMessage
                import struct

                def framed(msg):
                    data = msg.SerializeToString()
                    return bytes([len(data)]) + data

                options = framed(PairingMessage(status=PairingMessage.OPTIONS))

                code_req_msg = PairingMessage()
                code_req_msg.status = PairingMessage.PAIRING_CODE_REQUIRED
                code_req_msg.pairing_code = 1234
                code_req = framed(code_req_msg)

                success_msg = PairingMessage()
                success_msg.status = PairingMessage.PAIRING_CODE_RESPONSE_SUCCESS
                success = framed(success_msg)

                recv_calls = []
                for data in [options, code_req, success]:
                    recv_calls.append(data[:1])
                    recv_calls.append(data[1:])

                mock_sock = MagicMock()
                mock_sock.recv.side_effect = recv_calls
                mock_sock.settimeout = MagicMock()
                mock_tls.return_value = mock_sock

                from tv_remote.protocol import TVClient
                client = TVClient("10.0.0.1")
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: client.pair(pairing_code=1234, connect_timeout=1, response_timeout=3))
                assert result == (True, None)

    async def test_connect_rejected_in_executor(self):
        with patch("tv_remote.protocol._create_tls_connection") as mock_tls:
            mock_tls.side_effect = ConnectionRefusedError("Connection refused")

            from tv_remote.protocol import TVClient
            client = TVClient("10.0.0.1")
            loop = asyncio.get_running_loop()
            with pytest.raises(ConnectionRefusedError):
                await loop.run_in_executor(None, lambda: client.connect(timeout=1))
