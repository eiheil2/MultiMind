"""Integration tests for the ``multimind`` Typer CLI.

These tests drive the CLI through :class:`typer.testing.CliRunner`,
verifying that the application boots, help is rendered, and the
``providers`` command lists the registered providers end-to-end.
"""

from __future__ import annotations

from typer.testing import CliRunner

from multimind.cli.main import app

runner = CliRunner()


class TestCLIHelp:
    """Tests for the CLI top-level help surface."""

    def test_cli_help_works(self) -> None:
        """``multimind --help`` exits 0 and advertises the app name."""

        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "MultiMind" in result.output

    def test_cli_help_lists_registered_commands(self) -> None:
        """The help output lists the ``chat`` and ``providers`` commands."""

        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "chat" in result.output
        assert "providers" in result.output

    def test_cli_no_args_shows_help(self) -> None:
        """With no arguments the app shows help (``no_args_is_help``)."""

        result = runner.invoke(app, [])
        # Typer with no_args_is_help=True exits with code 0 (shows help).
        assert "MultiMind" in result.output


class TestProvidersCommand:
    """Tests for the ``multimind providers`` command."""

    def test_providers_command_works(self) -> None:
        """``multimind providers`` exits 0 and lists the default providers."""

        result = runner.invoke(app, ["providers"])
        assert result.exit_code == 0
        # The default providers should appear in the rendered table.
        assert "gemini-cli" in result.output
        assert "groq" in result.output

    def test_providers_command_shows_channels(self) -> None:
        """The providers table includes the channel column values."""

        result = runner.invoke(app, ["providers"])
        assert result.exit_code == 0
        assert "cli_reuse" in result.output
        assert "local" in result.output

    def test_providers_command_renders_table_title(self) -> None:
        """The providers command renders its table title."""

        result = runner.invoke(app, ["providers"])
        assert result.exit_code == 0
        assert "Provider" in result.output


class TestStatsCommand:
    """Tests for the ``multimind stats`` command."""

    def test_stats_command_works(self) -> None:
        """``multimind stats`` exits 0 and reports topology + providers."""

        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        assert "gemini-cli" in result.output
        # The stats command prints the topology description.
        assert "拓扑" in result.output


class TestGitStatusCommand:
    """Tests for the ``multimind git-status`` command."""

    def test_git_status_command_works(self, temp_git_repo) -> None:
        """``multimind git-status`` reports the repository state."""

        result = runner.invoke(app, ["git-status", "--repo", str(temp_git_repo)])
        assert result.exit_code == 0
        assert "Git 状态" in result.output
