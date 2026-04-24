from __future__ import annotations

from importlib.resources import files

from jinja2 import Environment, StrictUndefined

_ENVIRONMENT = Environment(
    autoescape=False,
    undefined=StrictUndefined,
    variable_start_string="[[",
    variable_end_string="]]",
)


def render_template(name: str, **values: str) -> str:
    template = files("ahadiff.install.templates").joinpath(name).read_text(encoding="utf-8")
    return _ENVIRONMENT.from_string(template).render(**values)
