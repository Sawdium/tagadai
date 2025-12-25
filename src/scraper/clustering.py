"""
Build archetype clustering based on stat distributions.

Uses K-means clustering on normalized stat ratios to discover natural
build archetypes from fight data.
"""

import sqlite3
from pathlib import Path
from typing import Optional
import json
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from collections import defaultdict


def get_stat_vectors(
    db_path: Path,
    level_min: int = 1,
    level_max: int = 301,
    min_total_stats: int = 50,
) -> tuple[np.ndarray, list[dict]]:
    """
    Extract stat vectors from metadata for clustering.

    Args:
        db_path: Path to the fights database
        level_min: Minimum leek level to include
        level_max: Maximum leek level to include
        min_total_stats: Minimum total combat stats to filter out empty entries

    Returns:
        Tuple of (stat_matrix, metadata_list)
        - stat_matrix: numpy array of shape (n_samples, 4) with [str, agi, mag, res] ratios
        - metadata_list: list of dicts with leek_id, level, chips_used, weapons_used
    """
    conn = sqlite3.connect(db_path)

    # Get stats and equipment for each unique leek observation
    # Use the most recent observation per leek to avoid duplicates
    cur = conn.execute('''
        SELECT
            leek_id, level, strength, agility, magic, resistance,
            chips_used, weapons_used
        FROM fight_leek_metadata
        WHERE level >= ? AND level <= ?
        AND (strength + agility + magic + resistance) >= ?
        GROUP BY leek_id
        HAVING MAX(fight_id)
    ''', (level_min, level_max, min_total_stats))

    stats = []
    metadata = []

    for row in cur:
        leek_id, level, strength, agility, magic, resistance, chips_json, weapons_json = row

        # Compute total for normalization
        total = strength + agility + magic + resistance
        if total == 0:
            continue

        # Normalized ratios
        stat_vector = [
            strength / total,
            agility / total,
            magic / total,
            resistance / total,
        ]

        stats.append(stat_vector)
        metadata.append({
            'leek_id': leek_id,
            'level': level,
            'strength': strength,
            'agility': agility,
            'magic': magic,
            'resistance': resistance,
            'chips_used': json.loads(chips_json) if chips_json else [],
            'weapons_used': json.loads(weapons_json) if weapons_json else [],
        })

    conn.close()

    return np.array(stats), metadata


