import binascii
from unittest import TestCase

from aioquic import tls
from aioquic.tls import (Buffer, BufferReadError, Certificate,
                         CertificateVerify, ClientHello, Context,
                         EncryptedExtensions, Finished, ServerHello, State,
                         pull_block, pull_bytes, pull_certificate,
                         pull_certificate_verify, pull_client_hello,
                         pull_encrypted_extensions, pull_finished,
                         pull_server_hello, pull_uint8, pull_uint16,
                         pull_uint32, pull_uint64, push_certificate,
                         push_certificate_verify, push_client_hello,
                         push_encrypted_extensions, push_finished,
                         push_server_hello)

from .utils import load

CERTIFICATE_DATA = load('tls_certificate.bin')[11:-2]
CERTIFICATE_VERIFY_SIGNATURE = load('tls_certificate_verify.bin')[-384:]

CLIENT_QUIC_TRANSPORT_PARAMETERS = binascii.unhexlify(
    b'ff0000110031000500048010000000060004801000000007000480100000000'
    b'4000481000000000100024258000800024064000a00010a')

SERVER_QUIC_TRANSPORT_PARAMETERS = binascii.unhexlify(
    b'ff00001104ff000011004500050004801000000006000480100000000700048'
    b'010000000040004810000000001000242580002001000000000000000000000'
    b'000000000000000800024064000a00010a')


class BufferTest(TestCase):
    def test_pull_block_truncated(self):
        buf = Buffer(capacity=0)
        with self.assertRaises(BufferReadError):
            with pull_block(buf, 1):
                pass

    def test_pull_bytes_truncated(self):
        buf = Buffer(capacity=0)
        with self.assertRaises(BufferReadError):
            pull_bytes(buf, 2)

    def test_pull_uint8_truncated(self):
        buf = Buffer(capacity=0)
        with self.assertRaises(BufferReadError):
            pull_uint8(buf)

    def test_pull_uint16_truncated(self):
        buf = Buffer(capacity=1)
        with self.assertRaises(BufferReadError):
            pull_uint16(buf)

    def test_pull_uint32_truncated(self):
        buf = Buffer(capacity=3)
        with self.assertRaises(BufferReadError):
            pull_uint32(buf)

    def test_pull_uint64_truncated(self):
        buf = Buffer(capacity=7)
        with self.assertRaises(BufferReadError):
            pull_uint64(buf)

    def test_seek(self):
        buf = Buffer(data=b'01234567')
        self.assertFalse(buf.eof())
        self.assertEqual(buf.tell(), 0)

        buf.seek(4)
        self.assertFalse(buf.eof())
        self.assertEqual(buf.tell(), 4)

        buf.seek(8)
        self.assertTrue(buf.eof())
        self.assertEqual(buf.tell(), 8)


class ContextTest(TestCase):
    def test_handshake(self):
        client = Context(is_client=True)
        client.handshake_extensions = [
            (tls.ExtensionType.QUIC_TRANSPORT_PARAMETERS, CLIENT_QUIC_TRANSPORT_PARAMETERS),
        ]
        self.assertEqual(client.state, State.CLIENT_HANDSHAKE_START)

        server = Context(is_client=False)
        server.certificate = CERTIFICATE_DATA
        server.handshake_extensions = [
            (tls.ExtensionType.QUIC_TRANSPORT_PARAMETERS, SERVER_QUIC_TRANSPORT_PARAMETERS),
        ]
        self.assertEqual(server.state, State.SERVER_EXPECT_CLIENT_HELLO)

        # send client hello
        client_buf = Buffer(capacity=512)
        client.handle_message(b'', client_buf)
        self.assertEqual(client.state, State.CLIENT_EXPECT_SERVER_HELLO)
        self.assertEqual(client_buf.tell(), 254)
        server_input = client_buf.data
        client_buf.seek(0)

        # handle client hello
        # send server hello, encrypted extensions, certificate
        server_buf = Buffer(capacity=2048)
        server.handle_message(server_input, server_buf)
        self.assertEqual(server.state, State.SERVER_EXPECT_FINISHED)
        self.assertEqual(server_buf.tell(), 155 + 90 + 1538)
        client_input = server_buf.data
        server_buf.seek(0)

        # handle server hello, encrypted extensions, certificate
        client.handle_message(client_input, client_buf)
        self.assertEqual(client.state, State.CLIENT_EXPECT_CERTIFICATE_VERIFY)
        self.assertEqual(client_buf.tell(), 0)

        # check keys match
        self.assertEqual(client.dec_key, server.enc_key)
        self.assertEqual(client.enc_key, server.dec_key)


