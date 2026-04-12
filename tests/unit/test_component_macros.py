"""Tests for the Jinja2 component macro library (macros/components.html).

Each test renders a macro and asserts required a11y attributes are present.
"""

import os

import pytest
from jinja2 import Environment, FileSystemLoader


@pytest.fixture()
def jinja_env():
    """Create a Jinja2 environment pointing at the templates directory."""
    templates_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "src", "templates"
    )
    return Environment(
        loader=FileSystemLoader(os.path.abspath(templates_dir)),
        autoescape=True,
        extensions=["jinja2.ext.do"],
    )


@pytest.fixture()
def render(jinja_env):
    """Helper that renders a template string with components imported."""

    def _render(source, **ctx):
        tpl = jinja_env.from_string(
            "{% from 'macros/components.html' import button, form_field, "
            "modal, status_chip, card %}\n" + source
        )
        return tpl.render(**ctx)

    return _render


# -- button macro --


class TestButton:
    def test_default_type_attribute(self, render):
        html = render("{{ button('Click me') }}")
        assert 'type="button"' in html
        assert "Click me" in html

    def test_submit_type(self, render):
        html = render("{{ button('Send', type='submit') }}")
        assert 'type="submit"' in html

    def test_variant_class(self, render):
        html = render("{{ button('Go', variant='is-secondary') }}")
        assert "is-secondary" in html

    def test_primary_variant_no_extra_class(self, render):
        html = render("{{ button('Go') }}")
        assert 'class="action-button"' in html

    def test_disabled(self, render):
        html = render("{{ button('Nope', disabled=True) }}")
        assert "disabled" in html

    def test_extra_attrs(self, render):
        html = render("""{{ button('Act', attrs={'aria-describedby': 'help1'}) }}""")
        assert 'aria-describedby="help1"' in html


# -- form_field macro --


class TestFormField:
    def test_label_present(self, render):
        html = render("{{ form_field('email', 'Email address') }}")
        assert "<label" in html
        assert 'for="email"' in html
        assert "Email address" in html

    def test_required_aria(self, render):
        html = render("{{ form_field('name', 'Name', required=True) }}")
        assert "required" in html
        assert 'aria-required="true"' in html

    def test_help_text_describedby(self, render):
        html = render(
            "{{ form_field('pw', 'Password', type='password', help_text='Min 8 chars') }}"
        )
        assert 'aria-describedby="pw-help"' in html
        assert 'id="pw-help"' in html
        assert "Min 8 chars" in html

    def test_error_aria_invalid(self, render):
        html = render("{{ form_field('age', 'Age', error='Too young') }}")
        assert 'aria-invalid="true"' in html
        assert 'role="alert"' in html
        assert "Too young" in html

    def test_value_set(self, render):
        html = render("{{ form_field('city', 'City', value='Paris') }}")
        assert 'value="Paris"' in html

    def test_custom_id(self, render):
        html = render("{{ form_field('x', 'X', id='custom_id') }}")
        assert 'id="custom_id"' in html
        assert 'for="custom_id"' in html

    def test_help_and_error_both_describedby(self, render):
        html = render("{{ form_field('f', 'F', help_text='Hint', error='Bad') }}")
        assert "f-help" in html
        assert "f-error" in html
        assert 'aria-describedby="f-help f-error"' in html


# -- modal macro --


class TestModal:
    def test_role_dialog(self, render):
        html = render("{% call modal('testModal', 'Test Title') %}body{% endcall %}")
        assert 'role="dialog"' in html

    def test_aria_modal(self, render):
        html = render("{% call modal('testModal', 'Test Title') %}body{% endcall %}")
        assert 'aria-modal="true"' in html

    def test_aria_labelledby(self, render):
        html = render("{% call modal('myModal', 'My Title') %}content{% endcall %}")
        assert 'aria-labelledby="myModalTitle"' in html
        assert 'id="myModalTitle"' in html
        assert "My Title" in html

    def test_close_button(self, render):
        html = render("{% call modal('m1', 'T') %}b{% endcall %}")
        assert 'aria-label="Close"' in html

    def test_body_rendered(self, render):
        html = render("{% call modal('m2', 'T') %}<p>Hello</p>{% endcall %}")
        assert "<p>Hello</p>" in html


# -- status_chip macro --


class TestStatusChip:
    def test_default_variant(self, render):
        html = render("{{ status_chip('Online') }}")
        assert "status-chip" in html
        assert "info" in html
        assert "Online" in html

    def test_custom_variant(self, render):
        html = render("{{ status_chip('Error', 'danger') }}")
        assert "danger" in html

    def test_success_variant(self, render):
        html = render("{{ status_chip('Active', 'success') }}")
        assert "success" in html


# -- card macro --


class TestCard:
    def test_title_rendered(self, render):
        html = render("{% call card('My Card') %}content{% endcall %}")
        assert "My Card" in html
        assert "status-card" in html

    def test_body_rendered(self, render):
        html = render("{% call card('C') %}<span>inner</span>{% endcall %}")
        assert "<span>inner</span>" in html

    def test_no_title(self, render):
        html = render("{% call card('') %}body{% endcall %}")
        assert "status-title" not in html
