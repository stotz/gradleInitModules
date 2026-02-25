"""
Maven Central integration for gradleInit.

Provides version lookup for dependencies hosted on Maven Central.
Uses direct maven-metadata.xml access instead of Search API for reliability.
"""

import urllib.request
import urllib.error
import urllib.parse
import json
import time
import re
import xml.etree.ElementTree as ET
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path


class MavenCentral:
    """
    Maven Central client using direct maven-metadata.xml access.
    
    This approach is more reliable than the Search API because:
    - No Solr index delay (always current)
    - No rate limiting issues
    - Stable XML format
    - Direct repository access
    """

    REPO_URL = "https://repo1.maven.org/maven2"
    CACHE_TTL = 3600  # 1 hour

    def __init__(self, cache_dir: Optional[Path] = None):
        if cache_dir is None:
            cache_dir = Path.home() / '.gradleInit' / 'cache' / 'maven'
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Dict[str, Any]] = {}

    def get_name(self) -> str:
        return "Maven Central"

    def _group_to_path(self, group_id: str) -> str:
        """Convert groupId to URL path (dots to slashes)."""
        return group_id.replace('.', '/')

    def _build_metadata_url(self, group_id: str, artifact_id: str) -> str:
        """Build URL for maven-metadata.xml."""
        group_path = self._group_to_path(group_id)
        return f"{self.REPO_URL}/{group_path}/{artifact_id}/maven-metadata.xml"

    def _parse_metadata_xml(self, xml_content: str) -> Dict[str, Any]:
        """
        Parse maven-metadata.xml content.
        
        Returns dict with:
            - latest: latest stable (non-prerelease) version
            - release: release version from metadata (may be prerelease)
            - versions: list of all versions (newest first after sorting)
        """
        try:
            root = ET.fromstring(xml_content)
            
            result = {
                'latest': None,
                'release': None,
                'versions': []
            }
            
            # Get release from metadata (informational, may be prerelease)
            release_elem = root.find('.//release')
            if release_elem is not None and release_elem.text:
                result['release'] = release_elem.text.strip()
            
            # Get all versions
            versioning = root.find('.//versioning/versions')
            if versioning is not None:
                versions = []
                for version_elem in versioning.findall('version'):
                    if version_elem.text:
                        versions.append(version_elem.text.strip())
                # Sort versions (newest first)
                result['versions'] = self._sort_versions(versions)
            
            # Always compute 'latest' as the newest stable version
            # (ignore <latest> element from XML as it often contains prereleases)
            if result['versions']:
                stable_versions = [v for v in result['versions'] 
                                   if not self._is_prerelease(v)]
                if stable_versions:
                    result['latest'] = stable_versions[0]
                else:
                    # No stable versions available, use newest overall
                    result['latest'] = result['versions'][0]
            
            return result
            
        except ET.ParseError:
            return {'latest': None, 'release': None, 'versions': []}

    def _is_prerelease(self, version: str) -> bool:
        """Check if version is a pre-release (alpha, beta, RC, SNAPSHOT, etc.)."""
        lower = version.lower()
        prerelease_markers = [
            'alpha', 'beta', 'rc', 'cr', 'snapshot', 
            'dev', 'preview', 'pre', 'milestone', 'm1', 'm2', 'm3',
            '-ea', 'ea+',  # Early Access (e.g., 27-ea+5)
        ]
        return any(marker in lower for marker in prerelease_markers)

    def _parse_version(self, version: str) -> Tuple[List[int], str]:
        """
        Parse version into comparable parts.
        
        Returns (numeric_parts, suffix) where:
            - numeric_parts: list of integers [major, minor, patch, ...]
            - suffix: any trailing non-numeric part
        """
        # Split on common delimiters
        match = re.match(r'^([\d.]+)(.*)$', version)
        if not match:
            return ([], version)
        
        numeric_str = match.group(1)
        suffix = match.group(2)
        
        parts = []
        for part in numeric_str.split('.'):
            try:
                parts.append(int(part))
            except ValueError:
                break
        
        return (parts, suffix)

    def _sort_versions(self, versions: List[str]) -> List[str]:
        """Sort versions newest first."""
        def version_key(v: str):
            parts, suffix = self._parse_version(v)
            # Pad with zeros for consistent comparison
            padded = parts + [0] * (10 - len(parts))
            # Pre-releases sort lower
            is_pre = 1 if self._is_prerelease(v) else 0
            return (padded, is_pre, suffix)
        
        return sorted(versions, key=version_key, reverse=True)

    def _get_cache_key(self, group_id: str, artifact_id: str) -> str:
        """Generate cache key."""
        return f"{group_id}:{artifact_id}"

    def _get_cache_file(self, group_id: str, artifact_id: str) -> Path:
        """Get cache file path."""
        safe_name = f"{group_id}_{artifact_id}".replace('.', '_')
        return self.cache_dir / f"{safe_name}.json"

    def _read_cache(self, group_id: str, artifact_id: str) -> Optional[Dict[str, Any]]:
        """Read from cache if valid."""
        cache_key = self._get_cache_key(group_id, artifact_id)
        
        # Check memory cache
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if time.time() - cached.get('timestamp', 0) < self.CACHE_TTL:
                return cached
        
        # Check file cache
        cache_file = self._get_cache_file(group_id, artifact_id)
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding='utf-8'))
                if time.time() - data.get('timestamp', 0) < self.CACHE_TTL:
                    self._cache[cache_key] = data
                    return data
            except (json.JSONDecodeError, KeyError, OSError):
                pass
        
        return None

    def _write_cache(self, group_id: str, artifact_id: str, data: Dict[str, Any]):
        """Write to cache."""
        cache_key = self._get_cache_key(group_id, artifact_id)
        cache_data = {
            **data,
            'timestamp': time.time(),
            'group_id': group_id,
            'artifact_id': artifact_id
        }
        
        self._cache[cache_key] = cache_data
        
        try:
            cache_file = self._get_cache_file(group_id, artifact_id)
            cache_file.write_text(json.dumps(cache_data), encoding='utf-8')
        except OSError:
            pass

    def _fetch_metadata(self, group_id: str, artifact_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch and parse maven-metadata.xml from Maven Central.
        Falls back to Search API if metadata.xml not found (404).
        """
        url = self._build_metadata_url(group_id, artifact_id)
        
        try:
            request = urllib.request.Request(url, headers={
                'User-Agent': 'gradleInit/1.0',
                'Accept': 'application/xml'
            })
            with urllib.request.urlopen(request, timeout=10) as response:
                xml_content = response.read().decode('utf-8')
                return self._parse_metadata_xml(xml_content)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Fallback to Search API
                return self._fetch_via_search_api(group_id, artifact_id)
            return None
        except Exception:
            return None

    def _fetch_via_search_api(self, group_id: str, artifact_id: str) -> Optional[Dict[str, Any]]:
        """
        Fallback: Fetch versions via Maven Central Search API.
        Used when maven-metadata.xml is not available (e.g., Gradle plugins).
        """
        search_url = "https://search.maven.org/solrsearch/select"
        query = f'g:"{group_id}" AND a:"{artifact_id}"'
        params = urllib.parse.urlencode({
            'q': query,
            'rows': 100,
            'wt': 'json',
            'core': 'gav'
        })
        url = f"{search_url}?{params}"
        
        try:
            request = urllib.request.Request(url, headers={
                'User-Agent': 'gradleInit/1.0',
                'Accept': 'application/json'
            })
            with urllib.request.urlopen(request, timeout=10) as response:
                import json
                data = json.loads(response.read().decode('utf-8'))
                docs = data.get('response', {}).get('docs', [])
                
                if not docs:
                    return None
                
                # Extract versions from search results
                versions = [doc.get('v') for doc in docs if doc.get('v')]
                if not versions:
                    return None
                
                # Sort versions (newest first)
                sorted_versions = self._sort_versions(versions)
                
                # Find latest stable version
                stable_versions = [v for v in sorted_versions 
                                   if not self._is_prerelease(v)]
                latest = stable_versions[0] if stable_versions else sorted_versions[0]
                
                return {
                    'latest': latest,
                    'release': latest,
                    'versions': sorted_versions
                }
        except Exception:
            return None

    def get_latest_version(self, group_id: str, artifact_id: str, 
                           include_prerelease: bool = False) -> Optional[str]:
        """
        Get latest version of an artifact.
        
        Args:
            group_id: Maven groupId (e.g., "org.junit.jupiter")
            artifact_id: Maven artifactId (e.g., "junit-jupiter")
            include_prerelease: If True, include alpha/beta/RC versions
        
        Returns:
            Latest version string, or None if not found
        """
        # Check cache
        cached = self._read_cache(group_id, artifact_id)
        if cached:
            if include_prerelease:
                return cached.get('versions', [None])[0]
            return cached.get('latest')
        
        # Fetch from Maven Central
        data = self._fetch_metadata(group_id, artifact_id)
        if not data:
            return None
        
        # Cache result
        self._write_cache(group_id, artifact_id, data)
        
        if include_prerelease:
            return data.get('versions', [None])[0]
        return data.get('latest')

    def get_versions(self, group_id: str, artifact_id: str, 
                     limit: int = 10,
                     include_prerelease: bool = False) -> List[str]:
        """
        Get list of available versions (newest first).
        
        Args:
            group_id: Maven groupId
            artifact_id: Maven artifactId
            limit: Maximum number of versions to return
            include_prerelease: If True, include alpha/beta/RC versions
        
        Returns:
            List of version strings, newest first
        """
        # Check cache
        cached = self._read_cache(group_id, artifact_id)
        if cached:
            versions = cached.get('versions', [])
        else:
            # Fetch from Maven Central
            data = self._fetch_metadata(group_id, artifact_id)
            if not data:
                return []
            
            # Cache result
            self._write_cache(group_id, artifact_id, data)
            versions = data.get('versions', [])
        
        # Filter pre-releases if needed
        if not include_prerelease:
            versions = [v for v in versions if not self._is_prerelease(v)]
        
        return versions[:limit]

    def get_matching_version(self, group_id: str, artifact_id: str,
                             constraint_type: str, constraint_value: Optional[str],
                             current_version: str) -> Optional[str]:
        """
        Get the best matching version for a constraint.
        
        Args:
            group_id: Maven groupId
            artifact_id: Maven artifactId
            constraint_type: One of 'latest', 'caret', 'tilde', 'gte', 'lte', 'gt', 'lt', 'range', 'wildcard'
            constraint_value: The constraint value (e.g., "1.2.3" for ^1.2.3)
            current_version: Current version (used as minimum for some constraints)
        
        Returns:
            Best matching version, or None if no match found
        """
        versions = self.get_versions(group_id, artifact_id, limit=100)
        if not versions:
            return None
        
        if constraint_type == 'latest':
            return versions[0] if versions else None
        
        # Parse current version for comparison
        curr_parts, _ = self._parse_version(current_version)
        
        for version in versions:
            v_parts, _ = self._parse_version(version)
            
            if constraint_type == 'caret':
                # ^1.2.3 means >=1.2.3 <2.0.0 (same major)
                c_parts, _ = self._parse_version(constraint_value or current_version)
                if not c_parts:
                    continue
                # Must have same major
                if v_parts and v_parts[0] == c_parts[0]:
                    # Must be >= constraint
                    if self._compare_versions(version, constraint_value or current_version) >= 0:
                        return version
            
            elif constraint_type == 'tilde':
                # ~1.2.3 means >=1.2.3 <1.3.0 (same major.minor)
                c_parts, _ = self._parse_version(constraint_value or current_version)
                if len(c_parts) < 2 or len(v_parts) < 2:
                    continue
                # Must have same major.minor
                if v_parts[0] == c_parts[0] and v_parts[1] == c_parts[1]:
                    # Must be >= constraint
                    if self._compare_versions(version, constraint_value or current_version) >= 0:
                        return version
            
            elif constraint_type == 'gte':
                if self._compare_versions(version, constraint_value) >= 0:
                    return version
            
            elif constraint_type == 'gt':
                if self._compare_versions(version, constraint_value) > 0:
                    return version
            
            elif constraint_type == 'lte':
                if self._compare_versions(version, constraint_value) <= 0:
                    return version
            
            elif constraint_type == 'lt':
                if self._compare_versions(version, constraint_value) < 0:
                    return version
            
            elif constraint_type == 'wildcard':
                # 1.x or 1.2.x
                c_parts, _ = self._parse_version(constraint_value)
                match = True
                for i, c_part in enumerate(c_parts):
                    if i >= len(v_parts) or v_parts[i] != c_part:
                        match = False
                        break
                if match:
                    return version
            
            elif constraint_type == 'range':
                # >=1.0 <2.0
                match = re.match(r'>=([^\s<]+)\s*<([^\s]+)', constraint_value or '')
                if match:
                    lower = match.group(1)
                    upper = match.group(2)
                    if (self._compare_versions(version, lower) >= 0 and
                        self._compare_versions(version, upper) < 0):
                        return version
        
        return None

    def _compare_versions(self, v1: str, v2: str) -> int:
        """Compare two versions. Returns -1 if v1<v2, 0 if equal, 1 if v1>v2."""
        p1, _ = self._parse_version(v1)
        p2, _ = self._parse_version(v2)
        
        # Pad to same length
        max_len = max(len(p1), len(p2))
        p1 = p1 + [0] * (max_len - len(p1))
        p2 = p2 + [0] * (max_len - len(p2))
        
        for i in range(max_len):
            if p1[i] < p2[i]:
                return -1
            if p1[i] > p2[i]:
                return 1
        return 0

    def clear_cache(self):
        """Clear all cached data."""
        self._cache.clear()
        if self.cache_dir.exists():
            for f in self.cache_dir.glob('*.json'):
                try:
                    f.unlink()
                except OSError:
                    pass

    @staticmethod
    def url_from_mvnrepository(mvnrepository_url: str) -> Optional[Tuple[str, str]]:
        """
        Extract groupId and artifactId from mvnrepository.com URL.
        
        Args:
            mvnrepository_url: URL like "https://mvnrepository.com/artifact/org.junit.jupiter/junit-jupiter"
        
        Returns:
            Tuple of (group_id, artifact_id) or None if URL is invalid
        """
        match = re.search(r'/artifact/([^/]+)/([^/\s@]+)', mvnrepository_url)
        if match:
            return (match.group(1), match.group(2))
        return None


__all__ = ['MavenCentral']
