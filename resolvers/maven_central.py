"""
Maven Central API integration for gradleInit.

Provides version lookup for dependencies hosted on Maven Central.
"""

import urllib.request
import urllib.parse
import json
import time
from typing import Optional, Dict, Any, List
from pathlib import Path


class MavenCentral:
    """Maven Central Search API client with caching."""

    SEARCH_URL = "https://search.maven.org/solrsearch/select"
    CACHE_TTL = 3600  # 1 hour

    def __init__(self, cache_dir: Optional[Path] = None):
        if cache_dir is None:
            cache_dir = Path.home() / '.gradleInit' / 'cache' / 'maven'
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Dict[str, Any]] = {}

    def get_name(self) -> str:
        return "Maven Central"

    def get_latest_version(self, group_id: str, artifact_id: str) -> Optional[str]:
        """Get latest version of an artifact."""
        cache_key = f"{group_id}:{artifact_id}"

        # Check memory cache
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if time.time() - cached['timestamp'] < self.CACHE_TTL:
                return cached['version']

        # Check file cache
        cache_file = self.cache_dir / f"{group_id}_{artifact_id}.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding='utf-8'))
                if time.time() - data.get('timestamp', 0) < self.CACHE_TTL:
                    self._cache[cache_key] = data
                    return data['version']
            except (json.JSONDecodeError, KeyError):
                pass

        # Query Maven Central
        version = self._query_maven_central(group_id, artifact_id)

        if version:
            cache_data = {
                'version': version,
                'timestamp': time.time(),
                'group_id': group_id,
                'artifact_id': artifact_id
            }
            self._cache[cache_key] = cache_data
            try:
                cache_file.write_text(json.dumps(cache_data), encoding='utf-8')
            except OSError:
                pass

        return version

    def _query_maven_central(self, group_id: str, artifact_id: str) -> Optional[str]:
        """Query Maven Central Search API."""
        query = f'g:"{group_id}" AND a:"{artifact_id}"'
        params = {'q': query, 'rows': 1, 'wt': 'json', 'core': 'gav'}
        url = f"{self.SEARCH_URL}?{urllib.parse.urlencode(params)}"

        try:
            request = urllib.request.Request(url, headers={
                'User-Agent': 'gradleInit/1.0',
                'Accept': 'application/json'
            })
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                docs = data.get('response', {}).get('docs', [])
                if docs:
                    return docs[0].get('v')
        except Exception:
            pass
        return None

    def get_versions(self, group_id: str, artifact_id: str, limit: int = 10) -> List[str]:
        """Get list of available versions (newest first)."""
        query = f'g:"{group_id}" AND a:"{artifact_id}"'
        params = {'q': query, 'rows': limit, 'wt': 'json', 'core': 'gav'}
        url = f"{self.SEARCH_URL}?{urllib.parse.urlencode(params)}"

        try:
            request = urllib.request.Request(url, headers={
                'User-Agent': 'gradleInit/1.0',
                'Accept': 'application/json'
            })
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                docs = data.get('response', {}).get('docs', [])
                return [doc.get('v') for doc in docs if doc.get('v')]
        except Exception:
            pass
        return []

    def clear_cache(self):
        """Clear all cached data."""
        self._cache.clear()
        if self.cache_dir.exists():
            for f in self.cache_dir.glob('*.json'):
                try:
                    f.unlink()
                except OSError:
                    pass


__all__ = ['MavenCentral']
