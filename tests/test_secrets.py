from __future__ import annotations

from pathlib import Path

from spectre.secrets import collect_secrets, load_dotenv, merge_secrets


def test_load_dotenv_parses_key_value(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DB_PASSWORD=supersecret\nAPI_KEY=abc123\n")
    result = load_dotenv(str(env_file))
    assert result == {"DB_PASSWORD": "supersecret", "API_KEY": "abc123"}


def test_load_dotenv_skips_comments_and_blanks(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("# this is a comment\n\nDB_PASSWORD=supersecret\n")
    result = load_dotenv(str(env_file))
    assert result == {"DB_PASSWORD": "supersecret"}


def test_load_dotenv_strips_quotes(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('DB_PASSWORD="supersecret"\nAPI_KEY=\'abc123\'\n')
    result = load_dotenv(str(env_file))
    assert result == {"DB_PASSWORD": "supersecret", "API_KEY": "abc123"}


def test_load_dotenv_missing_file() -> None:
    result = load_dotenv("/nonexistent/.env")
    assert result == {}


def test_load_dotenv_ignores_lines_without_equals(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DB_PASSWORD=supersecret\nINVALID_LINE\n")
    result = load_dotenv(str(env_file))
    assert result == {"DB_PASSWORD": "supersecret"}


def test_collect_secrets_merges_in_order() -> None:
    result = collect_secrets(
        service_secrets={"A": "1", "B": "2"},
        environment_secrets={"B": "override", "C": "3"},
    )
    assert result == {"A": "1", "B": "override", "C": "3"}


def test_collect_secrets_with_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("A=from_file\nD=4\n")
    result = collect_secrets(
        service_secrets={"A": "1"},
        secrets_file=str(env_file),
    )
    assert result == {"A": "from_file", "D": "4"}


def test_collect_secrets_cli_overrides_service_file(tmp_path: Path) -> None:
    svc_file = tmp_path / "svc.env"
    cli_file = tmp_path / "cli.env"
    svc_file.write_text("A=svc_val\nB=svc_val\n")
    cli_file.write_text("B=cli_val\nC=cli_val\n")
    result = collect_secrets(
        service_secrets={"A": "1"},
        secrets_file=str(svc_file),
        cli_secrets_file=str(cli_file),
    )
    assert result == {"A": "svc_val", "B": "cli_val", "C": "cli_val"}


def test_collect_secrets_all_none() -> None:
    result = collect_secrets()
    assert result == {}


def test_merge_secrets_adds_to_env_vars() -> None:
    result = merge_secrets({"PORT": "8000"}, {"DB_PASSWORD": "secret"})
    assert result == {"PORT": "8000", "DB_PASSWORD": "secret"}


def test_merge_secrets_overrides_env_vars() -> None:
    result = merge_secrets({"DB_PASSWORD": "old"}, {"DB_PASSWORD": "new"})
    assert result == {"DB_PASSWORD": "new"}


def test_merge_secrets_no_secrets() -> None:
    result = merge_secrets({"PORT": "8000"}, {})
    assert result == {"PORT": "8000"}


def test_merge_secrets_none_env_vars() -> None:
    result = merge_secrets(None, {"A": "1"})
    assert result == {"A": "1"}
