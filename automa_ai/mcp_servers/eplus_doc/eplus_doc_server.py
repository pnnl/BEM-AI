#!/usr/bin/env python3
"""
EnergyPlus Documentation Search FastMCP Server with SSE Transport

This FastMCP server provides search tools specifically for the EnergyPlus Input/Output Reference
documentation at https://bigladdersoftware.com/epx/docs/25-1/input-output-reference/
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup
from mcp.server import FastMCP
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("energyplus-docs-fastmcp")

EPLUS_DOC_URL = "https://bigladdersoftware.com/epx/docs/25-1/input-output-reference/"

@dataclass
class SearchResult:
    title: str
    url: str
    content_preview: str
    section: str
    relevance_score: float

@dataclass
class CachedPage:
    url: str
    title: str
    content: str
    last_updated: datetime
    section: str

# Pydantic models for FastMCP
class SearchQuery(BaseModel):
    query: str = Field(..., description="Search query for EnergyPlus documentation")
    max_results: int = Field(10, description="Maximum number of results to return", ge=1, le=50)

class PageDetailsQuery(BaseModel):
    url: str = Field(..., description="Full URL of the EnergyPlus documentation page")

class DiscoveryQuery(BaseModel):
    max_pages: int = Field(100, description="Maximum number of pages to discover", ge=10, le=500)

class EnergyPlusDocsSearcher:
    def __init__(self):
        self.base_url = EPLUS_DOC_URL
        self.session: Optional[aiohttp.ClientSession] = None
        self.page_cache: Dict[str, CachedPage] = {}
        self.cache_duration = timedelta(hours=24)  # Cache pages for 24 hours
        self.sitemap: List[str] = []

    async def initialize(self):
        """Initialize the HTTP session"""
        if not self.session:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={'User-Agent': 'EnergyPlus-Docs-FastMCP-Server/1.0'}
            )

    async def cleanup(self):
        """Clean up resources"""
        if self.session:
            await self.session.close()
            self.session = None

    async def discover_pages(self, max_pages: int = 100) -> List[str]:
        """Discover pages by crawling the documentation structure"""
        await self.initialize()

        discovered_urls = set()
        to_crawl = [self.base_url]
        crawled = set()

        while to_crawl and len(discovered_urls) < max_pages:
            current_url = to_crawl.pop(0)
            if current_url in crawled:
                continue

            try:
                crawled.add(current_url)
                async with self.session.get(current_url) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')

                    # Find all internal links
                    for link in soup.find('a', href=True):
                        href = link['href']
                        full_url = urljoin(current_url, href)

                        # Only include URLs from the target domain
                        if self._is_valid_url(full_url):
                            discovered_urls.add(full_url)
                            if full_url not in crawled and len(to_crawl) < 50:
                                to_crawl.append(full_url)
            except Exception as e:
                logger.warning(f"Error crawling {current_url}: {e}")

            self.sitemap = list(discovered_urls)
            return self.sitemap

    def _is_valid_url(self, url: str) -> bool:
        """Check if URL is within the target domain"""
        parsed = urlparse(url)
        return (
                parsed.netloc == "bigladdersoftware.com" and
                "/epx/docs/25-1/input-output-reference/" in parsed.path and
                not parsed.fragment  # Exclude anchor links
        )

    async def fetch_page_content(self, url: str) -> Optional[CachedPage]:
        """Fetch and cache page content"""
        await self.initialize()

        # Check cache first
        if url in self.page_cache:
            cached = self.page_cache[url]
            if datetime.now() - cached.last_updated < self.cache_duration:
                return cached
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')

                    # Extract title
                    title = soup.find('title')
                    title_text = title.get_text().strip() if title else url.split('/')[-1]

                    # Extract main content
                    content_elements = soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'td'])
                    content_text = ' '.join([elem.get_text().strip() for elem in content_elements])

                    # Determine section from URL or content
                    section = self._extract_section(url, soup)

                    # Cache the page
                    cached_page = CachedPage(
                        url=url,
                        title=title_text,
                        content=content_text,
                        last_updated=datetime.now(),
                        section=section
                    )
                    self.page_cache[url] = cached_page
                    return cached_page

        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")

        return None

    def _extract_section(self, url: str, soup: BeautifulSoup) -> str:
        """Extract section name from URL or page content"""
        # Try to get section from URL path
        path_parts = url.replace(self.base_url, '').split('/')
        if path_parts and path_parts[0]:
            return path_parts[0].replace('-', ' ').title()

        # Try to get section from page navigation or headings
        nav = soup.find('nav') or soup.find('div', class_='navigation')
        if nav:
            nav_text = nav.get_text().strip()
            if nav_text:
                return nav_text.split('\n')[0][:50]

        return "General"

    async def search_content(self, query: str, max_results: int = 10):
        """Search through cached content"""
        if not self.sitemap:
            await self.discover_pages()

        results = []
        query_terms = query.lower().split()

        # Fetch content for all pages if not already cached
        for url in self.sitemap[:50]:# limit to first 50
            page = await self.fetch_page_content(url)
            if page:
                score = self._calculate_relevance(page, query_terms)
                if score > 0:
                    preview = self._create_preview(page.content, query_terms)
                    results.append(SearchResult(
                        title=page.title,
                        url=page.url,
                        content_preview=preview,
                        section=page.section,
                        relevance_score=score
                    ))
        # Sort by relevance score and return top results
        results.sort(key=lambda x: x.relevance_score, reverse=True)
        return results[:max_results]

    def _calculate_relevance(self, page:CachedPage, query_terms: List[str]):
        """Calculate relevance score for a page based on query terms"""
        content_lower = page.content.lower()
        title_lower = page.title.lower()

        score = 0.0

        for term in query_terms:
            # Higher weight for title matches
            title_matches = title_lower.count(term)
            score += title_matches * 10

            # Regular content matches
            content_matches = content_lower.count(term)
            score += content_matches * 1

            # Bonus for exact phrase in title
            if term in title_lower:
                score += 5
        return score

    def _create_preview(self, content: str, query_terms: List[str]) -> str:
        """Create a preview snippet highlighting relevant content"""
        content_lower = content.lower()

        # Find the best position to create preview around query terms
        best_pos = 0
        best_score = 0

        for term in query_terms:
            pos = content_lower.find(term)
            if pos != -1:
                local_score = sum(1 for t in query_terms if t in content_lower[max(0, pos - 100):pos + 100])
                if local_score > best_score:
                    best_score = local_score
                    best_pos = pos
        # Extract preview around the best position
        start = max(0, best_pos - 150)
        end = min(len(content), best_pos + 150)
        preview = content[start:end].strip()

        # Add ellipsis if truncated
        if start > 0:
            preview = "..." + preview
        if end < len(content):
            preview = preview + "..."

        return preview[:300]  # Limit preview length


    async def get_page_details(self, url: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific page"""
        page = await self.fetch_page_content(url)
        if page:
            return {
                "url": page.url,
                "title": page.title,
                "section": page.section,
                "content": page.content,
                "last_updated": page.last_updated.isoformat(),
                "word_count": len(page.content.split())
            }
        return None

