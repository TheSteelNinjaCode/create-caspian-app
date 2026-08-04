"""Unit tests for the pure helper functions in `main.py`.

These cover the app-owned logic that has no external dependencies: env
parsing, query-param coercion, and the component-deferral HTML transform.
"""

import inspect
from typing import Optional

import main


class TestEnvParsing:
    def test_csv_env_splits_and_strips(self, monkeypatch):
        monkeypatch.setenv("SOME_LIST", " a , b ,, c ")
        assert main._csv_env("SOME_LIST") == ["a", "b", "c"]

    def test_csv_env_missing_is_empty(self, monkeypatch):
        monkeypatch.delenv("SOME_LIST", raising=False)
        assert main._csv_env("SOME_LIST") == []

    def test_bool_env_truthy_values(self, monkeypatch):
        for raw in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv("FLAG", raw)
            assert main._bool_env("FLAG") is True

    def test_bool_env_falsy_and_default(self, monkeypatch):
        monkeypatch.setenv("FLAG", "nope")
        assert main._bool_env("FLAG") is False
        monkeypatch.delenv("FLAG", raising=False)
        assert main._bool_env("FLAG", default=True) is True


class TestScalarCoercion:
    def test_int_and_float(self):
        assert main._coerce_scalar("42", int) == 42
        assert main._coerce_scalar("3.5", float) == 3.5

    def test_bool_variants(self):
        assert main._coerce_scalar("yes", bool) is True
        assert main._coerce_scalar("off", bool) is False

    def test_none_passthrough(self):
        assert main._coerce_scalar(None, int) is None

    def test_bad_int_falls_back_to_string(self):
        # Best-effort coercion: unparseable input returns the raw string.
        assert main._coerce_scalar("not-a-number", int) == "not-a-number"

    def test_optional_is_unwrapped(self):
        assert main._coerce_scalar("7", Optional[int]) == 7


class TestUnwrapOptional:
    def test_unwraps_optional(self):
        assert main._unwrap_optional(Optional[int]) is int

    def test_leaves_plain_type(self):
        assert main._unwrap_optional(str) is str


class TestQueryParamCoercion:
    def _param(self, annotation):
        return inspect.Parameter(
            "x", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=annotation
        )

    def test_list_param(self):
        from starlette.datastructures import QueryParams
        from starlette.requests import Request

        scope = {
            "type": "http",
            "query_string": b"x=1&x=2&x=3",
            "headers": [],
        }
        request = Request(scope)
        # sanity: the request exposes the multi-value list
        assert isinstance(request.query_params, QueryParams)
        result = main._coerce_query_param(request, "x", self._param(list[int]))
        assert result == [1, 2, 3]

    def test_scalar_param(self):
        from starlette.requests import Request

        scope = {"type": "http", "query_string": b"x=10", "headers": []}
        request = Request(scope)
        result = main._coerce_query_param(request, "x", self._param(int))
        assert result == 10


class TestDeferComponentRoots:
    def test_no_component_is_untouched(self):
        html = "<div>hello</div>"
        assert main.defer_component_roots(html) == html

    def test_component_root_is_wrapped_in_template(self):
        # The transform operates on a full document body, as in production.
        html = '<body><div pp-component="abc"><span>x</span></div></body>'
        out = main.defer_component_roots(html)
        assert "<template" in out
        assert 'pp-component="abc"' in out

    def test_brace_entities_are_double_encoded_inside_deferred_templates(self):
        html = (
            '<body><div pp-component="abc" '
            'title="&#123;attr&#125;" '
            'class="probe &#x7b;active&#x7d;">'
            "&lbrace;text&rbrace;"
            "</div><p>&#123;outside&#125;</p></body>"
        )

        out = main.defer_component_roots(html)

        assert 'title="&amp;#123;attr&amp;#125;"' in out
        assert 'class="probe &amp;#x7b;active&amp;#x7d;"' in out
        assert "&amp;lbrace;text&amp;rbrace;" in out
        assert "<p>&#123;outside&#125;</p>" in out

    def test_finalize_html_defers_and_preserves_plain_scripts(self):
        html = '<body><div pp-component="abc"><script>console.log(1)</script></div></body>'
        out = main.finalize_html(html)
        assert "<script>console.log(1)</script>" in out
        assert "<template" in out


class TestDevConsoleBridge:
    """The dev log bridge must be dev-only by code, not by convention.

    `CASPIAN_BROWSER_SYNC_PORT` is normally set only by settings/python-server.ts,
    which is why the tag does not reach production in practice. That is a fact
    about who sets the variable, not an enforcement -- so a stray value in a
    production environment used to inject `<script src="/__pp-devlog.js">` into
    every page, where BrowserSync is not running to serve it.
    """

    PAGE = "<html><head><title>t</title></head><body>x</body></html>"

    def test_injects_in_development_when_port_is_set(self, monkeypatch):
        monkeypatch.setattr(main, "IS_PRODUCTION", False)
        monkeypatch.setenv("CASPIAN_BROWSER_SYNC_PORT", "5090")

        assert "__pp-devlog.js" in main._inject_dev_console_bridge(self.PAGE)

    def test_never_injects_in_production(self, monkeypatch):
        """The guard under test: set variable, production, must stay out."""
        monkeypatch.setattr(main, "IS_PRODUCTION", True)
        monkeypatch.setenv("CASPIAN_BROWSER_SYNC_PORT", "5090")

        assert main._inject_dev_console_bridge(self.PAGE) == self.PAGE

    def test_skips_when_port_is_unset(self, monkeypatch):
        monkeypatch.setattr(main, "IS_PRODUCTION", False)
        monkeypatch.delenv("CASPIAN_BROWSER_SYNC_PORT", raising=False)

        assert main._inject_dev_console_bridge(self.PAGE) == self.PAGE

    def test_does_not_double_inject(self, monkeypatch):
        monkeypatch.setattr(main, "IS_PRODUCTION", False)
        monkeypatch.setenv("CASPIAN_BROWSER_SYNC_PORT", "5090")

        once = main._inject_dev_console_bridge(self.PAGE)
        twice = main._inject_dev_console_bridge(once)

        assert twice == once
        assert twice.count("__pp-devlog.js") == 1
