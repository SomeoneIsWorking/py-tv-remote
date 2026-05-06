import os
import ssl
import socket
import struct
import threading
import datetime

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from .remote_pb2 import PairingMessage, RemoteMessage

CERT_DIR = os.path.expanduser("~/.config/tv_remote/certs")

KEYCODES = {
    "POWER": 26,
    "BACK": 4,
    "HOME": 3,
    "MENU": 82,
    "DPAD_UP": 19,
    "DPAD_DOWN": 20,
    "DPAD_LEFT": 21,
    "DPAD_RIGHT": 22,
    "DPAD_CENTER": 23,
    "VOLUME_UP": 24,
    "VOLUME_DOWN": 25,
    "VOLUME_MUTE": 164,
    "MEDIA_PLAY_PAUSE": 85,
    "MEDIA_STOP": 86,
    "MEDIA_NEXT": 87,
    "MEDIA_PREVIOUS": 88,
    "ENTER": 66,
    "INFO": 165,
    "CHANNEL_UP": 166,
    "CHANNEL_DOWN": 167,
    "GUIDE": 168,
    "CAPTIONS": 249,
}


def _ensure_cert_dir():
    os.makedirs(CERT_DIR, exist_ok=True)


def _host_cert_path(host):
    safe = host.replace(".", "_").replace(":", "_")
    return os.path.join(CERT_DIR, f"{safe}.pem")


def _host_key_path(host):
    safe = host.replace(".", "_").replace(":", "_")
    return os.path.join(CERT_DIR, f"{safe}.key")


def has_cert(host):
    return os.path.exists(_host_cert_path(host)) and os.path.exists(_host_key_path(host))


def generate_cert(host):
    _ensure_cert_dir()
    cert_path = _host_cert_path(host)
    key_path = _host_key_path(host)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.datetime.now(datetime.timezone.utc)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, f"TV Remote Client - {host}"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )

    with open(key_path, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    return cert_path, key_path


def _create_tls_connection(host, port, cert_path, key_path, timeout=5):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_cert_chain(cert_path, key_path)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    sock = socket.create_connection((host, port), timeout=timeout)
    tls_sock = ctx.wrap_socket(sock, server_hostname=host)
    return tls_sock


def _send_message(sock, msg):
    data = msg.SerializeToString()
    sock.sendall(struct.pack("!I", len(data)) + data)


def _recv_exact(sock, n):
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data.extend(chunk)
    return bytes(data)


def _recv_message(sock, msg_class):
    header = _recv_exact(sock, 1)
    if header is None:
        return None
    length = header[0]
    if length == 0:
        return None
    data = _recv_exact(sock, length)
    if data is None:
        return None
    msg = msg_class()
    msg.ParseFromString(data)
    return msg


class TVClient:
    def __init__(self, host, port=6466, pairing_port=6467):
        self.host = host
        self.port = port
        self.pairing_port = pairing_port
        self._sock = None
        self._lock = threading.Lock()
        self._connected = False

    def _get_certs(self):
        if has_cert(self.host):
            return _host_cert_path(self.host), _host_key_path(self.host)
        return generate_cert(self.host)

    def pair(self, pairing_code=None, connect_timeout=5, response_timeout=8):
        cert_path, key_path = self._get_certs()
        sock = _create_tls_connection(self.host, self.pairing_port, cert_path, key_path, connect_timeout)

        got_protocol_response = False

        try:
            sock.settimeout(response_timeout)

            req = PairingMessage()
            req.status = PairingMessage.PAIRING_REQUEST
            req.service_name = b"tv-remote-app"
            req.client_name = b"TV Remote"
            _send_message(sock, req)

            while True:
                msg = _recv_message(sock, PairingMessage)
                if msg is None:
                    break

                got_protocol_response = True

                if msg.status == PairingMessage.OPTIONS:
                    resp = PairingMessage()
                    resp.status = PairingMessage.OPTIONS_RESPONSE
                    _send_message(sock, resp)

                elif msg.status in (PairingMessage.PAIRING_CODE, PairingMessage.PAIRING_CODE_REQUIRED):
                    code = msg.pairing_code
                    if pairing_code is not None:
                        resp = PairingMessage()
                        resp.status = PairingMessage.PAIRING_CODE
                        resp.pairing_code = pairing_code
                        _send_message(sock, resp)
                        sock.close()
                        return (True, None)
                    else:
                        sock.close()
                        return ("confirm", code)

                elif msg.status == PairingMessage.PAIRING_CODE_RESPONSE_SUCCESS:
                    sock.close()
                    return (True, None)

                elif msg.status == PairingMessage.PAIRING_CODE_RESPONSE_FAILURE:
                    sock.close()
                    return (False, None)

        except socket.timeout:
            sock.close()
            if got_protocol_response:
                return (True, None)
            return ("no_response", None)
        except Exception:
            sock.close()
            raise

        sock.close()
        if got_protocol_response:
            return (True, None)
        return ("no_response", None)

    def connect(self, timeout=5):
        cert_path, key_path = self._get_certs()
        sock = _create_tls_connection(self.host, self.port, cert_path, key_path, timeout)
        self._sock = sock
        self._connected = True
        return True

    def send_key(self, key_code):
        if not self._connected or self._sock is None:
            raise RuntimeError("Not connected")
        with self._lock:
            msg = RemoteMessage()
            msg.status = RemoteMessage.KEY_DOWN
            msg.key_code = key_code
            _send_message(self._sock, msg)

            msg = RemoteMessage()
            msg.status = RemoteMessage.KEY_UP
            msg.key_code = key_code
            _send_message(self._sock, msg)

    def close(self):
        self._connected = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
