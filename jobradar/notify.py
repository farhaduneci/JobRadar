"""Deliver an alert. Channel from config.json "notify": print | telegram | ntfy | webhook. Message text comes from
templates/<event>.txt ({company}, {n}, {roles} placeholders); secrets come from the environment, never the config."""
import json, os, urllib.parse, urllib.request

from .paths import TEMPLATES


def render(event, **vars):
    text = open(os.path.join(TEMPLATES, event + ".txt")).read().strip()
    for k, v in vars.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def post(url, data, headers):
    req = urllib.request.Request(url, data, headers)
    urllib.request.urlopen(req, timeout=30).read()


def deliver(cfg, event, **vars):
    """True when the message went out. Raises on a delivery failure so the caller can keep the match unsent."""
    n = cfg.get("notify", {"channel": "print"})
    text = render(event, **vars)
    ch = n["channel"]
    if ch == "print":
        print(text)
    elif ch == "telegram":
        tok, chat = os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
        post(f"https://api.telegram.org/bot{tok}/sendMessage",
             urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode(), {})
    elif ch == "ntfy":
        post(f"{n.get('server', 'https://ntfy.sh')}/{n['topic']}", text.encode(), {"Title": f"jobradar: {event}"})
    elif ch == "webhook":
        post(n["url"], json.dumps({"event": event, "text": text, **vars}).encode(), {"Content-Type": "application/json"})
    else:
        raise SystemExit(f"unknown notify channel {ch!r}")
    return True
