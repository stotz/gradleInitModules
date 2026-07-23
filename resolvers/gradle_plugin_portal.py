"""
Gradle Plugin Portal resolver.

The Plugin Portal serves a standard Maven repository layout under
https://plugins.gradle.org/m2, so this resolver is MavenCentral with a
different repository URL and cache. Plugin coordinates are the plugin
marker artifact:

    groupId    = <plugin id>
    artifactId = <plugin id>.gradle.plugin

Needed because some Gradle plugins (e.g. org.cyclonedx.bom) publish current
releases only to the Portal, while Maven Central carries stale mirrors.
"""

from pathlib import Path
from typing import Optional

from .maven_central import MavenCentral


class GradlePluginPortal(MavenCentral):
    """Version resolver for the Gradle Plugin Portal Maven repository."""

    REPO_URL = "https://plugins.gradle.org/m2"

    def __init__(self, cache_dir: Optional[Path] = None):
        if cache_dir is None:
            cache_dir = Path.home() / '.gradleInit' / 'cache' / 'plugin-portal'
        super().__init__(cache_dir=cache_dir)

    def get_name(self) -> str:
        return "Gradle Plugin Portal"

    def _fetch_via_search_api(self, group_id: str, artifact_id: str):
        # The Plugin Portal has no Search API; a 404 on maven-metadata.xml
        # simply means the plugin id does not exist there.
        return None
