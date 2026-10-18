"""Configuration parsing and validation tests."""

from __future__ import annotations

import pytest

from pytaskwirecheck.diagnostics.errors import ConfigError, ConfigVersionError

VALID = """
[project]
name = "demo"
version = 1

[execution]
max_workers = 2
default_timeout_seconds = 30
fail_fast = false

[tasks.a]
command = ["python", "-c", "print('a')"]
inputs = ["src/**/*.py"]
outputs = ["out.txt"]
cache = true

[tasks.b]
command = ["python", "-c", "print('b')"]
depends_on = ["a"]
"""


def test_valid_config_parses(make_config):
    config = make_config(VALID)
    assert config.project.name == "demo"
    assert config.project.version == 1
    assert config.execution.max_workers == 2
    assert set(config.tasks.keys()) == {"a", "b"}
    assert config.tasks["b"].depends_on == ("a",)
    assert config.tasks["a"].inputs == ("src/**/*.py",)
    assert config.tasks["a"].cache_eligible is True


def test_unknown_top_level_field(make_config):
    with pytest.raises(ConfigError, match="unknown field"):
        make_config(
            """
            [project]
            name = "x"
            bogus = 1

            [tasks.a]
            command = ["true"]
            """
        )


def test_unknown_task_field(make_config):
    with pytest.raises(ConfigError, match="unknown field"):
        make_config(
            """
            [tasks.a]
            command = ["true"]
            nope = 1
            """
        )


def test_missing_command(make_config):
    with pytest.raises(ConfigError):
        make_config(
            """
            [tasks.a]
            depends_on = []
            """
        )


def test_command_must_be_string_array(make_config):
    with pytest.raises(ConfigError, match="array of strings"):
        make_config(
            """
            [tasks.a]
            command = "echo hi"
            """
        )


def test_empty_command_rejected(make_config):
    with pytest.raises(ConfigError):
        make_config(
            """
            [tasks.a]
            command = []
            """
        )


def test_unsupported_version(make_config):
    with pytest.raises(ConfigVersionError):
        make_config(
            """
            [project]
            version = 99
            [tasks.a]
            command = ["true"]
            """
        )


def test_version_must_be_int(make_config):
    with pytest.raises(ConfigError):
        make_config(
            """
            [project]
            version = "1"
            [tasks.a]
            command = ["true"]
            """
        )


def test_duplicate_dependency_rejected(make_config):
    with pytest.raises(ConfigError, match="duplicate"):
        make_config(
            """
            [tasks.a]
            command = ["true"]
            [tasks.b]
            command = ["true"]
            depends_on = ["a", "a"]
            """
        )


def test_self_dependency_rejected(make_config):
    with pytest.raises(ConfigError, match="depend on itself"):
        make_config(
            """
            [tasks.a]
            command = ["true"]
            depends_on = ["a"]
            """
        )


def test_no_tasks(make_config):
    with pytest.raises(ConfigError, match="no tasks"):
        make_config(
            """
            [project]
            name = "empty"
            """
        )


def test_absolute_output_rejected(make_config):
    with pytest.raises(ConfigError, match="absolute"):
        make_config(
            """
            [tasks.a]
            command = ["true"]
            outputs = ["/etc/passwd"]
            """
        )


def test_escaping_output_rejected(make_config):
    with pytest.raises(ConfigError, match="escapes"):
        make_config(
            """
            [tasks.a]
            command = ["true"]
            outputs = ["../../etc/passwd"]
            """
        )


def test_escaping_cwd_rejected(make_config):
    with pytest.raises(ConfigError, match="escapes"):
        make_config(
            """
            [tasks.a]
            command = ["true"]
            cwd = "../outside"
            """
        )


def test_shell_requires_single_element(make_config):
    with pytest.raises(ConfigError, match="single string"):
        make_config(
            """
            [tasks.a]
            command = ["echo", "hi"]
            shell = true
            """
        )


def test_shell_single_element_ok(make_config):
    config = make_config(
        """
        [tasks.a]
        command = ["echo hi"]
        shell = true
        """
    )
    assert config.tasks["a"].shell is True


def test_invalid_task_identifier(make_config):
    with pytest.raises(ConfigError, match="invalid character"):
        make_config(
            """
            [tasks."bad id"]
            command = ["true"]
            """
        )


def test_env_values_must_be_strings(make_config):
    with pytest.raises(ConfigError):
        make_config(
            """
            [tasks.a]
            command = ["true"]
            [tasks.a.env]
            COUNT = 1
            """
        )


def test_retry_table(make_config):
    config = make_config(
        """
        [tasks.a]
        command = ["true"]
        [tasks.a.retry]
        max_attempts = 3
        delay_seconds = 0.5
        backoff = true
        """
    )
    retry = config.tasks["a"].retry
    assert retry.max_attempts == 3
    assert retry.delay_seconds == 0.5
    assert retry.backoff is True
    assert retry.enabled is True


def test_legacy_retries_counts_after_first(make_config):
    config = make_config(
        """
        [tasks.a]
        command = ["true"]
        retries = 2
        """
    )
    assert config.tasks["a"].retry.max_attempts == 3


def test_max_workers_bounds(make_config):
    with pytest.raises(ConfigError):
        make_config(
            """
            [execution]
            max_workers = 0
            [tasks.a]
            command = ["true"]
            """
        )


def test_cache_eligible_requires_io(make_config):
    config = make_config(
        """
        [tasks.a]
        command = ["true"]
        cache = true
        """
    )
    assert config.tasks["a"].cache_eligible is False


def test_cache_eviction_bounds_parse(make_config):
    config = make_config(
        """
        [cache]
        max_bytes = 2048
        max_entries = 5
        [tasks.a]
        command = ["true"]
        """
    )
    assert config.cache.max_bytes == 2048
    assert config.cache.max_entries == 5


def test_cache_eviction_bounds_default(make_config):
    config = make_config(
        """
        [tasks.a]
        command = ["true"]
        """
    )
    assert config.cache.max_bytes == 1_073_741_824
    assert config.cache.max_entries == 1000


def test_cache_eviction_bounds_zero_means_unlimited(make_config):
    config = make_config(
        """
        [cache]
        max_bytes = 0
        max_entries = 0
        [tasks.a]
        command = ["true"]
        """
    )
    assert config.cache.max_bytes is None
    assert config.cache.max_entries is None
