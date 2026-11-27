# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""The release's Discord announcement travels changelog/discord.md → manifest
`discord_post_md` → notes/discord_post.md → the announcements webhook, and is
posted at most once: on a first publish, never on a forced republish. A
missing draft never fails a build and a failed post never fails a publish."""
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 64
POST = "@everyone\n\n# 🚀 Mixar 1.2.3 is here\n\n🎨 **Paint**: faster\n\n**The Mixar team**"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / ".github/scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build(tmp_path, monkeypatch, discord, notification=None):
    """Run build_release_manifest.py; `discord` None = no discord.md at all."""
    changelog = tmp_path / "changelog"
    changelog.mkdir()
    (changelog / "user.md").write_text("User notes\n", encoding="utf-8")
    (changelog / "technical.md").write_text("Technical notes\n", encoding="utf-8")
    if notification is not None:
        (changelog / "notification.txt").write_bytes(notification)
    if discord is not None:
        (changelog / "discord.md").write_text(discord, encoding="utf-8")
    env = {"VERSION": "1.2.3", "TAG": "v1.2.3", "PR_NUMBER": "42",
           "CHANGELOG_DIR": str(changelog), "OUT_FILE": str(tmp_path / "manifest.json")}
    for prefix, ext in (("MACOS", "dmg"), ("WINDOWS", "msi"), ("LINUX", "tar.xz")):
        env.update({f"{prefix}_S3_KEY": f"releases/1.2.3/mixar.{ext}",
                    f"{prefix}_SIZE_BYTES": "1", f"{prefix}_SHA256": SHA})
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    _load("build_release_manifest").main()
    return json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))


def _manifest(**extra):
    return {
        "schema_version": 1, "status": "pending", "version": "1.2.3", "tag": "v1.2.3",
        "channel": "stable", "severity": "recommended", "notify": True,
        "release_notes_md": "User notes", "technical_notes_md": "Technical notes",
        "platforms": {
            "mac": {"s3_key": "r/m.dmg", "size": 1, "sha256": SHA},
            "windows": {"s3_key": "r/w.msi", "size": 1, "sha256": SHA},
        },
        **extra,
    }


def _load_manifest(tmp_path, monkeypatch, manifest):
    """Run load_release_manifest.py; returns (outputs, notes dir)."""
    manifest_file = tmp_path / "in.json"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "github-output"
    monkeypatch.setenv("VERSION", manifest["version"])
    monkeypatch.setenv("MANIFEST_FILE", str(manifest_file))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("NOTES_DIR", str(tmp_path / "notes"))
    _load("load_release_manifest").main()
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    return outputs, tmp_path / "notes"


# ── builder ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("draft", [None, b" ", b"two\nlines", b"x" * 201, b"\xff"])
def test_unusable_notification_uses_release_notes(tmp_path, monkeypatch, draft):
    manifest = _build(tmp_path, monkeypatch, POST, notification=draft)
    assert manifest["changelog_summary"] == "User notes"


def test_notification_and_discord_can_be_edited_independently(tmp_path, monkeypatch):
    manifest = _build(tmp_path, monkeypatch, POST, notification=b"Paint faster.")
    assert manifest["changelog_summary"] == "Paint faster."
    manifest["changelog_summary"] = 'Try the new "Paint" tools.'
    outputs, notes = _load_manifest(tmp_path, monkeypatch, manifest)
    assert outputs["changelog_summary"] == manifest["changelog_summary"]
    assert (notes / "release_notes.md").read_text().strip() == "User notes"
    assert (notes / "discord_post.md").read_text().strip() == POST


def test_builder_stores_the_draft_and_the_loader_hands_it_to_publish(tmp_path, monkeypatch):
    manifest = _build(tmp_path, monkeypatch, POST + "\n")
    assert manifest["discord_post_md"] == POST

    outputs, notes = _load_manifest(tmp_path, monkeypatch, manifest)
    assert outputs["has_discord_post"] == "true"
    assert (notes / "discord_post.md").read_text(encoding="utf-8") == POST + "\n"


@pytest.mark.parametrize("discord", [None, "", " \n\t\n"])
def test_missing_or_blank_draft_never_fails_the_build(tmp_path, monkeypatch, capsys, discord):
    manifest = _build(tmp_path, monkeypatch, discord)
    assert manifest["discord_post_md"] == ""
    assert manifest["release_notes_md"] == "User notes"
    assert "::warning::manifest: optional" in capsys.readouterr().out


# ── loader ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("extra", [{}, {"discord_post_md": None}, {"discord_post_md": ""},
                                   {"discord_post_md": " \n\t "}])
def test_absent_null_or_blank_post_publishes_without_discord(tmp_path, monkeypatch, extra):
    outputs, notes = _load_manifest(tmp_path, monkeypatch, _manifest(**extra))
    assert outputs["has_discord_post"] == "false"
    assert not (notes / "discord_post.md").exists()
    assert outputs["status"] == "pending"


def test_limit_is_2000_code_points_after_trimming(tmp_path, monkeypatch, capsys):
    # 2000 emoji are 2000 characters (len), though 4000 UTF-16 units: the
    # count has to agree with mixar-backend and the dashboard's counter.
    at_limit = "🚀" * 2000
    outputs, notes = _load_manifest(tmp_path, monkeypatch,
                                    _manifest(discord_post_md=f"\n{at_limit}  \n"))
    assert outputs["has_discord_post"] == "true"
    assert (notes / "discord_post.md").read_text(encoding="utf-8") == at_limit + "\n"

    with pytest.raises(SystemExit) as exit_info:
        _load_manifest(tmp_path, monkeypatch, _manifest(discord_post_md=at_limit + "!"))
    assert exit_info.value.code == 1
    error = capsys.readouterr().out
    assert "::error::manifest: discord_post_md is 2001 characters" in error
    assert "Shorten the Discord post" in error


# ── publish step ───────────────────────────────────────────────────────────

@pytest.fixture
def webhook():
    """A local stand-in for the Discord webhook; records what it is sent."""
    state = {"requests": [], "status": 204}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - http.server's naming
            body = self.rfile.read(int(self.headers["Content-Length"]))
            state["requests"].append({"path": self.path, "headers": dict(self.headers),
                                      "json": json.loads(body)})
            self.send_response(state["status"])
            answer = b"" if state["status"] == 204 else b'{"message": "Unknown Webhook", "code": 10015}'
            self.send_header("Content-Length", str(len(answer)))
            self.end_headers()
            self.wfile.write(answer)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_port}/api/webhooks/1/s3cret-token"
    yield state
    server.shutdown()
    server.server_close()


def _announce(tmp_path, monkeypatch, capsys, *, url, text=POST, status="pending", force="false",
              channel="stable", notify="true"):
    """Run post_discord_announcement.py; returns (exit code, stdout, summary)."""
    notes = tmp_path / "notes"
    notes.mkdir(exist_ok=True)
    if text:
        (notes / "discord_post.md").write_text(text + "\n", encoding="utf-8")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("NOTES_DIR", str(notes))
    monkeypatch.setenv("HAS_DISCORD_POST", "true" if text else "false")
    monkeypatch.setenv("MANIFEST_STATUS", status)
    monkeypatch.setenv("FORCE", force)
    monkeypatch.setenv("CHANNEL", channel)
    monkeypatch.setenv("NOTIFY", notify)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", url)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("no_proxy", "*")
    code = _load("post_discord_announcement").main()
    return code, capsys.readouterr().out, summary.read_text(encoding="utf-8")


def test_first_publish_posts_the_exact_text_once(tmp_path, monkeypatch, capsys, webhook):
    code, stdout, summary = _announce(tmp_path, monkeypatch, capsys, url=webhook["url"] + "\n")
    assert code == 0
    assert len(webhook["requests"]) == 1
    request = webhook["requests"][0]
    assert request["json"] == {"content": POST, "allowed_mentions": {"parse": ["everyone"]}}
    assert request["headers"]["Content-Type"] == "application/json"
    # Discord's edge answers 403 (error 1010) to urllib's default User-Agent.
    assert not request["headers"]["User-Agent"].startswith("Python-urllib")
    assert "**Posted**" in summary and POST in summary
    assert "s3cret-token" not in stdout + summary


@pytest.mark.parametrize("kwargs, reason", [
    ({"force": "true"}, "forced republish"),
    ({"force": "true", "status": "published"}, "forced republish"),
    ({"status": "published"}, "already 'published'"),
    ({"status": ""}, "first publish only"),
    ({"url": ""}, "DISCORD_ANNOUNCEMENTS_WEBHOOK_URL secret is not set"),
    ({"channel": "beta"}, "stable releases only"),
    ({"notify": "false"}, "notify is off"),
])
def test_republish_or_unconfigured_never_posts_but_shows_the_text(
        tmp_path, monkeypatch, capsys, webhook, kwargs, reason):
    kwargs = {"url": webhook["url"], **kwargs}
    code, stdout, summary = _announce(tmp_path, monkeypatch, capsys, **kwargs)
    assert code == 0
    assert webhook["requests"] == []
    assert "**Skipped**" in summary and reason in summary and POST in summary
    assert "skipped" in stdout


def test_no_post_in_the_manifest_is_a_quiet_no_op(tmp_path, monkeypatch, capsys, webhook):
    code, _, summary = _announce(tmp_path, monkeypatch, capsys, url=webhook["url"], text="")
    assert code == 0
    assert webhook["requests"] == []
    assert "no `discord_post_md`" in summary


def test_a_failed_post_warns_keeps_the_text_and_hides_the_webhook(
        tmp_path, monkeypatch, capsys, webhook):
    webhook["status"] = 404
    code, stdout, summary = _announce(tmp_path, monkeypatch, capsys, url=webhook["url"])
    assert code == 1  # the workflow step is continue-on-error
    assert "::warning::Discord announcement was NOT posted: HTTP 404" in stdout
    assert "Unknown Webhook" in stdout
    assert "**Not posted**" in summary and POST in summary
    assert "s3cret-token" not in stdout + summary


@pytest.mark.parametrize("bad_url", ["not-a-url/s3cret-token", "file:///tmp/s3cret-token",
                                     "http://127.0.0.1:1/s3cret-token"])
def test_an_unusable_webhook_fails_soft_without_echoing_it(tmp_path, monkeypatch, capsys, bad_url):
    code, stdout, summary = _announce(tmp_path, monkeypatch, capsys, url=bad_url)
    assert code == 1
    assert "::warning::" in stdout and "**Not posted**" in summary
    assert "s3cret-token" not in stdout + summary


def test_summary_fence_outgrows_backticks_in_the_post():
    fenced = _load("post_discord_announcement").fenced("try ```this``` now")
    assert fenced.startswith("````text\n") and fenced.endswith("\n````")


# ── wiring ─────────────────────────────────────────────────────────────────

def test_publish_posts_after_the_stamp_and_only_on_a_first_publish():
    wf = (ROOT / ".github/workflows/publish-release.yml").read_text(encoding="utf-8")
    step = wf.split("- name: Post Discord announcement (first publish only)")[1]
    step = step.split("\n      - name:")[0]
    assert "continue-on-error: true" in step
    assert "DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_ANNOUNCEMENTS_WEBHOOK_URL }}" in step
    assert "HAS_DISCORD_POST: ${{ steps.mf.outputs.has_discord_post }}" in step
    assert "MANIFEST_STATUS: ${{ steps.mf.outputs.status }}" in step
    assert "FORCE: ${{ inputs.force && 'true' || 'false' }}" in step
    assert "CHANNEL: ${{ steps.mf.outputs.channel }}" in step
    assert "NOTIFY: ${{ steps.mf.outputs.notify }}" in step
    assert "run: python3 .github/scripts/post_discord_announcement.py" in step
    # After the stamp: a version that reached this step can only be published
    # again with force=true, which never posts.
    assert wf.index("- name: Stamp manifest as published") < wf.index("- name: Post Discord announcement")
    # The secret reaches the script through env only, never a command line.
    assert wf.count("DISCORD_ANNOUNCEMENTS_WEBHOOK_URL }}") == 1


def test_changelog_job_writes_and_checks_the_draft():
    wf = (ROOT / ".github/workflows/release-orchestrator.yml").read_text(encoding="utf-8")
    assert "Produce exactly four files" in wf
    assert "./changelog/notification.txt" in wf and "./changelog/discord.md" in wf
    # The draft is optional: a missing, blank or over-long one warns and is
    # stored empty (no post) instead of failing the changelog job.
    assert "test -s changelog/discord.md" not in wf
    assert '"$DISCORD_CHARS" -gt 2000' in wf
    assert ": > changelog/discord.md" in wf
    prompt = (ROOT / ".github/prompts/release-notes.md").read_text(encoding="utf-8")
    assert "`changelog/discord.md`" in prompt
    assert "Hard limit: 1900 characters" in prompt
    assert "`@everyone` alone on the first line" in prompt