class TlsTest(TestCase):
    def test_pull_client_hello(self):
        buf = Buffer(data=load('tls_client_hello.bin'))
        hello = pull_client_hello(buf)
        self.assertTrue(buf.eof())

        self.assertEqual(
            hello.random,
            binascii.unhexlify(
                '18b2b23bf3e44b5d52ccfe7aecbc5ff14eadc3d349fabf804d71f165ae76e7d5'))
        self.assertEqual(
            hello.session_id,
            binascii.unhexlify(
                '9aee82a2d186c1cb32a329d9dcfe004a1a438ad0485a53c6bfcf55c132a23235'))
        self.assertEqual(hello.cipher_suites, [
            tls.CipherSuite.AES_256_GCM_SHA384,
            tls.CipherSuite.AES_128_GCM_SHA256,
            tls.CipherSuite.CHACHA20_POLY1305_SHA256,
        ])
        self.assertEqual(hello.compression_methods, [
            tls.CompressionMethod.NULL,
        ])

        # extensions
        self.assertEqual(hello.key_exchange_modes, [
            tls.KeyExchangeMode.PSK_DHE_KE,
        ])
        self.assertEqual(hello.key_share, [
            (
                tls.Group.SECP256R1,
                binascii.unhexlify(
                    '047bfea344467535054263b75def60cffa82405a211b68d1eb8d1d944e67aef8'
                    '93c7665a5473d032cfaf22a73da28eb4aacae0017ed12557b5791f98a1e84f15'
                    'b0'),
            )
        ])
        self.assertEqual(hello.signature_algorithms, [
            tls.SignatureAlgorithm.RSA_PSS_RSAE_SHA256,
            tls.SignatureAlgorithm.ECDSA_SECP256R1_SHA256,
            tls.SignatureAlgorithm.RSA_PKCS1_SHA256,
            tls.SignatureAlgorithm.RSA_PKCS1_SHA1,
        ])
        self.assertEqual(hello.supported_groups, [
            tls.Group.SECP256R1,
        ])
        self.assertEqual(hello.supported_versions, [
            tls.TLS_VERSION_1_3,
            tls.TLS_VERSION_1_3_DRAFT_28,
            tls.TLS_VERSION_1_3_DRAFT_27,
            tls.TLS_VERSION_1_3_DRAFT_26,
        ])

        self.assertEqual(hello.other_extensions, [
            (tls.ExtensionType.QUIC_TRANSPORT_PARAMETERS, CLIENT_QUIC_TRANSPORT_PARAMETERS),
        ])

    def test_push_client_hello(self):
        hello = ClientHello(
            random=binascii.unhexlify(
                '18b2b23bf3e44b5d52ccfe7aecbc5ff14eadc3d349fabf804d71f165ae76e7d5'),
            session_id=binascii.unhexlify(
                '9aee82a2d186c1cb32a329d9dcfe004a1a438ad0485a53c6bfcf55c132a23235'),
            cipher_suites=[
                tls.CipherSuite.AES_256_GCM_SHA384,
                tls.CipherSuite.AES_128_GCM_SHA256,
                tls.CipherSuite.CHACHA20_POLY1305_SHA256,
            ],
            compression_methods=[
                tls.CompressionMethod.NULL,
            ],

            key_exchange_modes=[
                tls.KeyExchangeMode.PSK_DHE_KE,
            ],
            key_share=[
                (
                    tls.Group.SECP256R1,
                    binascii.unhexlify(
                        '047bfea344467535054263b75def60cffa82405a211b68d1eb8d1d944e67aef8'
                        '93c7665a5473d032cfaf22a73da28eb4aacae0017ed12557b5791f98a1e84f15'
                        'b0'),
                )
            ],
            signature_algorithms=[
                tls.SignatureAlgorithm.RSA_PSS_RSAE_SHA256,
                tls.SignatureAlgorithm.ECDSA_SECP256R1_SHA256,
                tls.SignatureAlgorithm.RSA_PKCS1_SHA256,
                tls.SignatureAlgorithm.RSA_PKCS1_SHA1,
            ],
            supported_groups=[
                tls.Group.SECP256R1,
            ],
            supported_versions=[
                tls.TLS_VERSION_1_3,
                tls.TLS_VERSION_1_3_DRAFT_28,
                tls.TLS_VERSION_1_3_DRAFT_27,
                tls.TLS_VERSION_1_3_DRAFT_26,
            ],

            other_extensions=[
                (tls.ExtensionType.QUIC_TRANSPORT_PARAMETERS, CLIENT_QUIC_TRANSPORT_PARAMETERS),
            ])

        buf = Buffer(1000)
        push_client_hello(buf, hello)
        self.assertEqual(buf.data, load('tls_client_hello.bin'))

    def test_pull_server_hello(self):
        buf = Buffer(data=load('tls_server_hello.bin'))
        hello = pull_server_hello(buf)
        self.assertTrue(buf.eof())

        self.assertEqual(
            hello.random,
            binascii.unhexlify(
                'ada85271d19680c615ea7336519e3fdf6f1e26f3b1075ee1de96ffa8884e8280'))
        self.assertEqual(
            hello.session_id,
            binascii.unhexlify(
                '9aee82a2d186c1cb32a329d9dcfe004a1a438ad0485a53c6bfcf55c132a23235'))
        self.assertEqual(hello.cipher_suite, tls.CipherSuite.AES_256_GCM_SHA384)
        self.assertEqual(hello.compression_method, tls.CompressionMethod.NULL)
        self.assertEqual(hello.key_share, (
            tls.Group.SECP256R1,
            binascii.unhexlify(
                '048b27d0282242d84b7fcc02a9c4f13eca0329e3c7029aa34a33794e6e7ba189'
                '5cca1c503bf0378ac6937c354912116ff3251026bca1958d7f387316c83ae6cf'
                'b2')
        ))
        self.assertEqual(hello.supported_version, tls.TLS_VERSION_1_3)

    def test_push_server_hello(self):
        hello = ServerHello(
            random=binascii.unhexlify(
                'ada85271d19680c615ea7336519e3fdf6f1e26f3b1075ee1de96ffa8884e8280'),
            session_id=binascii.unhexlify(
                '9aee82a2d186c1cb32a329d9dcfe004a1a438ad0485a53c6bfcf55c132a23235'),
            cipher_suite=tls.CipherSuite.AES_256_GCM_SHA384,
            compression_method=tls.CompressionMethod.NULL,

            key_share=(
                tls.Group.SECP256R1,
                binascii.unhexlify(
                    '048b27d0282242d84b7fcc02a9c4f13eca0329e3c7029aa34a33794e6e7ba189'
                    '5cca1c503bf0378ac6937c354912116ff3251026bca1958d7f387316c83ae6cf'
                    'b2'),
            ),
            supported_version=tls.TLS_VERSION_1_3,
        )

        buf = Buffer(1000)
        push_server_hello(buf, hello)
        self.assertEqual(buf.data, load('tls_server_hello.bin'))

    def test_pull_encrypted_extensions(self):
        buf = Buffer(data=load('tls_encrypted_extensions.bin'))
        extensions = pull_encrypted_extensions(buf)
        self.assertIsNotNone(extensions)
        self.assertTrue(buf.eof())

        self.assertEqual(extensions.other_extensions, [
            (tls.ExtensionType.QUIC_TRANSPORT_PARAMETERS, SERVER_QUIC_TRANSPORT_PARAMETERS),
        ])

    def test_push_encrypted_extensions(self):
        extensions = EncryptedExtensions(other_extensions=[
            (tls.ExtensionType.QUIC_TRANSPORT_PARAMETERS, SERVER_QUIC_TRANSPORT_PARAMETERS),
        ])

        buf = Buffer(100)
        push_encrypted_extensions(buf, extensions)
        self.assertEqual(buf.data, load('tls_encrypted_extensions.bin'))

    def test_pull_certificate(self):
        buf = Buffer(data=load('tls_certificate.bin'))
        certificate = pull_certificate(buf)
        self.assertTrue(buf.eof())

        self.assertEqual(certificate.request_context, b'')
        self.assertEqual(certificate.certificates, [(CERTIFICATE_DATA, b'')])

    def test_push_certificate(self):
        certificate = Certificate(
            request_context=b'',
            certificates=[(CERTIFICATE_DATA, b'')])

        buf = Buffer(1600)
        push_certificate(buf, certificate)
        self.assertEqual(buf.data, load('tls_certificate.bin'))

    def test_pull_certificate_verify(self):
        buf = Buffer(data=load('tls_certificate_verify.bin'))
        verify = pull_certificate_verify(buf)
        self.assertTrue(buf.eof())

        self.assertEqual(verify.algorithm, tls.SignatureAlgorithm.RSA_PSS_RSAE_SHA256)
        self.assertEqual(verify.signature, CERTIFICATE_VERIFY_SIGNATURE)

    def test_push_certificate_verify(self):
        verify = CertificateVerify(
            algorithm=tls.SignatureAlgorithm.RSA_PSS_RSAE_SHA256,
            signature=CERTIFICATE_VERIFY_SIGNATURE)

        buf = Buffer(400)
        push_certificate_verify(buf, verify)
        self.assertEqual(buf.data, load('tls_certificate_verify.bin'))

    def test_pull_finished(self):
        buf = Buffer(data=load('tls_finished.bin'))
        finished = pull_finished(buf)
        self.assertTrue(buf.eof())

        self.assertEqual(
            finished.verify_data,
            binascii.unhexlify('f157923234ff9a4921aadb2e0ec7b1a3'
                               '0fce73fb9ec0c4276f9af268f408ec68'))

    def test_push_finished(self):
        finished = Finished(
            verify_data=binascii.unhexlify('f157923234ff9a4921aadb2e0ec7b1a3'
                                           '0fce73fb9ec0c4276f9af268f408ec68'))

        buf = Buffer(128)
        push_finished(buf, finished)
        self.assertEqual(buf.data, load('tls_finished.bin'))
