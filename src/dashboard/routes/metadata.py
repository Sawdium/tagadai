"""
Metadata extraction API routes.
"""

from datetime import datetime
from typing import Optional

from fastapi import FastAPI

from src.common.config import get_paths

# Scraper imports
try:
    from ...scraper import get_scraper
    SCRAPER_AVAILABLE = True
except ImportError:
    SCRAPER_AVAILABLE = False
    get_scraper = None

_paths = get_paths()


def register_metadata_routes(app: FastAPI):
    """Register metadata-related routes."""

    @app.get("/api/metadata/status")
    async def get_metadata_status():
        """Get metadata extraction progress and stats."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}
        scraper = get_scraper()
        return {
            "progress": scraper.db.get_metadata_extraction_progress(),
            "stats": scraper.db.get_metadata_stats(),
        }

    @app.post("/api/metadata/extract")
    async def extract_metadata(batch_size: int = 500, max_batches: int = 10):
        """Extract metadata for fights that don't have it yet."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}

        from ...scraper.metadata import extract_fight_metadata

        scraper = get_scraper()
        total_saved = 0
        batches_processed = 0

        for _ in range(max_batches):
            fights = scraper.db.get_fights_needing_metadata(batch_size=batch_size)
            if not fights:
                break

            for fight_id, fight_data in fights:
                metadata = extract_fight_metadata(fight_id, fight_data)
                if metadata:
                    saved = scraper.db.save_fight_metadata([m.to_dict() for m in metadata])
                    total_saved += saved

            batches_processed += 1

            if fights:
                scraper.db.set_metadata_extraction_state('last_fight_id', str(fights[-1][0]))
                scraper.db.set_metadata_extraction_state('last_extraction_time',
                    datetime.now().isoformat())

        return {
            "batches_processed": batches_processed,
            "records_saved": total_saved,
            "progress": scraper.db.get_metadata_extraction_progress(),
        }

    @app.get("/api/metadata/equipment")
    async def get_equipment_usage(fight_type: Optional[int] = None, min_sample: int = 10):
        """Get equipment usage statistics by level bucket."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}

        from ...scraper.item_mappings import get_weapon_name, get_chip_name

        scraper = get_scraper()
        raw_data = scraper.db.get_equipment_usage_by_level(
            fight_type=fight_type,
            min_sample_size=min_sample
        )

        result = {}
        for bucket, data in raw_data.items():
            result[bucket] = {
                "sample_size": data["sample_size"],
                "weapons": {
                    str(w): {
                        "name": get_weapon_name(int(w)),
                        "count": info["count"],
                        "pct": info["pct"]
                    }
                    for w, info in data["weapons"].items()
                },
                "chips": {
                    str(c): {
                        "name": get_chip_name(int(c)),
                        "count": info["count"],
                        "pct": info["pct"]
                    }
                    for c, info in data["chips"].items()
                },
            }

        return {
            "by_level": result,
            "fight_type": fight_type,
            "min_sample": min_sample,
        }

    @app.get("/api/metadata/cooccurrence")
    async def get_equipment_cooccurrence(
        level_bucket: Optional[str] = None,
        fight_type: Optional[int] = None,
        min_cooccurrence: int = 10,
        item_type: Optional[str] = None,
    ):
        """Get equipment co-occurrence matrix for builds analysis."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}

        from ...scraper.item_mappings import get_weapon_name, get_chip_name

        scraper = get_scraper()
        raw_data = scraper.db.get_equipment_cooccurrence(
            level_bucket=level_bucket,
            fight_type=fight_type,
            min_cooccurrence=min_cooccurrence,
        )

        items = raw_data.get("items", [])
        matrix = raw_data.get("matrix", [])
        counts = raw_data.get("counts", {})

        if item_type:
            prefix = "W:" if item_type == "weapon" else "C:"
            indices = [i for i, item in enumerate(items) if item.startswith(prefix)]
            items = [items[i] for i in indices]
            matrix = [[matrix[i][j] for j in indices] for i in indices]
            counts = {k: v for k, v in counts.items() if k.startswith(prefix)}

        named_items = []
        for item in items:
            if item.startswith("W:"):
                weapon_id = int(item[2:])
                named_items.append({
                    "id": item,
                    "type": "weapon",
                    "name": get_weapon_name(weapon_id),
                })
            elif item.startswith("C:"):
                chip_id = int(item[2:])
                named_items.append({
                    "id": item,
                    "type": "chip",
                    "name": get_chip_name(chip_id),
                })

        return {
            "items": named_items,
            "matrix": matrix,
            "counts": {k: v for k, v in counts.items()},
            "level_bucket": level_bucket,
            "fight_type": fight_type,
            "min_cooccurrence": min_cooccurrence,
        }

    @app.get("/api/metadata/clusters")
    async def get_build_clusters(
        n_clusters: int = 6,
        level_min: int = 1,
        level_max: int = 301,
    ):
        """Get build archetype clusters based on stat distributions."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}

        try:
            from ...scraper.clustering import cluster_builds
            from ...scraper.item_mappings import get_chip_name, get_weapon_name

            result = cluster_builds(
                _paths.database_path,
                n_clusters=n_clusters,
                level_min=level_min,
                level_max=level_max,
            )

            if 'error' in result:
                return result

            for cluster in result['clusters']:
                cluster['top_chips'] = [
                    {'id': cid, 'name': get_chip_name(cid), 'count': cnt}
                    for cid, cnt in cluster['top_chips']
                ]
                cluster['top_weapons'] = [
                    {'id': wid, 'name': get_weapon_name(wid), 'count': cnt}
                    for wid, cnt in cluster['top_weapons']
                ]

            return result

        except ImportError as e:
            return {"error": f"Missing dependency: {e}. Install scikit-learn."}
        except Exception as e:
            return {"error": str(e)}

    @app.get("/api/metadata/clusters/evolution")
    async def get_cluster_evolution(n_clusters: int = 6):
        """Get cluster distribution evolution across levels."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}

        try:
            from ...scraper.clustering import get_stat_vectors
            import numpy as np
            from sklearn.cluster import KMeans
            from sklearn.preprocessing import StandardScaler

            stat_matrix, metadata = get_stat_vectors(_paths.database_path, level_min=1, level_max=301, min_total_stats=50)

            if len(stat_matrix) < n_clusters:
                return {"error": f"Not enough samples ({len(stat_matrix)})"}

            scaler = StandardScaler()
            stat_scaled = scaler.fit_transform(stat_matrix)
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            labels = kmeans.fit_predict(stat_scaled)

            stat_names = ['Str', 'Agi', 'Mag', 'Res']
            archetypes = {}
            for cluster_id in range(n_clusters):
                centroid = stat_matrix[labels == cluster_id].mean(axis=0)
                sorted_stats = sorted(enumerate(centroid), key=lambda x: -x[1])
                top_idx, top_val = sorted_stats[0]
                second_idx, second_val = sorted_stats[1]

                if top_val > 0.7:
                    archetypes[cluster_id] = f"Pure {stat_names[top_idx]}"
                elif top_val > 0.45 and second_val > 0.25:
                    archetypes[cluster_id] = f"{stat_names[top_idx]}/{stat_names[second_idx]}"
                elif top_val > 0.4:
                    archetypes[cluster_id] = f"{stat_names[top_idx]} Focus"
                else:
                    archetypes[cluster_id] = f"Balanced"

            buckets = [
                (1, 25), (26, 50), (51, 75), (76, 100),
                (101, 125), (126, 150), (151, 175), (176, 200),
                (201, 225), (226, 250), (251, 275), (276, 300), (301, 301)
            ]

            evolution = []
            for level_min, level_max in buckets:
                bucket_mask = np.array([
                    level_min <= m['level'] <= level_max
                    for m in metadata
                ])
                bucket_labels = labels[bucket_mask]
                total = len(bucket_labels)

                if total == 0:
                    continue

                label_str = f"{level_min}-{level_max}" if level_min != level_max else str(level_min)
                bucket_data = {
                    'level_range': label_str,
                    'total': total,
                    'clusters': {}
                }

                for cluster_id in range(n_clusters):
                    count = int((bucket_labels == cluster_id).sum())
                    pct = round(count / total * 100, 1)
                    bucket_data['clusters'][archetypes[cluster_id]] = {
                        'count': count,
                        'pct': pct
                    }

                evolution.append(bucket_data)

            base_colors = {
                'Str': ['#f85149', '#ff7b72', '#ffa198'],
                'Agi': ['#3fb950', '#7ee787', '#a5d6a7'],
                'Mag': ['#a371f7', '#d2a8ff', '#e0c3fc'],
                'Res': ['#d29922', '#f0b429', '#ffd54f'],
            }
            archetype_colors = {}
            stat_counters = {'Str': 0, 'Agi': 0, 'Mag': 0, 'Res': 0}

            for archetype in set(archetypes.values()):
                for stat in ['Str', 'Agi', 'Mag', 'Res']:
                    if stat in archetype:
                        idx = stat_counters[stat] % len(base_colors[stat])
                        archetype_colors[archetype] = base_colors[stat][idx]
                        stat_counters[stat] += 1
                        break
                else:
                    archetype_colors[archetype] = '#8b949e'

            return {
                'evolution': evolution,
                'archetypes': list(set(archetypes.values())),
                'archetype_colors': archetype_colors,
                'sample_count': len(stat_matrix),
                'n_clusters': n_clusters,
            }

        except ImportError as e:
            return {"error": f"Missing dependency: {e}. Install scikit-learn."}
        except Exception as e:
            import traceback
            return {"error": str(e), "traceback": traceback.format_exc()}

    @app.get("/api/metadata/insights")
    async def get_build_insights():
        """Generate auto-insights from build data."""
        if not SCRAPER_AVAILABLE:
            return {"error": "Scraper module not available"}

        try:
            from ...scraper.clustering import get_stat_vectors
            import numpy as np
            from sklearn.cluster import KMeans
            from sklearn.preprocessing import StandardScaler

            stat_matrix, metadata = get_stat_vectors(_paths.database_path, level_min=1, level_max=301, min_total_stats=50)

            if len(stat_matrix) < 10:
                return {"insights": [], "error": "Not enough data"}

            insights = []

            low_level = [m for m in metadata if m['level'] <= 50]
            mid_level = [m for m in metadata if 100 <= m['level'] <= 150]
            high_level = [m for m in metadata if m['level'] >= 250]

            def get_dominant_stat(leeks):
                if not leeks:
                    return None, 0
                avg_str = np.mean([l['strength'] for l in leeks])
                avg_agi = np.mean([l['agility'] for l in leeks])
                avg_mag = np.mean([l['magic'] for l in leeks])
                avg_res = np.mean([l['resistance'] for l in leeks])
                total = avg_str + avg_agi + avg_mag + avg_res
                if total == 0:
                    return None, 0
                stats = {'Strength': avg_str/total, 'Agility': avg_agi/total,
                         'Magic': avg_mag/total, 'Resistance': avg_res/total}
                dominant = max(stats, key=stats.get)
                return dominant, stats[dominant]

            if low_level:
                stat, pct = get_dominant_stat(low_level)
                if stat and pct > 0.35:
                    insights.append({
                        'type': 'level_trend',
                        'icon': '📊',
                        'text': f'{stat} dominates early game ({pct*100:.0f}% of stats at level 1-50)'
                    })

            if high_level:
                stat, pct = get_dominant_stat(high_level)
                if stat:
                    insights.append({
                        'type': 'level_trend',
                        'icon': '🎯',
                        'text': f'High-level meta favors {stat} ({pct*100:.0f}% at level 250+)'
                    })

            for threshold in [50, 75, 100, 125, 150]:
                magic_leeks = [m for m in metadata if m['level'] >= threshold and m['magic'] > m['strength'] and m['magic'] > m['agility']]
                if len(magic_leeks) >= 20:
                    insights.append({
                        'type': 'emergence',
                        'icon': '✨',
                        'text': f'Magic builds emerge around level {threshold}'
                    })
                    break

            scaler = StandardScaler()
            stat_scaled = scaler.fit_transform(stat_matrix)
            kmeans = KMeans(n_clusters=6, random_state=42, n_init=10)
            labels = kmeans.fit_predict(stat_scaled)

            cluster_sizes = np.bincount(labels, minlength=6)
            rarest_cluster = int(np.argmin(cluster_sizes))
            rarest_size = cluster_sizes[rarest_cluster]
            rarest_pct = rarest_size / len(labels) * 100

            if rarest_pct < 5:
                rarest_centroid = stat_matrix[labels == rarest_cluster].mean(axis=0)
                stat_names = ['Strength', 'Agility', 'Magic', 'Resistance']
                dominant = stat_names[int(np.argmax(rarest_centroid))]
                insights.append({
                    'type': 'rarity',
                    'icon': '💎',
                    'text': f'{dominant}-focused builds are rare ({rarest_pct:.1f}% of players)'
                })

            popular_cluster = int(np.argmax(cluster_sizes))
            popular_pct = cluster_sizes[popular_cluster] / len(labels) * 100
            popular_centroid = stat_matrix[labels == popular_cluster].mean(axis=0)
            stat_names = ['Strength', 'Agility', 'Magic', 'Resistance']
            dominant = stat_names[int(np.argmax(popular_centroid))]
            insights.append({
                'type': 'popular',
                'icon': '🏆',
                'text': f'{dominant} is the most popular stat ({popular_pct:.0f}% of builds)'
            })

            insights.append({
                'type': 'info',
                'icon': '📈',
                'text': f'Analysis based on {len(metadata):,} unique leek builds'
            })

            return {"insights": insights}

        except Exception as e:
            return {"error": str(e), "insights": []}
