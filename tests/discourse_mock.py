import json

import httpx
from helpers import FIXTURES

from feedback_ingest.adapters.http.httpx_client import HttpxClient


# Two search pages and their posts.json, whatever the date window asked for.
def discourse_http(fail_page: str | None = None) -> HttpxClient:
    def handle(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if request.url.path == "/search.json":
            if params["page"] == fail_page:
                return httpx.Response(503, text="slow down")
            page = FIXTURES / f"discourse/pull/search_page{params['page']}.json"
            return httpx.Response(200, content=page.read_bytes())
        topic = FIXTURES / f"discourse/pull/posts_topic_{request.url.path.split('/')[2]}.json"
        wanted = {int(i) for i in params.get_list("post_ids[]")}
        posts = json.loads(topic.read_text())["post_stream"]["posts"]
        kept = [p for p in posts if p["id"] in wanted]
        return httpx.Response(200, json={"post_stream": {"posts": kept}})

    return HttpxClient(transport=httpx.MockTransport(handle))
