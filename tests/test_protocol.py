import os
import struct
import tempfile
from unittest.mock import Mock, patch, MagicMock, call

import pytest

from tv_remote.protocol import (
    TVClient,
    KEYCODES,
    generate_cert,
    has_cert,
    _ensure_cert_dir,
    _host_cert_path,
    _host_key_path,
    _send_message,
    _recv_message,
    _recv_exact,
    CERT_DIR,
)
from tv_remote.remote_pb2 import PairingMessage, RemoteMessage


class TestCertificates:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.patcher = patch("tv_remote.protocol.CERT_DIR", self.temp_dir)
        self.patcher.start()

    def teardown_method(self):
        self.patcher.stop()
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ensure_cert_dir_creates_directory(self):
        cert_dir = os.path.join(self.temp_dir, "nested", "certs")
        with patch("tv_remote.protocol.CERT_DIR", cert_dir):
            _ensure_cert_dir()
            assert os.path.isdir(cert_dir)

    def test_generate_cert_creates_files(self):
        cert_path, key_path = generate_cert("192.168.1.100")
        assert os.path.isfile(cert_path)
        assert os.path.isfile(key_path)

        with open(cert_path) as f:
            assert "BEGIN CERTIFICATE" in f.read()
        with open(key_path) as f:
            assert "BEGIN PRIVATE KEY" in f.read()

    def test_has_cert_true_after_generate(self):
        generate_cert("192.168.1.100")
        assert has_cert("192.168.1.100") is True

    def test_has_cert_false_before_generate(self):
        assert has_cert("nonexistent.host") is False

    def test_host_cert_path_uses_safe_name(self):
        path = _host_cert_path("192.168.1.100")
        assert "192_168_1_100.pem" in path

        path = _host_cert_path("google-tv.local")
        assert "google-tv" in path


class TestKeycodes:
    def test_all_keycodes_are_positive_integers(self):
        for name, code in KEYCODES.items():
            assert isinstance(name, str)
            assert isinstance(code, int)
            assert code > 0

    def test_common_keys_present(self):
        required = {"POWER", "BACK", "HOME", "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT", "DPAD_CENTER",
                     "VOLUME_UP", "VOLUME_DOWN", "VOLUME_MUTE", "MENU"}
        assert required.issubset(KEYCODES.keys())

    def test_no_duplicate_codes(self):
        codes = list(KEYCODES.values())
        assert len(codes) == len(set(codes)), "Duplicate key codes found"


class TestMessageSerialization:
    def test_pairing_message_roundtrip(self):
        original = PairingMessage()
        original.status = PairingMessage.PAIRING_CODE
        original.pairing_code = 1234
        original.service_name = b"test-client"

        data = original.SerializeToString()
        parsed = PairingMessage()
        parsed.ParseFromString(data)

        assert parsed.status == PairingMessage.PAIRING_CODE
        assert parsed.pairing_code == 1234
        assert parsed.service_name == b"test-client"

    def test_pairing_message_success(self):
        msg = PairingMessage()
        msg.status = PairingMessage.PAIRING_CODE_RESPONSE_SUCCESS
        assert msg.status == 31

    def test_pairing_message_failure(self):
        msg = PairingMessage()
        msg.status = PairingMessage.PAIRING_CODE_RESPONSE_FAILURE
        assert msg.status == 32

    def test_remote_message_roundtrip(self):
        original = RemoteMessage()
        original.status = RemoteMessage.KEY_DOWN
        original.key_code = 19  # DPAD_UP

        data = original.SerializeToString()
        parsed = RemoteMessage()
        parsed.ParseFromString(data)

        assert parsed.status == RemoteMessage.KEY_DOWN
        assert parsed.key_code == 19

    def test_remote_message_key_up(self):
        msg = RemoteMessage()
        msg.status = RemoteMessage.KEY_UP
        msg.key_code = 3
        assert msg.key_code == 3
        assert msg.status == RemoteMessage.KEY_UP


class TestSendRecvMessage:
    def test_send_message_writes_length_prefix(self):
        mock_sock = MagicMock()
        msg = PairingMessage()
        msg.status = PairingMessage.PAIRING_CODE
        msg.pairing_code = 1234

        _send_message(mock_sock, msg)

        assert mock_sock.sendall.called
        args = mock_sock.sendall.call_args[0][0]
        # First 4 bytes = length, rest = protobuf data
        length = struct.unpack("!I", args[:4])[0]
        assert length == len(args) - 4

    def test_recv_exact_reads_full_data(self):
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [b"AB", b"CD"]

        result = _recv_exact(mock_sock, 4)
        assert result == b"ABCD"

    def test_recv_exact_returns_none_on_empty(self):
        mock_sock = MagicMock()
        mock_sock.recv.return_value = b""

        result = _recv_exact(mock_sock, 4)
        assert result is None

    def test_recv_message_parses_correctly(self):
        msg = PairingMessage()
        msg.status = PairingMessage.PAIRING_CODE
        msg.pairing_code = 4321
        data = msg.SerializeToString()

        framed = bytes([len(data)]) + data

        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [framed[:1], framed[1:]]

        result = _recv_message(mock_sock, PairingMessage)
        assert result is not None
        assert result.status == PairingMessage.PAIRING_CODE
        assert result.pairing_code == 4321

    def test_recv_message_returns_none_on_empty_header(self):
        mock_sock = MagicMock()
        mock_sock.recv.return_value = b""

        result = _recv_message(mock_sock, PairingMessage)
        assert result is None


