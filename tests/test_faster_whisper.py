from voice.faster_whisper import _is_cuda_runtime_error


def test_cuda_runtime_error_detects_missing_cublas():
    assert _is_cuda_runtime_error(RuntimeError("Library cublas64_12.dll is not found or cannot be loaded"))


def test_cuda_runtime_error_ignores_regular_errors():
    assert not _is_cuda_runtime_error(RuntimeError("audio file not found"))
