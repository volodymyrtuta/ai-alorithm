import binascii

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .packet import is_long_header
from .tls import (CipherSuite, cipher_suite_aead, cipher_suite_hash,
                  hkdf_expand_label, hkdf_extract)

INITIAL_CIPHER_SUITE = CipherSuite.AES_128_GCM_SHA256
INITIAL_SALT = binascii.unhexlify('ef4fb0abb47470c41befcf8031334fae485e09a0')
MAX_PN_SIZE = 4
SAMPLE_SIZE = 16


def derive_key_iv_hp(cipher_suite, secret):
    algorithm = cipher_suite_hash(cipher_suite)
    if cipher_suite in [
        CipherSuite.AES_256_GCM_SHA384,
        CipherSuite.CHACHA20_POLY1305_SHA256,
    ]:
        key_size = 32
    else:
        key_size = 16
    return (
        hkdf_expand_label(algorithm, secret, b'quic key', b'', key_size),
        hkdf_expand_label(algorithm, secret, b'quic iv', b'', 12),
        hkdf_expand_label(algorithm, secret, b'quic hp', b'', key_size)
    )


class CryptoContext:
    def __init__(self):
        self.teardown()

    def decrypt_packet(self, packet, encrypted_offset):
        packet = bytearray(packet)

        # header protection
        sample_offset = encrypted_offset + MAX_PN_SIZE
        sample = packet[sample_offset:sample_offset + SAMPLE_SIZE]
        mask = self.header_protection_mask(sample)

        if is_long_header(packet[0]):
            # long header
            packet[0] ^= (mask[0] & 0x0f)
        else:
            # short header
            packet[0] ^= (mask[0] & 0x1f)

        pn_length = (packet[0] & 0x03) + 1
        for i in range(pn_length):
            packet[encrypted_offset + i] ^= mask[1 + i]
        pn = packet[encrypted_offset:encrypted_offset + pn_length]
        plain_header = bytes(packet[:encrypted_offset + pn_length])

        # payload protection
        nonce = bytearray(len(self.iv) - pn_length) + bytearray(pn)
        for i in range(len(self.iv)):
            nonce[i] ^= self.iv[i]
        try:
            payload = self.aead.decrypt(nonce, bytes(packet[encrypted_offset + pn_length:]),
                                        plain_header)
        except InvalidTag:
            raise CryptoError('Payload decryption failed')

        # packet number
        packet_number = 0
        for i in range(pn_length):
            packet_number = (packet_number << 8) | pn[i]

        return plain_header, payload, packet_number

    def encrypt_packet(self, plain_header, plain_payload):
        pn_length = (plain_header[0] & 0x03) + 1
        pn_offset = len(plain_header) - pn_length
        pn = plain_header[pn_offset:pn_offset + pn_length]

        # payload protection
        nonce = bytearray(len(self.iv) - pn_length) + bytearray(pn)
        for i in range(len(self.iv)):
            nonce[i] ^= self.iv[i]
        protected_payload = self.aead.encrypt(nonce, plain_payload, plain_header)

        # header protection
        sample_offset = MAX_PN_SIZE - pn_length
        sample = protected_payload[sample_offset:sample_offset + SAMPLE_SIZE]
        mask = self.header_protection_mask(sample)

        packet = bytearray(plain_header + protected_payload)
        if is_long_header(packet[0]):
            # long header
            packet[0] ^= (mask[0] & 0x0f)
        else:
            # short header
            packet[0] ^= (mask[0] & 0x1f)

        for i in range(pn_length):
            packet[pn_offset + i] ^= mask[1 + i]

        return packet

    def header_protection_mask(self, sample):
        if self.cipher_suite == CipherSuite.CHACHA20_POLY1305_SHA256:
            encryptor = Cipher(
                algorithms.ChaCha20(key=self.hp, nonce=sample),
                mode=None,
                backend=default_backend()).encryptor()
            buf = bytearray(5)
            encryptor.update_into(bytes(5), buf)
            return bytes(buf)
        else:
            encryptor = Cipher(
                algorithms.AES(self.hp),
                mode=modes.ECB(),
                backend=default_backend()).encryptor()
            buf = bytearray(31)
            encryptor.update_into(sample, buf)
            return buf[:5]

    def is_valid(self):
        return self.aead is not None

    def setup(self, cipher_suite, secret):
        assert cipher_suite in [
            CipherSuite.AES_128_GCM_SHA256,
            CipherSuite.AES_256_GCM_SHA384,
            CipherSuite.CHACHA20_POLY1305_SHA256,
        ], 'unsupported cipher suite'
        key, self.iv, self.hp = derive_key_iv_hp(cipher_suite, secret)
        self.aead = cipher_suite_aead(cipher_suite, key)
        self.cipher_suite = cipher_suite

    def teardown(self):
        self.aead = None
        self.cipher_suite = None
        self.hp = None
        self.iv = None


class CryptoError(Exception):
    pass


class CryptoPair:
    def __init__(self):
        self.aead_tag_size = 16
        self.recv = CryptoContext()
        self.send = CryptoContext()

    def decrypt_packet(self, packet, encrypted_offset):
        return self.recv.decrypt_packet(packet, encrypted_offset)

    def encrypt_packet(self, plain_header, plain_payload):
        return self.send.encrypt_packet(plain_header, plain_payload)

    def setup_initial(self, cid, is_client):
        if is_client:
            recv_label, send_label = b'server in', b'client in'
        else:
            recv_label, send_label = b'client in', b'server in'

        algorithm = cipher_suite_hash(INITIAL_CIPHER_SUITE)
        initial_secret = hkdf_extract(algorithm, INITIAL_SALT, cid)
        self.recv.setup(
            INITIAL_CIPHER_SUITE,
            hkdf_expand_label(algorithm, initial_secret, recv_label, b'', algorithm.digest_size))
        self.send.setup(
            INITIAL_CIPHER_SUITE,
            hkdf_expand_label(algorithm, initial_secret, send_label, b'', algorithm.digest_size))
