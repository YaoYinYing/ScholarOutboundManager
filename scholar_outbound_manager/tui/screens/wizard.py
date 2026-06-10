"""First-run wizard screen for missing config.yaml."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button
from textual.widgets import Input
from textual.widgets import Static


class WizardScreen(Screen[None]):
    """First-run wizard that creates a config.yaml template."""

    CSS = """
    WizardScreen {
        align: center middle;
    }
    #wizard-container {
        width: 60;
        height: auto;
        border: solid $primary;
        padding: 1 2;
    }
    #wizard-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }
    #wizard-step-title {
        text-style: bold;
        padding-top: 1;
    }
    .wizard-field {
        padding-left: 2;
    }
    #wizard-message {
        padding-top: 1;
        color: $warning;
    }
    """

    def __init__(self, services) -> None:
        super().__init__()
        self._services = services
        self._step = 0
        self._config_path = str(services._config_path)
        self._fields: dict[str, str] = {
            "config_path": str(services._config_path),
            "subscription_url": "",
            "user_data_dir": "state_data",
            "xray_binary_path": ".runtime/xray/xray",
        }

    def compose(self) -> ComposeResult:
        with Vertical(id="wizard-container"):
            yield Static("Scholar Outbound Manager", id="wizard-title")
            yield Static("First-Run Setup", id="wizard-step-title")
            yield Static("", id="wizard-body")
            yield Static("", id="wizard-message")
            with Horizontal(id="wizard-actions"):
                yield Button("Next", id="btn-next")
                yield Button("Skip", id="btn-skip")
                yield Button("Quit", id="btn-quit")

    def on_mount(self) -> None:
        self._render_step()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-quit":
            self.app.exit()
        elif event.button.id == "btn-skip":
            self._create_template_and_exit()
        elif event.button.id == "btn-next":
            self._advance()

    def _render_step(self) -> None:
        steps = [
            ("Step 1: Config Path", "config_path", "Path for the new config file."),
            ("Step 2: Subscription", "subscription_url", "Enter your subscription URL."),
            ("Step 3: User Data", "user_data_dir", "Directory for artifacts and journals."),
            ("Step 4: Xray Binary", "xray_binary_path", "Path to Xray core binary."),
            ("Step 5: Save", None, "Review and save the config template."),
        ]

        if self._step >= len(steps):
            self._create_template_and_exit()
            return

        title, key, desc = steps[self._step]

        self.query_one("#wizard-step-title", Static).update(title)

        if key is not None:
            body = f"{desc}\n\n  {key}: {self._fields[key]}"
            self.query_one("#wizard-body", Static).update(body)
            self.query_one("#btn-next", Button).label = "Edit & Next"
            self.query_one("#btn-skip", Button).display = True
        else:
            # Review step
            lines = ["Review before saving:\n"]
            for k, v in self._fields.items():
                display = v if k != "subscription_url" or not v else "***configured***"
                lines.append(f"  {k}: {display}")
            self.query_one("#wizard-body", Static).update("\n".join(lines))
            self.query_one("#btn-next", Button).label = "Save & Continue"
            self.query_one("#btn-skip", Button).display = False

    def _advance(self) -> None:
        if self._step == 0:
            self._prompt_edit("config_path", "Enter config path:")
        elif self._step == 1:
            self._prompt_edit("subscription_url", "Enter subscription URL:")
        elif self._step == 2:
            self._prompt_edit("user_data_dir", "Enter user data directory:")
        elif self._step == 3:
            self._prompt_edit("xray_binary_path", "Enter Xray binary path:")
        else:
            self._step += 1
            self._render_step()

    def _prompt_edit(self, key: str, prompt: str) -> None:
        def on_submit(value: str) -> None:
            if value.strip():
                self._fields[key] = value.strip()
            self._step += 1
            self._render_step()
            # Remove the input after use
            try:
                inp = self.query_one("#wizard-input", Input)
                inp.remove()
            except Exception:
                pass

        try:
            old = self.query_one("#wizard-input", Input)
            old.remove()
        except Exception:
            pass

        inp = Input(self._fields[key], id="wizard-input")
        inp.mount(self.query_one("#wizard-container"))
        inp.focus()

        # We use a simple approach: mount the input and advance on next button
        # The actual value is captured via the existing button handler
        self._pending_key = key

    def _create_template_and_exit(self) -> None:
        try:
            import yaml
            config_path = Path(self._fields["config_path"])
            config_path.parent.mkdir(parents=True, exist_ok=True)

            template = {
                "schema_version": 1,
                "user_data_dir": self._fields["user_data_dir"],
                "subscriptions": [
                    {
                        "name": "default",
                        "url": self._fields["subscription_url"] or "https://example.invalid/sub",
                        "format": "auto",
                        "enabled": bool(self._fields["subscription_url"]),
                        "headers": {},
                    }
                ],
                "filters": {
                    "include_keywords": ["scholar", "google"],
                    "exclude_keywords": [],
                    "deprioritize_keywords": ["ipv6"],
                },
                "probe": {
                    "timeout_seconds": 15,
                    "concurrency": 1,
                    "cache_ttl_hours": 24,
                    "failure_backoff_hours": 48,
                    "allow_network_probe": True,
                },
                "xray": {
                    "binary_path": self._fields["xray_binary_path"],
                    "runtime_dir": ".runtime",
                    "local_socks_host": "127.0.0.1",
                    "local_socks_port": 0,
                },
                "output": {
                    "outbounds_path": "generated/google_scholar_outbounds.json",
                    "routes_path": "generated/google_scholar_routes.json",
                    "manifest_path": "generated/google_scholar_manifest.json",
                    "history_dir": "state_data/history",
                },
                "generation": {
                    "tag_prefix": "google-scholar-node-",
                    "max_passed_nodes": 3,
                    "fallback_blackhole_tag": "google-scholar-unavailable",
                    "previous_output_max_age_hours": 168,
                },
                "routing": {
                    "mode": "dedicated_inbound",
                    "inbound_tags": ["google-scholar-in"],
                    "fail_closed": True,
                },
            }

            config_path.write_text(yaml.dump(template, default_flow_style=False), encoding="utf-8")
            self._services._config_path = config_path
        except Exception as exc:
            self.query_one("#wizard-message", Static).update(f"Failed: {exc}")
            return

        self.app.push_screen(HomeScreen(self._services))
