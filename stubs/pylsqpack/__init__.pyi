from typing import List, Tuple

Headers = List[Tuple[bytes, bytes]]

class DecompressionFailed(Exception): ...
class DecoderStreamError(Exception): ...
class EncoderStreamError(Exception): ...
class StreamBlocked(Exception): ...

class Decoder:
    def __init__(self, max_table_capacity: int, blocked_streams: int) -> None: ...
    def feed_encoder(self, data: bytes) -> List[int]: ...
    def feed_header(self, stream_id: int, data: bytes) -> Tuple[bytes, Headers]: ...
    def resume_header(self, stream_id: int) -> Tuple[bytes, Headers]: ...

class Encoder:
    def apply_settings(
        self, max_table_capacity: int, blocked_streams: int
    ) -> bytes: ...
    def encode(self, stream_id: int, headers: Headers) -> Tuple[bytes, bytes]: ...
    def feed_decoder(self, data: bytes) -> None: ...
