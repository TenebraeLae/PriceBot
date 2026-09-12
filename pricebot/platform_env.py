from urllib.parse import quote

LOOPBACK = ("localhost", "127.0.0.1")


def is_loopback_url(url: str) -> bool:
    lowered = url.lower()
    return any(host in lowered for host in LOOPBACK)


def public_https_base(domain: str) -> str:
    host = domain.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    return f"https://{host}" if host else ""


def compose_database_url(
    current: str,
    *,
    host: str,
    user: str,
    password: str,
    port: int,
    database: str,
) -> str:
    if not host:
        return current
    if current and not is_loopback_url(current):
        return current
    login = quote(user, safe="")
    secret = quote(password, safe="")
    name = database or "pricebot"
    return f"postgresql+asyncpg://{login}:{secret}@{host}:{port}/{name}"


def compose_redis_url(current: str, *, host: str, password: str, port: int) -> str:
    if not host:
        return current
    if current and not is_loopback_url(current):
        return current
    auth = f":{quote(password, safe='')}@" if password else ""
    return f"redis://{auth}{host}:{port}/0"


def compose_public_urls(
    *,
    domain: str,
    public_base_url: str,
    webapp_url: str,
) -> tuple[str, str]:
    base = public_https_base(domain)
    if not base:
        return public_base_url, webapp_url
    if is_loopback_url(public_base_url):
        public_base_url = base
    if is_loopback_url(webapp_url) or not webapp_url.startswith("https://"):
        webapp_url = f"{base}/app/"
    return public_base_url, webapp_url
