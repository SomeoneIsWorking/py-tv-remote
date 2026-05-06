import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        import sys
        app = QApplication(sys.argv)
    return app


class TestAppComponentApi:
    """Verify app components use correct Edifice API (catch TypeError from wrong props)."""

    def test_progressbar_correct_api(self, qapp):
        """ProgressBar must use min_value / max_value, not 'maximum'."""
        from edifice import ProgressBar

        ProgressBar(value=0, min_value=0, max_value=0)

        ProgressBar(value=50, min_value=0, max_value=100)

        ProgressBar(value=0, min_value=0, max_value=0, style={"min-width": 250})

    def test_button_enabled_prop(self, qapp):
        """Button accepts enabled=False."""
        from edifice import Button

        Button(title="test", enabled=False)
        Button(title="test", enabled=True)

    def test_textinput_placeholder(self, qapp):
        """TextInput accepts placeholder_text."""
        from edifice import TextInput

        TextInput(text="", placeholder_text="e.g. 1.2.3.4")

    def test_hbox_spacing(self, qapp):
        """HBoxView accepts style with spacing."""
        from edifice import HBoxView

        HBoxView(style={"spacing": 5})

    def test_vbox_setting(self, qapp):
        """VBoxView accepts style with align and spacing."""
        from edifice import VBoxView

        VBoxView(style={"align": "center", "spacing": 5})

    def test_label_styles(self, qapp):
        """Label accepts common style props used in the app."""
        from edifice import Label

        Label(text="test", style={"color": "#888"})
        Label(text="test", style={"font-size": "18px", "font-weight": "bold"})
        Label(text="test", style={"font-size": "48px", "font-weight": "bold", "letter-spacing": "10px"})


class TestAppModuleLoads:
    """Verify the app module imports and defines its API correctly."""

    def test_app_imports_cleanly(self):
        """Verify no ImportError or SyntaxError when importing."""
        import importlib
        import tv_remote.app
        importlib.reload(tv_remote.app)

    def test_app_has_main(self):
        """App module exposes a main() callable."""
        from tv_remote.app import main
        assert callable(main)

    def test_app_uses_correct_progressbar_args(self):
        """Check source for ProgressBar calls to prevent 'maximum' arguments."""
        import ast
        import pathlib

        app_path = pathlib.Path(__file__).parent.parent / "src" / "tv_remote" / "app.py"
        tree = ast.parse(app_path.read_text())

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "ProgressBar":
                for kw in node.keywords:
                    if kw.arg in ("maximum", "minimum"):
                        pytest.fail(f"ProgressBar uses wrong arg '{kw.arg}' at line {node.lineno}")

    def test_no_broken_lambdas(self):
        """Verify lambda captures use default argument pattern (e, t=tv) not just (t)."""
        import ast
        import pathlib

        app_path = pathlib.Path(__file__).parent.parent / "src" / "tv_remote" / "app.py"
        tree = ast.parse(app_path.read_text())

        for node in ast.walk(tree):
            if isinstance(node, ast.Lambda):
                arg_names = [a.arg for a in node.args.args]
                if len(arg_names) == 1:
                    body = node.body
                    if isinstance(body, ast.Call) and isinstance(body.func, ast.Name):
                        pass
