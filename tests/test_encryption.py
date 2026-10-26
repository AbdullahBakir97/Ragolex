"""Encryption at rest: uploaded files and webhook secrets, with ENCRYPTION_KEYS."""

import hashlib
import hmac
import io

import pytest
from pydantic import ValidationError

from ragolex import cli
from ragolex.core.config import Settings, get_settings
from ragolex.core.encryption import (
    FILE_MAGIC,
    HEADER_BYTES,
    SEGMENT_BYTES,
    EncryptionError,
    KeyRing,
    new_key,
)
from ragolex.storage.file_storage import FileStorage

from .test_ask_api import GUIDE, ask, upload_process_and_index
from .test_upload_scanning import FakeClamd
from .test_webhooks import (  # noqa: F401 - dispatch is a fixture
    RecordingSender,
    create,
    dispatch,
)

TAG_BYTES = 16


def ring(*keys):
    return KeyRing.from_setting(",".join(keys))


def encrypt(keys, data, piece=7_000):
    encryptor = keys.file_encryptor()
    out = [encryptor.header]
    for start in range(0, len(data), piece):
        out.append(encryptor.update(data[start:start + piece]))
    out.append(encryptor.finish())
    return b"".join(out)


def decrypt(keys, sealed):
    return b"".join(keys.decrypt_stream(io.BytesIO(sealed)))


@pytest.fixture
def encryption_on(monkeypatch):
    """The app with a key; returns it."""
    key = new_key()
    monkeypatch.setenv("ENCRYPTION_KEYS", key)
    get_settings.cache_clear()
    return key


def use_keys(monkeypatch, *keys):
    monkeypatch.setenv("ENCRYPTION_KEYS", ",".join(keys))
    get_settings.cache_clear()


def stored_files(files_dir):
    return [path for path in files_dir.rglob("*") if path.is_file()]


# The cipher


def test_values_decrypt_with_their_key_and_old_keys_still_decrypt():
    old, new = new_key(), new_key()
    sealed = ring(old).encrypt_value("whsec_abc")

    assert sealed.startswith("enc:v1:") and "whsec_abc" not in sealed
    assert ring(old).decrypt_value(sealed) == "whsec_abc"
    assert ring(new, old).decrypt_value(sealed) == "whsec_abc"
    # Encrypting twice gives different text: every value has its own nonce.
    assert ring(old).encrypt_value("whsec_abc") != sealed
    # A value stored before there were keys is read as it is.
    assert ring(new).decrypt_value("whsec_plain") == "whsec_plain"
    with pytest.raises(EncryptionError, match="not in ENCRYPTION_KEYS"):
        ring(new).decrypt_value(sealed)


def test_a_changed_value_does_not_decrypt():
    keys = ring(new_key())
    sealed = keys.encrypt_value("whsec_abc")
    changed = sealed[:-2] + ("A" if sealed[-2] != "A" else "B") + sealed[-1]

    with pytest.raises(EncryptionError, match="could not be decrypted"):
        keys.decrypt_value(changed)


@pytest.mark.parametrize("size", [0, 1, SEGMENT_BYTES - 1, SEGMENT_BYTES, SEGMENT_BYTES + 1,
                                  3 * SEGMENT_BYTES + 5])