############ MCP server #################

def serve(host, port, transport):
    """Initialize and runs the agent cards mcp_servers server.
    Args:
        host: The hostname or IP address to bind the server to.
        port: The port number to bind the server to.
        transport: The transport mechanism for the MCP server (e.g., 'stdio', 'sse')

    Raises:
        ValueError
    """
    logger.info("Starting EnergyPlus Docs Search MCP Server")
    mcp = FastMCP("eplus-doc-mcp", host=host, port=port)

    # Global searcher instance
    searcher = EnergyPlusDocsSearcher()

    @mcp.tool()
    async def search_energyplus_docs(params: SearchQuery) -> str:
        """Search through EnergyPlus Input/Output Reference documentation with intelligent ranking"""
        try:
            results = await searcher.search_content(params.query, params.max_results)

            if not results:
                return f"No results found for query: '{params.query}'."

            # Format results as JSON for better structure
            formatted_results = {
                "query": params.query,
                "total_results": len(results),
                "results": []
            }

            for i, result in enumerate(results, 1):
                formatted_results["results"].append({
                    "rank": i,
                    "title": result.title,
                    "section": result.section,
                    "url": result.url,
                    "relevance_score": round(result.relevance_score, 1),
                    "preview": result.content_preview
                })

            return json.dumps(formatted_results, indent=2)
        except Exception as e:
            logger.error(f"Error in search_energyplus_docs: {e}")
            return f"Error performing search: {str(e)}"

    @mcp.tool()
    async def get_page_details(params: PageDetailsQuery) -> str:
        """Get comprehensive information about a specific EnergyPlus documentation page"""
        try:
            details = await searcher.get_page_details(params.url)

            if not details:
                return f"Could not retrieve details for URL: {params.url}"

            # Format as structured JSON
            formatted_details = {
                "page_info": {
                    "title": details['title'],
                    "section": details['section'],
                    "url": details['url'],
                    "word_count": details['word_count'],
                    "last_updated": details['last_updated']
                },
                "content_preview": details['content'][:2000] + "..." if len(details['content']) > 2000 else details[
                    'content']
            }
            return json.dumps(formatted_details, indent=2)
        except Exception as e:
            logger.error(f"Error in get_page_details: {e}")
            return f"Error retrieving page details: {str(e)}"

    @mcp.tool()
    async def discover_documentation_structure(params: DiscoveryQuery) -> str:
        """Discover and map the structure of the EnergyPlus documentation site"""
        try:
            discovered_urls = await searcher.discover_pages(params.max_pages)

            # Group by section for better organization
            sections = {}
            for url in discovered_urls:
                path = url.replace(searcher.base_url, '')
                section = path.split('/')[0] if path else 'root'
                if section not in sections:
                    sections[section] = []
                sections[section].append(url)

            # Format as structured JSON
            structure = {
                "discovery_info": {
                    "total_pages": len(discovered_urls),
                    "total_sections": len(sections),
                    "base_url": searcher.base_url
                },
                "sections": {}
            }
            for section, urls in sections.items():
                structure["sections"][section.replace('-', ' ').title()] = {
                    "page_count": len(urls),
                    "pages": [
                        {
                            "name": url.split('/')[-1] or url.split('/')[-2],
                            "url": url
                        } for url in urls[:20]  # Limit to first 20 per section
                    ]
                }
                if len(urls) > 20:
                    structure["sections"][section.replace('-', ' ').title()]["additional_pages"] = len(urls) - 20

            return json.dumps(structure, indent=2)
        except Exception as e:
            logger.error(f"Error in discover_documentation_structure: {e}")
            return f"Error discovering documentation structure: {str(e)}"

    # Cleanup function for graceful shutdown
    async def cleanup_searcher():
        """Clean up searcher resources"""
        await searcher.cleanup()

    logger.info(f"EnergyPlus Doc MCP Server at {host}:{port} and transport {transport}")
    mcp.run(transport=transport)


