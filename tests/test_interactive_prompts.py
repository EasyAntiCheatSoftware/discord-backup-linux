"""Interactive validation regressions; prompts and Discord transports are synthetic."""

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from discord_backup import cli
from discord_backup.tokens import Candidate
from test_backup import FakeHTTP, PASSWORD, legacy
from test_selection_hub import BOT_TOKEN, BotHTTP


class PromptTests(unittest.TestCase):
    def test_yes_no_retries_invalid_answers_and_keeps_explicit_defaults(self):
        for default in (False, True):
            for answer, expected in (("y", True), (" YES ", True), ("N", False), ("no", False), ("", default)):
                with self.subTest(default=default, answer=answer):
                    output = io.StringIO()
                    with patch.object(cli, "input", side_effect=["maybe", "yn", "1", answer]) as prompt, redirect_stdout(output):
                        self.assertEqual(cli.yes_no("Continue?", default=default), expected)
                    self.assertEqual(prompt.call_count, 4)
                    self.assertEqual(output.getvalue().count("Invalid answer."), 3)

    def test_backup_menu_waits_for_valid_menu_and_invite_answers(self):
        for answer, no_invites in (("n", True), ("yes", False), ("", False)):
            with self.subTest(answer=answer):
                answers = iter(["", "abc", "11", "1", "maybe", "nope", answer, "0"])
                executed = []
                def respond(prompt):
                    value = next(answers)
                    if "Create server/group" in prompt:
                        self.assertEqual(executed, [])
                    return value
                with patch.object(cli, "input", side_effect=respond), \
                     patch.object(cli, "execute", side_effect=lambda args: executed.append(args) or 0), \
                     redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.menu(), 0)
                self.assertEqual(len(executed), 1)
                self.assertEqual(executed[0].no_invites, no_invites)

    def test_account_selection_retries_without_scanning_or_entering_a_token_early(self):
        args = cli.parser().parse_args(["backup"])
        candidate = Candidate("synthetic-account-token", ["Discord"], {"id": "1", "username": "demo"})
        answers = iter(["wrong", "3", "1", "maybe", "n", "²", "9" * 5000, "2", "1"])
        scans = []
        with patch("sys.stdin.isatty", return_value=True), \
             patch.object(cli, "input", side_effect=lambda prompt: next(answers)), \
             patch.object(cli, "scan_accounts", side_effect=lambda args: scans.append(args.scan_browsers) or [candidate]), \
             patch.object(cli, "hidden_token", side_effect=AssertionError("Manual entry was not selected")), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.select_token(args), candidate.token)
        self.assertEqual(scans, [False])
        self.assertNotIn(candidate.token, output.getvalue())

    def test_recovery_browser_choice_retries_without_opening_browser(self):
        source = Path("/data/synthetic.bkup")
        browser = Mock()
        answers = iter(["wrong", "1", "", "maybe", "n", "0"])
        with patch.object(cli, "load_backup", return_value=(legacy(), PASSWORD)), \
             patch.object(cli, "input", side_effect=lambda prompt: next(answers)), \
             patch.object(cli, "export_recovery", return_value=(Path("/data/recovery/index.html"), [])) as export, \
             patch.object(cli.webbrowser, "open", browser), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.recovery_menu(cli.parser().parse_args(["recover", str(source)])), 0)
        export.assert_called_once()
        browser.assert_not_called()

    def test_hub_contact_choice_waits_before_using_the_selected_scope(self):
        source = Path("/data/synthetic.bkup")
        answers = iter(["2", "maybe", "n", "0"])
        hub = Mock()
        def respond(prompt):
            if "Include friends" in prompt:
                hub.assert_not_called()
            return next(answers)
        with patch.object(cli, "load_backup", return_value=(legacy(), PASSWORD)), \
             patch.object(cli, "input", side_effect=respond), patch.object(cli, "hub_flow", hub), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(cli.recovery_menu(cli.parser().parse_args(["recover", str(source)])), 0)
        self.assertEqual(hub.call_args.args[0].include, ["servers", "groups", "warnings"])

    def test_hub_server_selection_retries_invalid_numbers_and_ids(self):
        bot = Mock()
        bot.guilds.return_value = [{"id": "500", "name": "Private recovery"}]
        answers = iter(["", "abc", "2", "²", "9" * 5000, "1"])
        with patch.object(cli, "bot_identity"), patch.object(cli, "input", side_effect=lambda prompt: next(answers)), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.choose_hub_server(bot), "500")
        bot.guilds.assert_called_once()
        bot.request.assert_not_called()
        with patch.object(cli, "bot_identity"), patch.object(cli, "input", return_value="123456789012345678"), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.choose_hub_server(bot), "123456789012345678")
        with patch.object(cli, "bot_identity"), patch.object(cli, "input", return_value="0"), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "cancelled"):
                cli.choose_hub_server(bot)

    def test_restore_confirmations_retry_typos_without_writing(self):
        http = FakeHTTP({("GET", "/users/@me"): {"id": "2", "username": "new-account"}})
        answers = iter(["different", "yes", "DIFFERENT", "apply", "y", ""])
        def respond(prompt):
            self.assertEqual(http.writes(), [])
            return next(answers)
        with patch.object(cli, "client_for", return_value=http.client()), \
             patch.object(cli, "input", side_effect=respond) as prompt, redirect_stdout(io.StringIO()):
            cli.settings_flow(cli.parser().parse_args(["restore-folders"]), legacy(), PASSWORD)
        self.assertEqual(prompt.call_count, 6)
        self.assertEqual(http.writes(), [])

    def test_hub_publish_requires_the_exact_word_after_invalid_answers(self):
        http = BotHTTP()
        answers = iter(["publish", "yes", "PUBLISH"])
        def respond(prompt):
            self.assertEqual(http.writes(), [])
            return next(answers)
        args = cli.parser().parse_args(["restore-hub", "--guild", "500"])
        with patch.object(cli, "DiscordBotClient", return_value=http.client()), \
             patch.object(cli, "hidden_input", return_value=BOT_TOKEN), \
             patch.object(cli, "input", side_effect=respond) as prompt, redirect_stdout(io.StringIO()):
            self.assertEqual(cli.hub_flow(args, legacy(), confirm=True), 0)
        self.assertEqual(prompt.call_count, 3)
        self.assertTrue(http.messages())

    def test_eof_at_yes_no_prompt_cancels_instead_of_selecting_default(self):
        with patch("sys.stdin.isatty", return_value=True), \
             patch.object(cli, "input", side_effect=["1", "maybe", EOFError]), \
             patch.object(cli, "execute") as execute, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main([]), 130)
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()