class TestTVClient:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cert_patcher = patch("tv_remote.protocol.CERT_DIR", self.temp_dir)
        self.cert_patcher.start()

    def teardown_method(self):
        self.cert_patcher.stop()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_sets_host_and_ports(self):
        client = TVClient("192.168.1.100")
        assert client.host == "192.168.1.100"
        assert client.port == 6466
        assert client.pairing_port == 6467

    def test_init_with_custom_ports(self):
        client = TVClient("192.168.1.100", port=5000, pairing_port=5001)
        assert client.port == 5000
        assert client.pairing_port == 5001

    @patch("tv_remote.protocol._create_tls_connection")
    @patch("tv_remote.protocol._send_message")
    def test_pair_sends_request_then_waits(self, mock_send, mock_tls):
        import socket
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.recv.side_effect = socket.timeout("timed out")
        mock_sock.settimeout = MagicMock()
        mock_tls.return_value = mock_sock

        client = TVClient("192.168.1.100")
        result = client.pair(connect_timeout=1, response_timeout=1)

        assert result == ("no_response", None)
        send_call = mock_send.call_args[0][1]
        assert send_call.status == PairingMessage.PAIRING_REQUEST

    @patch("tv_remote.protocol._create_tls_connection")
    @patch("tv_remote.protocol._recv_message")
    @patch("tv_remote.protocol._send_message")
    def test_pair_with_code_confirms(self, mock_send, mock_recv, mock_tls):
        mock_tls.return_value = MagicMock()

        options_msg = PairingMessage()
        options_msg.status = PairingMessage.OPTIONS

        code_req = PairingMessage()
        code_req.status = PairingMessage.PAIRING_CODE_REQUIRED
        code_req.pairing_code = 5678

        mock_recv.side_effect = [options_msg, code_req]

        client = TVClient("192.168.1.100")
        result = client.pair(connect_timeout=1, response_timeout=3)

        assert result == ("confirm", 5678)

    @patch("tv_remote.protocol._create_tls_connection")
    @patch("tv_remote.protocol._recv_message")
    @patch("tv_remote.protocol._send_message")
    def test_pair_with_code_sends_confirmation(self, mock_send, mock_recv, mock_tls):
        mock_tls.return_value = MagicMock()

        options_msg = PairingMessage()
        options_msg.status = PairingMessage.OPTIONS

        code_req = PairingMessage()
        code_req.status = PairingMessage.PAIRING_CODE_REQUIRED
        code_req.pairing_code = 5678

        success = PairingMessage()
        success.status = PairingMessage.PAIRING_CODE_RESPONSE_SUCCESS

        mock_recv.side_effect = [options_msg, code_req, success]

        client = TVClient("192.168.1.100")
        result = client.pair(pairing_code=5678, connect_timeout=1, response_timeout=3)

        assert result == (True, None)

    @patch("tv_remote.protocol._create_tls_connection")
    @patch("tv_remote.protocol._recv_message")
    @patch("tv_remote.protocol._send_message")
    def test_pair_rejected(self, mock_send, mock_recv, mock_tls):
        mock_tls.return_value = MagicMock()

        fail = PairingMessage()
        fail.status = PairingMessage.PAIRING_CODE_RESPONSE_FAILURE

        mock_recv.side_effect = [fail]

        client = TVClient("192.168.1.100")
        result = client.pair(pairing_code=1234, connect_timeout=1, response_timeout=3)

        assert result == (False, None)

    @patch("tv_remote.protocol._create_tls_connection")
    @patch("tv_remote.protocol._recv_message")
    @patch("tv_remote.protocol._send_message")
    def test_pair_connection_closed_is_no_response(self, mock_send, mock_recv, mock_tls):
        mock_tls.return_value = MagicMock()
        mock_recv.return_value = None  # Connection closed without any protocol message

        client = TVClient("192.168.1.100")
        result = client.pair(connect_timeout=1, response_timeout=3)

        assert result == ("no_response", None), "Connection closed without protocol response should trigger retry"

    @patch("tv_remote.protocol._create_tls_connection")
    def test_send_key_raises_if_not_connected(self, mock_tls):
        client = TVClient("192.168.1.100")
        with pytest.raises(RuntimeError, match="Not connected"):
            client.send_key(19)

    @patch("tv_remote.protocol._create_tls_connection")
    @patch("tv_remote.protocol._send_message")
    def test_send_key_sends_down_and_up(self, mock_send, mock_tls):
        mock_sock = MagicMock()
        mock_tls.return_value = mock_sock

        client = TVClient("192.168.1.100")
        client.connect(timeout=1)
        client.send_key(19)

        assert mock_send.call_count == 2
        first_msg = mock_send.call_args_list[0][0][1]
        second_msg = mock_send.call_args_list[1][0][1]

        assert first_msg.status == RemoteMessage.KEY_DOWN
        assert first_msg.key_code == 19
        assert second_msg.status == RemoteMessage.KEY_UP
        assert second_msg.key_code == 19

    def test_close_is_idempotent(self):
        client = TVClient("192.168.1.100")
        client.close()
        client.close()  # Should not raise
