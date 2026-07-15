"""
Firecrawl Search Provider

API Docs: https://docs.firecrawl.dev/
Endpoint: https://api.firecrawl.dev/v1/search
"""

from datetime import datetime
import json
from typing import Any

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider


@register_provider("firecrawl")
class FirecrawlProvider(BaseSearchProvider):
    """Firecrawl search provider"""

    name = "firecrawl"
    display_name = "Firecrawl"
    description = "Web search with markdown scraping"
    supports_answer = False
    BASE_URL = "https://api.firecrawl.dev/v1/search"
    API_KEY_ENV_VARS = ("FIRECRAWL_API_KEY", "SEARCH_API_KEY")

    def search(
        self,
        query: str,
        limit: int = 10,
        timeout: int = 60,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """
        Perform search using Firecrawl API.

        Args:
            query: Search query.
            limit: Maximum number of results to return.
            timeout: Request timeout in seconds.
            **kwargs: Additional options.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        self.logger.debug(f"Calling Firecrawl API limit={limit}")
        payload: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "scrapeOptions": {
                "formats": ["markdown"],
                "onlyMainContent": True
            }
        }

        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request_kwargs: dict[str, Any] = {"headers": headers, "json": payload}
        if self.proxy:
            request_kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}

        response = requests.post(self.BASE_URL, timeout=timeout, **request_kwargs)

        if response.status_code != 200:
            try:
                error_data = response.json()
            except (json.JSONDecodeError, ValueError):
                error_data = {"error": response.text}
            self.logger.error(f"Firecrawl API error: {response.status_code} - {error_data}")
            raise Exception(
                f"Firecrawl API error: {response.status_code} - "
                f"{error_data.get('error', response.text)}"
            )

        data = response.json()

        # Firecrawl returns { "success": True, "data": [ ... ] } or { "success": True, "data": { "results": [ ... ] } }
        res_list = []
        if isinstance(data.get("data"), list):
            res_list = data["data"]
        elif isinstance(data.get("data"), dict) and isinstance(data["data"].get("results"), list):
            res_list = data["data"]["results"]

        self.logger.debug(f"Firecrawl returned {len(res_list)} results")

        # Extract search results
        citations: list[Citation] = []
        search_results: list[SearchResult] = []

        for i, result in enumerate(res_list, 1):
            url = result.get("url", "")
            title = result.get("title", "")
            snippet = result.get("description", "")
            content = result.get("markdown", "") or result.get("content", "")

            # Sometimes title/description are in metadata object
            metadata_obj = result.get("metadata") or {}
            if not title and metadata_obj.get("title"):
                title = metadata_obj.get("title")
            if not snippet and metadata_obj.get("description"):
                snippet = metadata_obj.get("description")

            sr = SearchResult(
                title=title,
                url=url,
                snippet=snippet,
                content=content,
            )
            search_results.append(sr)

            citations.append(
                Citation(
                    id=i,
                    reference=f"[{i}]",
                    url=url,
                    title=title,
                    snippet=snippet,
                    content=content,
                )
            )

        metadata: dict[str, Any] = {
            "finish_reason": "stop",
            "limit": limit,
        }

        response_obj = WebSearchResponse(
            query=query,
            answer="",
            provider="firecrawl",
            timestamp=datetime.now().isoformat(),
            model="firecrawl-search",
            citations=citations,
            search_results=search_results,
            usage={},
            metadata=metadata,
        )

        return response_obj
