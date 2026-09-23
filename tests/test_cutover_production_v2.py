import os
from pathlib import Path

import pytest

from admin.cutover_production_v2 import (
    READER_ROLE,
    SYNC_ROLE,
    direct_dsn,
    redacted_error,
    role_dsn,
    write_private_candidate,
)


OWNER_DSN = (
    "postgresql://neondb_owner:old%20password@ep-example.us-east-2.aws.neon.tech/neondb"
    "?sslmode=require&channel_binding=require&application_name=bridge"
)


@pytest.mark.parametrize("role", [SYNC_ROLE, READER_ROLE])
def test_role_dsn_replaces_only_credentials_and_preserves_connection_options(role):
    generated = role_dsn(OWNER_DSN, role, "new /:@?#% password")

    # Parse through psycopg instead of asserting a particular escaping style.
    from psycopg.conninfo import conninfo_to_dict

    parsed = conninfo_to_dict(generated)
    assert parsed["user"] == role
    assert parsed["password"] == "new /:@?#% password"
    assert parsed["host"] == "ep-example.us-east-2.aws.neon.tech"
    assert parsed["dbname"] == "neondb"
    assert parsed["sslmode"] == "require"
    assert parsed["channel_binding"] == "require"
    assert parsed["application_name"] == "bridge"
    assert "neondb_owner" not in generated
    assert "old%20password" not in generated


def test_role_dsn_accepts_keyword_conninfo_without_leaking_old_credentials():
    source = (
        "host=ep-example.neon.tech dbname=neondb user=neondb_owner "
        "password='old password' sslmode=require"
    )
    generated = role_dsn(source, SYNC_ROLE, "replacement password")

    from psycopg.conninfo import conninfo_to_dict

    parsed = conninfo_to_dict(generated)
    assert parsed["user"] == SYNC_ROLE
    assert parsed["password"] == "replacement password"
    assert "old password" not in generated
    assert "neondb_owner" not in generated


def test_redacted_error_never_returns_dsn_password_host_or_username():
    secret = "correct-horse-battery-staple"
    raw = (
        "connection failed for postgresql://neondb_owner:"
        f"{secret}@private-production-host.neon.tech/neondb"
    )
    public = redacted_error(RuntimeError(raw), (secret, OWNER_DSN))

    assert secret not in public
    assert "neondb_owner" not in public
    assert "private-production-host" not in public
    assert "postgresql://" not in public
    assert public


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission assertion")
def test_candidate_secret_file_is_owner_only_on_posix(tmp_path):
    target = tmp_path / "reader-v2.json"
    target.touch(mode=0o600)
    write_private_candidate(target, {"postgres_dsn": "secret"})
    assert target.stat().st_mode & 0o777 == 0o600


def test_candidate_writer_rejects_non_object_secret_document(tmp_path):
    target = tmp_path / "reader-v2.json"
    target.touch(mode=0o600)
    with pytest.raises((TypeError, ValueError)):
        write_private_candidate(target, ["secret"])


def test_candidate_writer_refuses_unprepared_secret_container(tmp_path):
    with pytest.raises(RuntimeError, match="preparado"):
        write_private_candidate(tmp_path / "missing.json", {"postgres_dsn": "secret"})


def test_powershell_wrapper_uses_atomic_replace_and_cleans_candidates():
    script = (Path(__file__).parents[1] / "activar_roles_v2.ps1").read_text(
        encoding="utf-8"
    )
    assert "[IO.File]::Replace($candidateConfig, $configPath, $replaceBackup, $true)" in script
    assert "$replaceBackup = Join-Path $InstallDir" in script
    assert "Remove-Item -LiteralPath $replaceBackup" in script
    assert "finally" in script
    assert "Remove-Item -LiteralPath $candidateConfig" in script
    assert "Remove-Item -LiteralPath $candidateReader" in script

    # The old production configuration must remain available until both new
    # credentials were validated and the protected reader file was installed.
    assert script.index("if ($LASTEXITCODE -ne 0)") < script.index(
        "[IO.File]::Replace($candidateConfig, $configPath"
    )
    assert script.index("Copy-Item -LiteralPath $configPath") < script.index(
        "[IO.File]::Replace($candidateConfig, $configPath"
    )


def test_pooled_neon_conninfo_is_converted_to_direct_without_changing_options():
    from psycopg.conninfo import conninfo_to_dict

    pooled = OWNER_DSN.replace("ep-example.", "ep-example-pooler.")
    parsed = conninfo_to_dict(direct_dsn(pooled))
    assert parsed["host"] == "ep-example.us-east-2.aws.neon.tech"
    assert parsed["dbname"] == "neondb"
    assert parsed["sslmode"] == "require"
    assert parsed["channel_binding"] == "require"


def test_main_converts_pooler_and_has_sanitized_top_level_failure():
    source = (Path(__file__).parents[1] / "admin/cutover_production_v2.py").read_text(
        encoding="utf-8"
    )
    assert "source_dsn = direct_dsn" in source
    assert "redacted_error" in source
    assert "except Exception" in source
    assert "traceback" not in source.lower()


def test_helper_verifies_privilege_groups_are_nologin_and_non_admin():
    source = (Path(__file__).parents[1] / "admin/cutover_production_v2.py").read_text(
        encoding="utf-8"
    ).lower()
    for attribute in (
        "rolcanlogin",
        "rolsuper",
        "rolcreatedb",
        "rolcreaterole",
        "rolreplication",
        "rolbypassrls",
    ):
        assert attribute in source
    assert "expected_groups" in source
    # Both logins and both NOLOGIN privilege groups must be fetched/validated.
    assert "list(expected_groups)" in source
    assert "list(expected_groups.values())" in source


def test_wrapper_protects_candidates_before_python_and_rolls_back_after_swap():
    script = (Path(__file__).parents[1] / "activar_roles_v2.ps1").read_text(
        encoding="utf-8"
    )
    python_call = script.index("& $python $helper")
    assert script.index("New-Item", 0, python_call) >= 0
    assert script.index("Set-PrivateAcl $candidateConfig", 0, python_call) >= 0
    assert script.index("Set-PrivateAcl $candidateReader", 0, python_call) >= 0

    swap = script.index("[IO.File]::Replace($candidateConfig, $configPath")
    finally_block = script.index("finally", swap)
    rollback = script.index("Copy-Item", swap, finally_block)
    assert rollback > swap
