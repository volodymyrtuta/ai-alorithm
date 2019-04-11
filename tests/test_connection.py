import io
from unittest import TestCase

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from aioquic.connection import QuicConnection
from aioquic.packet import QuicProtocolVersion

from .utils import load

SERVER_CERTIFICATE = x509.load_pem_x509_certificate(
    load('ssl_cert.pem'), backend=default_backend())
SERVER_PRIVATE_KEY = serialization.load_pem_private_key(
    load('ssl_key.pem'), password=None, backend=default_backend())


class QuicConnectionTest(TestCase):
    def _test_connect_with_version(self, version):
        client = QuicConnection(
            is_client=True)
        client.supported_versions = [version]
        client.version = version

        server = QuicConnection(
            is_client=False,
            certificate=SERVER_CERTIFICATE,
            private_key=SERVER_PRIVATE_KEY)
        server.supported_versions = [version]
        server.version = version

        # perform handshake
        client.connection_made()
        for datagram in client.pending_datagrams():
            server.datagram_received(datagram)

        for datagram in server.pending_datagrams():
            client.datagram_received(datagram)

        for datagram in client.pending_datagrams():
            server.datagram_received(datagram)

        for datagram in server.pending_datagrams():
            client.datagram_received(datagram)

        # send data over stream
        client_stream = client.create_stream()
        client_stream.push_data(b'ping')

        for datagram in client.pending_datagrams():
            server.datagram_received(datagram)

        for datagram in server.pending_datagrams():
            client.datagram_received(datagram)

        server_stream = server.streams[0]
        self.assertEqual(server_stream.pull_data(), b'ping')

    def test_connect_draft_17(self):
        self._test_connect_with_version(QuicProtocolVersion.DRAFT_17)

    def test_connect_draft_18(self):
        self._test_connect_with_version(QuicProtocolVersion.DRAFT_18)

    def test_connect_draft_19(self):
        self._test_connect_with_version(QuicProtocolVersion.DRAFT_19)

    def test_connect_with_log(self):
        client_log_file = io.StringIO()
        client = QuicConnection(
            is_client=True,
            secrets_log_file=client_log_file)
        server_log_file = io.StringIO()
        server = QuicConnection(
            is_client=False,
            certificate=SERVER_CERTIFICATE,
            private_key=SERVER_PRIVATE_KEY,
            secrets_log_file=server_log_file)

        # perform handshake
        client.connection_made()
        for datagram in client.pending_datagrams():
            server.datagram_received(datagram)

        for datagram in server.pending_datagrams():
            client.datagram_received(datagram)

        for datagram in client.pending_datagrams():
            server.datagram_received(datagram)

        for datagram in server.pending_datagrams():
            client.datagram_received(datagram)

        # check secrets were logged
        client_log = client_log_file.getvalue()
        server_log = server_log_file.getvalue()
        self.assertEqual(client_log, server_log)
        labels = []
        for line in client_log.splitlines():
            labels.append(line.split()[0])
        self.assertEqual(labels, [
            'QUIC_SERVER_HANDSHAKE_TRAFFIC_SECRET',
            'QUIC_CLIENT_HANDSHAKE_TRAFFIC_SECRET',
            'QUIC_SERVER_TRAFFIC_SECRET_0',
            'QUIC_CLIENT_TRAFFIC_SECRET_0'])

    def test_create_stream(self):
        client = QuicConnection(is_client=True)
        server = QuicConnection(
            is_client=False,
            certificate=SERVER_CERTIFICATE,
            private_key=SERVER_PRIVATE_KEY)

        # client
        stream = client.create_stream()
        self.assertEqual(stream.stream_id, 0)

        stream = client.create_stream()
        self.assertEqual(stream.stream_id, 4)

        stream = client.create_stream(is_unidirectional=True)
        self.assertEqual(stream.stream_id, 2)

        stream = client.create_stream(is_unidirectional=True)
        self.assertEqual(stream.stream_id, 6)

        # server
        stream = server.create_stream()
        self.assertEqual(stream.stream_id, 1)

        stream = server.create_stream()
        self.assertEqual(stream.stream_id, 5)

        stream = server.create_stream(is_unidirectional=True)
        self.assertEqual(stream.stream_id, 3)

        stream = server.create_stream(is_unidirectional=True)
        self.assertEqual(stream.stream_id, 7)

    def test_version_negotiation_needed(self):
        client = QuicConnection(
            is_client=True)

        datagrams = 0
        client.connection_made()
        for datagram in client.pending_datagrams():
            datagrams += 1
        self.assertEqual(datagrams, 1)

        client.datagram_received(load('version_negotiation.bin'))
        for datagram in client.pending_datagrams():
            datagrams += 1
        self.assertEqual(datagrams, 2)
