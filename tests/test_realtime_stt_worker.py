from voice.realtime_stt_worker import _append_audio_chunk, _input_device_index


class FakeAudioArray:
    def __init__(self, data: bytes):
        self.data = data

    def tobytes(self):
        return self.data


def test_append_audio_chunk_accepts_byte_like_values():
    chunks = []

    _append_audio_chunk(chunks, b"one")
    _append_audio_chunk(chunks, bytearray(b"two"))
    _append_audio_chunk(chunks, memoryview(b"three"))
    _append_audio_chunk(chunks, FakeAudioArray(b"four"))
    _append_audio_chunk(chunks, None)

    assert chunks == [b"one", b"two", b"three", b"four"]


def test_input_device_index_ignores_default(tmp_path, monkeypatch):
    config = tmp_path / "apolo.json"
    config.write_text('{"audio": {"input_device": "default"}}', encoding="utf-8")
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    assert _input_device_index() is None
