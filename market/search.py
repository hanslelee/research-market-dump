"""Web search providers for the market agent. Each returns [{"url", "title"}].

config.json -> market.search.provider:
  "none"    no search; the agent uses seed_urls and competitor urls only (works without any key)
  "tavily"  Tavily Search API, key in env var market.search.key_name (default TAVILY_API_KEY)
  "brave"   Brave Search API, key in env var market.search.key_name (e.g. BRAVE_API_KEY)
"""
import json
import os
import urllib.parse
import urllib.request


class SearchUnavailable(RuntimeError):
    pass


def _key(sc):
    key = os.environ.get(sc.get("key_name", "TAVILY_API_KEY"), "")
    if not key:
        raise SearchUnavailable(f"search key {sc.get('key_name')} is not set")
    return key


def tavily(query, sc):
    body = json.dumps({"api_key": _key(sc), "query": query, "max_results": sc.get("per_query", 5),
                       "search_depth": "basic"}).encode()
    req = urllib.request.Request("https://api.tavily.com/search", data=body,
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {_key(sc)}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    return [{"url": x.get("url", ""), "title": x.get("title", "")} for x in data.get("results", []) if x.get("url")]


def brave(query, sc):
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
        {"q": query, "count": sc.get("per_query", 5)})
    req = urllib.request.Request(url, headers={"Accept": "application/json", "X-Subscription-Token": _key(sc)})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    return [{"url": x.get("url", ""), "title": x.get("title", "")} for x in (data.get("web") or {}).get("results", [])]


PROVIDERS = {"tavily": tavily, "brave": brave, "none": lambda q, sc: []}


_warned = set()


def search(query, sc, log=print):
    """Search results, or [] (the agent then uses seed and competitor urls only). Never stops the run."""
    fn = PROVIDERS.get(sc.get("provider", "none"))
    if not fn:
        raise SearchUnavailable(f"unknown provider {sc.get('provider')!r}")
    try:
        return fn(query, sc)
    except SearchUnavailable as e:
        if str(e) not in _warned:
            _warned.add(str(e))
            log(f"search: {e}; using seed and competitor urls only")
        return []
    except Exception as e:
        log(f"search: '{query}' failed ({e})")
        return []