def test_files_of_any_size_come_back_as_they_were(size):
    keys = ring(new_key())
    data = bytes(range(256)) * (size // 256) + bytes(size % 256)

    sealed = encrypt(keys, data)

    assert sealed.startswith(FILE_MAGIC)
    segments = max(1, -(-size // SEGMENT_BYTES))
    assert len(sealed) == HEADER_BYTES + size + segments * TAG_BYTES
    assert decrypt(keys, sealed) == data


def test_a_file_cut_short_or_changed_does_not_decrypt():
    keys = ring(new_key())
    sealed = encrypt(keys, b"x" * (2 * SEGMENT_BYTES + 10))
    first_segment_only = sealed[:HEADER_BYTES + SEGMENT_BYTES + TAG_BYTES]
    flipped = bytearray(sealed)
    flipped[HEADER_BYTES + 100] ^= 1

    # Cut at a segment's end, the rest would still decrypt: the last segment is marked.
    with pytest.raises(EncryptionError, match="changed or cut short"):
        decrypt(keys, first_segment_only)
    with pytest.raises(EncryptionError, match="changed or cut short"):
        decrypt(keys, bytes(flipped))
    with pytest.raises(EncryptionError, match="not in ENCRYPTION_KEYS"):
        decrypt(ring(new_key()), sealed)


def test_keys_must_be_32_bytes_of_base64_and_are_never_shown():
    assert Settings(ENCRYPTION_KEYS="").encryption_keys is None
    assert Settings(ENCRYPTION_KEYS=f" {new_key()} , {new_key()} ").encryption_keys is not None

    with pytest.raises(ValidationError) as error:
        Settings(ENCRYPTION_KEYS=f"{new_key()},not-a-key-at-all")

    assert "key 2 is not 32 bytes" in str(error.value)
    assert "not-a-key-at-all" not in str(error.value)


# Uploaded files


def test_uploads_are_stored_encrypted_and_still_answer(client, embedder, llm, files_dir,
                                                       encryption_on):
    upload_process_and_index(client)

    [stored] = stored_files(files_dir)
    content = stored.read_bytes()
    assert content.startswith(FILE_MAGIC)
    assert b"embedding" not in content
    answer = ask(client, question="Where is the embedding vector stored?", min_score=0.2)
    assert answer.status_code == 200 and answer.json()["answer"]


def test_the_scanner_gets_the_file_as_uploaded(db, monkeypatch, files_dir, encryption_on):
    from fastapi.testclient import TestClient

    with FakeClamd() as clamd:
        monkeypatch.setenv("CLAMAV_URL", f"tcp://127.0.0.1:{clamd.port}")
        get_settings.cache_clear()
        from ragolex.main import create_app

        with TestClient(create_app()) as client:
            response = client.post("/api/v1/data/upload/demo",
                                   files={"file": ("notes.txt", b"Cats purr.", "text/plain")})

    assert response.status_code == 200
    assert clamd.received == [b"Cats purr."]
    [stored] = stored_files(files_dir)
    assert stored.read_bytes().startswith(FILE_MAGIC)


def test_encrypted_files_need_their_key(client, embedder, files_dir, monkeypatch, encryption_on):
    file_id = client.post("/api/v1/data/upload/demo",
                          files={"file": ("guide.txt", GUIDE, "text/plain")}).json()["file_id"]
    use_keys(monkeypatch, new_key())  # The key that encrypted it is lost.

    response = client.post("/api/v1/data/process/demo",
                           json={"file_id": file_id, "chunk_size": 60, "overlap_size": 0})

    assert response.status_code == 422
    assert response.json()["signal"] == "processing_failed"


def test_plaintext_copies_and_files_stored_before_there_were_keys(tmp_path):
    keys = ring(new_key())
    storage = FileStorage(tmp_path, keys)
    plain = tmp_path / "plain.txt"
    plain.write_bytes(b"from before")

    with storage.plaintext(plain) as path:
        assert path == plain
    assert storage.encrypt_file(plain) is True
    assert storage.encrypt_file(plain) is False  # Already encrypted with the current key.
    with storage.plaintext(plain) as path:
        assert path != plain and path.read_bytes() == b"from before"
        copy_folder = path.parent
    assert not copy_folder.exists()
    storage.copy_plaintext(plain, tmp_path / "out.txt")
    assert (tmp_path / "out.txt").read_bytes() == b"from before"
    with pytest.raises(EncryptionError, match="ENCRYPTION_KEYS is empty"):
        FileStorage(tmp_path).copy_plaintext(plain, tmp_path / "again.txt")


# Webhook secrets


def test_webhook_secrets_are_stored_encrypted_and_still_sign(client, dispatch, query,  # noqa: F811
                                                             encryption_on):
    created = create(client).json()
    client.post("/api/v1/data/upload/p1", files={"file": ("a.txt", b"Hello.", "text/plain")})
    sender = RecordingSender(status=204)

    [(stored,)] = query("SELECT secret FROM webhooks")
    assert stored.startswith("enc:v1:") and created["secret"] not in stored
    assert dispatch(sender) == [True]
    [(_, _, headers, raw)] = sender.requests
    expected = hmac.new(created["secret"].encode(), b"1700000000." + raw, hashlib.sha256)
    assert headers["X-Ragolex-Signature"] == f"t=1700000000,v1={expected.hexdigest()}"


# The command


def test_the_command_encrypts_what_was_stored_before_and_rotates_keys(
        client, embedder, files_dir, query, monkeypatch, capsys):
    file_id = upload_process_and_index(client)
    secret = create(client).json()["secret"]
    first, second = new_key(), new_key()

    assert cli.main(["encryption", "encrypt"]) == cli.FAILED  # No keys yet.
    use_keys(monkeypatch, first)
    assert cli.main(["encryption", "status"]) == cli.PASSED
    assert "files: 1 not encrypted" in capsys.readouterr().out
    assert cli.main(["encryption", "encrypt"]) == cli.PASSED
    first_id = ring(first).current_id
    assert f"Encrypted 1 files and 1 webhook secrets with key {first_id}" in (
        capsys.readouterr().out)
    [(stored,)] = query("SELECT secret FROM webhooks")
    assert stored.startswith(f"enc:v1:{first_id}:")
    # Once more, nothing is left to do.
    cli.main(["encryption", "encrypt"])
    assert "Encrypted 0 files and 0 webhook secrets" in capsys.readouterr().out

    # Rotating: the new key first, the old one kept to read what it encrypted.
    use_keys(monkeypatch, second, first)
    assert cli.main(["encryption", "encrypt"]) == cli.PASSED
    second_id = ring(second).current_id
    assert cli.main(["encryption", "status"]) == cli.PASSED
    status = capsys.readouterr().out
    assert f"files: 1 with key {second_id} (current)" in status
    assert f"webhook secrets: 1 with key {second_id} (current)" in status
    # Without the old key now, everything still reads.
    use_keys(monkeypatch, second)
    assert ring(second).decrypt_value(query("SELECT secret FROM webhooks")[0][0]) == secret
    response = client.post("/api/v1/data/process/demo",
                           json={"file_id": file_id, "chunk_size": 60, "overlap_size": 0})
    assert response.status_code == 200


def test_new_key_prints_a_usable_key(capsys):
    assert cli.main(["encryption", "new-key"]) == cli.PASSED

    key = capsys.readouterr().out.strip()
    assert Settings(ENCRYPTION_KEYS=key).encryption_keys is not None
