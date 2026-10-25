"""Deliver an alert. Channel from config.json "notify": print | telegram | ntfy | webhook (RadarKit's channels). Message text
comes from templates/<event>.txt ({company}, {n}, {roles} placeholders); secrets come from the environment, never the config."""
from radarkit import http, notify, template

from .paths import TEMPLATES


def render(event, **vars):
    return template.render(TEMPLATES, event, **vars)


def deliver(cfg, event, **vars):
    """True when the message went out. Raises on a delivery failure so the caller can keep the match unsent."""
    n = {"channel": "print", "title": "jobradar", **cfg.get("notify", {})}
    return http.run(notify.deliver(n, render(event, **vars), event, **vars))
