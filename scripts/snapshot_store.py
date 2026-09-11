"""Validate complete snapshots before replacing the last successful output."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import tempfile

class SnapshotRejected(RuntimeError):
    pass

@contextlib.contextmanager
def publishing_lock(output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.with_suffix(output.suffix + '.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SnapshotRejected('다른 수집 작업이 실행 중입니다. 기존 파일을 유지합니다.') from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)

def _atomic_bytes(path, content):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

def publish_snapshot(output, payload, *, allow_shrink=False):
    output = Path(output)
    orders = payload.get('orders')
    products = payload.get('products')
    if not isinstance(orders, list) or not orders or not isinstance(products, list) or not products:
        raise SnapshotRejected('발주서 또는 상품이 비어 있습니다. 기존 파일을 유지합니다.')
    if payload.get('errors'):
        raise SnapshotRejected(f"발주서 {len(payload['errors'])}개 파싱 실패. 불완전한 결과를 발행하지 않습니다.")
    if payload.get('count') != len(orders) or payload.get('product_count') != len(products):
        raise SnapshotRejected('스냅샷 건수와 실제 데이터가 일치하지 않습니다.')
    old_bytes = output.read_bytes() if output.exists() else None
    old = None
    if old_bytes is not None:
        try:
            old = json.loads(old_bytes)
        except (ValueError, UnicodeDecodeError) as error:
            raise SnapshotRejected('기존 파일이 손상되었습니다. 마지막 정상본을 먼저 확인하세요.') from error
    if old and not allow_shrink:
        for key in ('orders', 'products'):
            previous = old.get(key, [])
            if isinstance(previous, list) and len(previous) >= 10 and len(payload[key]) < len(previous) * 0.8:
                raise SnapshotRejected(f'{key} 건수가 20% 이상 줄었습니다. 원본 파일·수집 범위를 확인하세요.')
    encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
    output.parent.mkdir(parents=True, exist_ok=True)
    if old_bytes is not None:
        _atomic_bytes(output.with_suffix(output.suffix + '.last-good'), old_bytes)
    _atomic_bytes(output, encoded)
    # Persist the directory entries as well as file content.
    directory = os.open(output.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
