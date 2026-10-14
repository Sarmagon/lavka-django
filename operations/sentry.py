from urllib.parse import urlsplit, urlunsplit


def scrub_event(event, hint):
    # Requests and breadcrumbs can contain addresses, payment numbers and signed media URLs.
    event.pop("user", None)
    event.pop("extra", None)
    event.pop("breadcrumbs", None)
    request = event.get("request", {})
    for field in ("data", "cookies", "headers", "query_string", "env"):
        request.pop(field, None)
    if request.get("url"):
        parts = urlsplit(request["url"])
        request["url"] = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return event