def cluster_builds(
    db_path: Path,
    n_clusters: int = 6,
    level_min: int = 1,
    level_max: int = 301,
    min_total_stats: int = 50,
) -> dict:
    """
    Perform K-means clustering on build stat distributions.

    Args:
        db_path: Path to the fights database
        n_clusters: Number of clusters to find
        level_min: Minimum leek level to include
        level_max: Maximum leek level to include
        min_total_stats: Minimum total combat stats

    Returns:
        Dict with cluster information:
        - clusters: list of cluster dicts with centroid, size, top_chips, top_weapons
        - labels: cluster assignment for each sample
        - sample_count: total samples clustered
    """
    # Get stat vectors
    stat_matrix, metadata = get_stat_vectors(
        db_path, level_min, level_max, min_total_stats
    )

    if len(stat_matrix) < n_clusters:
        return {
            'error': f'Not enough samples ({len(stat_matrix)}) for {n_clusters} clusters',
            'sample_count': len(stat_matrix),
        }

    # Standardize features (though ratios are already normalized)
    scaler = StandardScaler()
    stat_scaled = scaler.fit_transform(stat_matrix)

    # K-means clustering
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = kmeans.fit_predict(stat_scaled)

    # Analyze each cluster
    clusters = []
    for cluster_id in range(n_clusters):
        mask = labels == cluster_id
        cluster_metadata = [m for m, is_in in zip(metadata, mask) if is_in]
        cluster_stats = stat_matrix[mask]

        # Compute centroid (average stat ratios)
        centroid = cluster_stats.mean(axis=0).tolist()

        # Count equipment usage in this cluster
        chip_counts = defaultdict(int)
        weapon_counts = defaultdict(int)

        for m in cluster_metadata:
            for chip in m['chips_used']:
                chip_counts[chip] += 1
            for weapon in m['weapons_used']:
                weapon_counts[weapon] += 1

        # Get top equipment
        top_chips = sorted(chip_counts.items(), key=lambda x: -x[1])[:5]
        top_weapons = sorted(weapon_counts.items(), key=lambda x: -x[1])[:3]

        # Compute average level
        avg_level = sum(m['level'] for m in cluster_metadata) / len(cluster_metadata) if cluster_metadata else 0

        # Determine archetype name based on dominant stat
        stat_names = ['strength', 'agility', 'magic', 'resistance']
        dominant_idx = centroid.index(max(centroid))
        dominant_stat = stat_names[dominant_idx]

        # More descriptive name based on stat distribution
        if centroid[0] > 0.5:  # >50% strength
            archetype = "Strength"
        elif centroid[1] > 0.5:  # >50% agility
            archetype = "Agility"
        elif centroid[2] > 0.5:  # >50% magic
            archetype = "Magic"
        elif centroid[3] > 0.3:  # >30% resistance (tank)
            archetype = "Tank"
        elif centroid[0] > 0.3 and centroid[1] > 0.3:
            archetype = "Hybrid Str/Agi"
        elif centroid[0] > 0.3 and centroid[2] > 0.3:
            archetype = "Hybrid Str/Mag"
        elif centroid[1] > 0.3 and centroid[2] > 0.3:
            archetype = "Hybrid Agi/Mag"
        else:
            archetype = f"{dominant_stat.capitalize()}-focused"

        clusters.append({
            'id': cluster_id,
            'archetype': archetype,
            'size': int(mask.sum()),
            'centroid': {
                'strength': round(centroid[0], 3),
                'agility': round(centroid[1], 3),
                'magic': round(centroid[2], 3),
                'resistance': round(centroid[3], 3),
            },
            'avg_level': round(avg_level, 1),
            'top_chips': top_chips,
            'top_weapons': top_weapons,
        })

    # Sort clusters by size
    clusters.sort(key=lambda x: -x['size'])

    return {
        'clusters': clusters,
        'sample_count': len(stat_matrix),
        'level_range': [level_min, level_max],
        'n_clusters': n_clusters,
    }


def get_cluster_distribution_by_level(
    db_path: Path,
    n_clusters: int = 6,
    level_buckets: list[tuple[int, int]] = None,
) -> dict:
    """
    Get cluster distribution across level ranges.

    Returns data suitable for a stacked area chart showing how
    build archetypes evolve across levels.
    """
    if level_buckets is None:
        level_buckets = [
            (1, 50), (51, 100), (101, 150), (151, 200), (201, 250), (251, 300), (301, 301)
        ]

    # First, cluster all data to get consistent cluster definitions
    full_result = cluster_builds(db_path, n_clusters=n_clusters, min_total_stats=50)

    if 'error' in full_result:
        return full_result

    # Get cluster archetype names
    archetype_names = {c['id']: c['archetype'] for c in full_result['clusters']}

    # Now get distribution for each level bucket
    distribution = []

    for level_min, level_max in level_buckets:
        bucket_result = cluster_builds(
            db_path, n_clusters=n_clusters,
            level_min=level_min, level_max=level_max,
            min_total_stats=50
        )

        if 'error' in bucket_result:
            distribution.append({
                'level_range': f"{level_min}-{level_max}",
                'total': 0,
                'clusters': {},
            })
            continue

        # Count by cluster
        cluster_counts = {c['id']: c['size'] for c in bucket_result['clusters']}
        total = sum(cluster_counts.values())

        distribution.append({
            'level_range': f"{level_min}-{level_max}" if level_min != level_max else str(level_min),
            'total': total,
            'clusters': {
                archetype_names.get(cid, f"Cluster {cid}"): count
                for cid, count in cluster_counts.items()
            },
        })

    return {
        'distribution': distribution,
        'archetypes': list(archetype_names.values()),
    }
