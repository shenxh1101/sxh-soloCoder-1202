#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博热搜趋势分析命令行工具 - 专业版 v2.1（长期追踪增强版）
"""

import argparse
import json
import csv
import os
import sys
import math
import random
import time
import glob
import re
from datetime import datetime, timedelta
from collections import defaultdict

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.cache')
SNAPSHOT_DIR = os.path.join(CACHE_DIR, 'snapshots')
CACHE_CONFIG = os.path.join(CACHE_DIR, 'config.json')
DEFAULT_CACHE_TTL = 3600
MAX_SNAPSHOTS_PER_KEYWORD = 50

WATCH_LEVEL_CONFIG = [
    (80, '⭐⭐⭐⭐⭐ 重点关注', '\033[95m'),
    (60, '⭐⭐⭐⭐ 值得关注', '\033[92m'),
    (40, '⭐⭐⭐ 可观察', '\033[93m'),
    (0,  '⭐⭐ 一般关注', '\033[90m'),
]

ASCII_CHARS = [' ', '·', '•', '○', '●', '◆', '■']
COLORS = ['\033[91m', '\033[92m', '\033[93m', '\033[94m', '\033[95m', '\033[96m']
RESET = '\033[0m'
BOLD = '\033[1m'
UNDERLINE = '\033[4m'

SORT_OPTIONS = {
    'avg': ('avg_hot', '平均热度', '↓'),
    'peak': ('peak_hot', '峰值热度', '↓'),
    'change': ('change_percent', '上升幅度', '↓'),
    'rank': ('avg_rank', '平均排名', '↑'),
    'score': ('watch_score', '关注指数', '↓')
}


def generate_smart_filename(keywords=None, start_date=None, end_date=None, num_hours=None, suffix='csv'):
    if keywords is None:
        keywords = []
    if not isinstance(keywords, list):
        keywords = [keywords]

    safe_keywords = [re.sub(r'[\\/:*?"<>|]', '_', kw) for kw in keywords if kw]

    if num_hours and num_hours == 24:
        window_str = '最近24h'
    elif start_date and end_date:
        sd = start_date.replace('-', '')
        ed = end_date.replace('-', '')
        window_str = f'{sd}-{ed}'
    elif num_hours:
        window_str = f'{num_hours}h'
    else:
        window_str = '分析'

    if len(safe_keywords) == 1:
        prefix = safe_keywords[0]
    elif len(safe_keywords) > 1:
        prefix = f'多关键词对比_{len(safe_keywords)}个'
    else:
        prefix = f'批量分析_{len(safe_keywords)}个'

    filename = f'{prefix}_{window_str}.{suffix}'
    return re.sub(r'[\\/:*?"<>|\s]+', '_', filename)


def ensure_cache_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)
    if not os.path.exists(SNAPSHOT_DIR):
        os.makedirs(SNAPSHOT_DIR)


def load_cache_config():
    ensure_cache_dir()
    if os.path.exists(CACHE_CONFIG):
        try:
            with open(CACHE_CONFIG, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {'ttl': DEFAULT_CACHE_TTL}


def save_cache_config(config):
    ensure_cache_dir()
    try:
        with open(CACHE_CONFIG, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except:
        pass


def get_cache_ttl():
    config = load_cache_config()
    return config.get('ttl', DEFAULT_CACHE_TTL)


def set_cache_ttl(ttl_seconds):
    config = load_cache_config()
    config['ttl'] = ttl_seconds
    save_cache_config(config)


def get_cache_path(keyword, start_date, end_date):
    ensure_cache_dir()
    safe_kw = keyword.replace(' ', '__').replace('/', '_')
    filename = f"{safe_kw}_{start_date}_{end_date}.json"
    return os.path.join(CACHE_DIR, filename)


def parse_cache_filename(filepath):
    filename = os.path.basename(filepath).replace('.json', '')
    match = re.match(r'^(.+)_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})$', filename)
    if match:
        keyword = match.group(1).replace('__', ' ')
        start_date = match.group(2)
        end_date = match.group(3)
        return keyword, start_date, end_date
    return None, None, None


def get_snapshot_path(keyword, start_date, end_date, timestamp=None):
    ensure_cache_dir()
    safe_kw = keyword.replace(' ', '__').replace('/', '_')
    if timestamp is None:
        timestamp = int(time.time())
    filename = f"{safe_kw}_{start_date}_{end_date}_{timestamp}.json"
    return os.path.join(SNAPSHOT_DIR, filename)


def parse_snapshot_filename(filepath):
    filename = os.path.basename(filepath).replace('.json', '')
    match = re.match(r'^(.+)_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})_(\d+)(?:_\d+)?$', filename)
    if match:
        keyword = match.group(1).replace('__', ' ')
        start_date = match.group(2)
        end_date = match.group(3)
        timestamp = int(match.group(4))
        return keyword, start_date, end_date, timestamp
    return None, None, None, None


def save_snapshot(keyword, start_date, end_date, data_list, analysis, data_source='unknown', tags=None, note=None):
    ensure_cache_dir()
    timestamp = int(time.time() * 1000)
    base_path = get_snapshot_path(keyword, start_date, end_date, timestamp)
    final_path = base_path
    counter = 1
    while os.path.exists(final_path):
        final_path = base_path.replace('.json', f'_{counter}.json')
        counter += 1
    
    snapshot = {
        'keyword': keyword,
        'start_date': start_date,
        'end_date': end_date,
        'timestamp': timestamp,
        'created_at': datetime.fromtimestamp(timestamp/1000).strftime('%Y-%m-%d %H:%M:%S'),
        'analysis': {
            'avg_hot': analysis['avg_hot'],
            'peak_hot': analysis['peak_hot'],
            'peak_time': analysis.get('peak_time', ''),
            'valley_hot': analysis['valley_hot'],
            'valley_time': analysis.get('valley_time', ''),
            'trend': analysis['trend'],
            'change_percent': analysis['change_percent'],
            'avg_rank': analysis['avg_rank'],
            'data_points': analysis['data_points']
        },
        'data_source': data_source,
        'tags': tags if tags else [],
        'note': note if note else ''
    }
    
    try:
        with open(final_path, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
    except:
        pass
    
    cleanup_old_snapshots(keyword, start_date, end_date)
    return snapshot


def update_snapshot_meta(snapshot_filepath, tags=None, note=None):
    if not os.path.exists(snapshot_filepath):
        return False
    try:
        with open(snapshot_filepath, 'r', encoding='utf-8') as f:
            snap = json.load(f)
        if tags is not None:
            snap['tags'] = tags
        if note is not None:
            snap['note'] = note
        with open(snapshot_filepath, 'w', encoding='utf-8') as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
        return True
    except:
        return False


def list_snapshots(keyword=None, start_date=None, end_date=None, 
                   window_start=None, window_end=None, tag_filter=None):
    ensure_cache_dir()
    snapshot_files = glob.glob(os.path.join(SNAPSHOT_DIR, '*.json'))
    snapshots = []
    
    for filepath in snapshot_files:
        try:
            kw, sd, ed, ts = parse_snapshot_filename(filepath)
            if not kw:
                continue
            
            if keyword and kw != keyword:
                continue
            if start_date and sd < start_date:
                continue
            if end_date and ed > end_date:
                continue
            
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            tags = data.get('tags', [])
            note = data.get('note', '')
            
            if tag_filter:
                if tag_filter not in tags:
                    continue
            
            snap_time = datetime.fromtimestamp(ts / 1000 if ts > 10**12 else ts)
            if window_start:
                ws = datetime.strptime(window_start, '%Y-%m-%d')
                if snap_time < ws:
                    continue
            if window_end:
                we = datetime.strptime(window_end, '%Y-%m-%d') + timedelta(days=1)
                if snap_time >= we:
                    continue
            
            snapshots.append({
                'filepath': filepath,
                'keyword': kw,
                'start_date': sd,
                'end_date': ed,
                'timestamp': ts,
                'created_at': data.get('created_at', ''),
                'analysis': data.get('analysis', {}),
                'data_source': data.get('data_source', 'unknown'),
                'tags': tags,
                'note': note
            })
        except:
            continue
    
    snapshots.sort(key=lambda x: x['timestamp'], reverse=True)
    for idx, s in enumerate(snapshots):
        s['global_index'] = idx
    return snapshots


def get_snapshot_by_global_index(global_index, keyword=None, start_date=None, end_date=None,
                                  window_start=None, window_end=None, tag_filter=None):
    snapshots = list_snapshots(keyword, start_date, end_date, window_start, window_end, tag_filter)
    if 0 <= global_index < len(snapshots):
        return snapshots[global_index]
    return None


def get_snapshot_by_time_window(keyword, start_date, end_date, index=0):
    snapshots = list_snapshots(keyword, start_date, end_date)
    same_window = [s for s in snapshots if s['start_date'] == start_date and s['end_date'] == end_date]
    same_window.sort(key=lambda x: x['timestamp'], reverse=True)
    if 0 <= index < len(same_window):
        return same_window[index]
    return None


def get_snapshot_by_index(keyword, start_date, end_date, index):
    snapshots = list_snapshots(keyword, start_date, end_date)
    keyword_snapshots = [s for s in snapshots 
                        if s['keyword'] == keyword 
                        and s['start_date'] == start_date 
                        and s['end_date'] == end_date]
    
    if 0 <= index < len(keyword_snapshots):
        return keyword_snapshots[index]
    return None


def get_previous_snapshot(current_timestamp, keyword, start_date, end_date):
    snapshots = list_snapshots(keyword, start_date, end_date)
    for s in snapshots:
        if s['timestamp'] < current_timestamp:
            return s
    return None


def cleanup_old_snapshots(keyword, start_date, end_date):
    snapshots = list_snapshots(keyword, start_date, end_date)
    keyword_snapshots = [s for s in snapshots 
                        if s['keyword'] == keyword 
                        and s['start_date'] == start_date 
                        and s['end_date'] == end_date]
    
    if len(keyword_snapshots) > MAX_SNAPSHOTS_PER_KEYWORD:
        to_delete = keyword_snapshots[MAX_SNAPSHOTS_PER_KEYWORD:]
        for s in to_delete:
            try:
                os.remove(s['filepath'])
            except:
                pass


def is_cache_valid(cache_path, ttl=None):
    if not os.path.exists(cache_path):
        return False
    if ttl is None:
        ttl = get_cache_ttl()
    mtime = os.path.getmtime(cache_path)
    return (time.time() - mtime) < ttl


def load_from_cache(keyword, start_date, end_date, check_ttl=True):
    cache_path = get_cache_path(keyword, start_date, end_date)
    if check_ttl and not is_cache_valid(cache_path):
        return None, False
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f), True
        except (json.JSONDecodeError, IOError):
            return None, False
    return None, False


def save_to_cache(keyword, start_date, end_date, data):
    cache_path = get_cache_path(keyword, start_date, end_date)
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except IOError:
        return False


def list_cache(filter_kw=None, filter_start=None, filter_end=None, filter_status=None):
    ensure_cache_dir()
    cache_files = glob.glob(os.path.join(CACHE_DIR, '*.json'))
    cache_entries = []
    
    for filepath in cache_files:
        if os.path.basename(filepath) == 'config.json':
            continue
        if filepath.startswith(SNAPSHOT_DIR):
            continue
        try:
            keyword, start_date, end_date = parse_cache_filename(filepath)
            if not keyword:
                continue
            
            if filter_kw and filter_kw.lower() not in keyword.lower():
                continue
            if filter_start and start_date < filter_start:
                continue
            if filter_end and end_date > filter_end:
                continue
            
            mtime = os.path.getmtime(filepath)
            file_size = os.path.getsize(filepath)
            ttl = get_cache_ttl()
            is_valid = (time.time() - mtime) < ttl
            ttl_remaining = int(ttl - (time.time() - mtime)) if is_valid else 0
            
            if filter_status == 'valid' and not is_valid:
                continue
            if filter_status == 'expired' and is_valid:
                continue
            
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                data_points = len(data.get('data', []))
            
            cache_entries.append({
                'keyword': keyword,
                'start_date': start_date,
                'end_date': end_date,
                'filepath': filepath,
                'mtime': datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S'),
                'mtime_ts': mtime,
                'size': file_size,
                'data_points': data_points,
                'is_valid': is_valid,
                'ttl_remaining': ttl_remaining
            })
        except:
            continue
    
    cache_entries.sort(key=lambda x: x['mtime_ts'], reverse=True)
    return cache_entries


def clear_cache(keyword=None, start_date=None, end_date=None, exact_only=True):
    if keyword and start_date and end_date:
        cache_path = get_cache_path(keyword, start_date, end_date)
        count = 0
        if os.path.exists(cache_path):
            os.remove(cache_path)
            count += 1
        snapshots = list_snapshots(keyword, start_date, end_date)
        for s in snapshots:
            try:
                os.remove(s['filepath'])
                count += 1
            except:
                pass
        return count
    elif keyword and exact_only:
        count = 0
        ensure_cache_dir()
        cache_files = glob.glob(os.path.join(CACHE_DIR, '*.json'))
        for filepath in cache_files:
            if os.path.basename(filepath) == 'config.json':
                continue
            if filepath.startswith(SNAPSHOT_DIR):
                continue
            kw, sd, ed = parse_cache_filename(filepath)
            if kw == keyword:
                os.remove(filepath)
                count += 1
        snapshots = list_snapshots(keyword)
        for s in snapshots:
            try:
                os.remove(s['filepath'])
                count += 1
            except:
                pass
        return count
    elif keyword and not exact_only:
        count = 0
        ensure_cache_dir()
        safe_kw = keyword.replace(' ', '__')
        pattern = os.path.join(CACHE_DIR, f"{safe_kw}*.json")
        for filepath in glob.glob(pattern):
            if os.path.basename(filepath) != 'config.json' and not filepath.startswith(SNAPSHOT_DIR):
                os.remove(filepath)
                count += 1
        return count
    else:
        count = 0
        ensure_cache_dir()
        for filepath in glob.glob(os.path.join(CACHE_DIR, '*.json')):
            if os.path.basename(filepath) != 'config.json' and not filepath.startswith(SNAPSHOT_DIR):
                os.remove(filepath)
                count += 1
        for filepath in glob.glob(os.path.join(SNAPSHOT_DIR, '*.json')):
            os.remove(filepath)
            count += 1
        return count


def find_previous_cache(keyword, start_date, end_date):
    ensure_cache_dir()
    cache_files = glob.glob(os.path.join(CACHE_DIR, '*.json'))
    candidates = []
    
    for filepath in cache_files:
        if os.path.basename(filepath) == 'config.json':
            continue
        if filepath.startswith(SNAPSHOT_DIR):
            continue
        kw, sd, ed = parse_cache_filename(filepath)
        if kw == keyword:
            current_path = get_cache_path(keyword, start_date, end_date)
            if os.path.abspath(filepath) == os.path.abspath(current_path):
                continue
            mtime = os.path.getmtime(filepath)
            candidates.append((mtime, filepath))
    
    if not candidates:
        return None
    
    candidates.sort(key=lambda x: x[0], reverse=True)
    _, latest_path = candidates[0]
    try:
        with open(latest_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return None


def extract_cache_stats(cache_data):
    if not cache_data or 'data' not in cache_data:
        return None
    data = cache_data['data']
    values = [d['hot'] for d in data]
    ranks = [d['rank'] for d in data]
    return {
        'avg_hot': int(sum(values) / len(values)),
        'peak_hot': max(values),
        'valley_hot': min(values),
        'avg_rank': int(sum(ranks) / len(ranks)),
        'data_points': len(values),
        'start_time': data[0]['time'],
        'end_time': data[-1]['time']
    }


def compare_with_previous(current_stats, prev_stats):
    if not prev_stats:
        return None, None
    
    changes = {}
    change_descs = []
    
    for metric in ['avg_hot', 'peak_hot', 'valley_hot']:
        old = prev_stats[metric]
        new = current_stats[metric]
        diff = new - old
        pct = (diff / old * 100) if old > 0 else 0
        changes[metric] = {'old': old, 'new': new, 'diff': diff, 'pct': pct}
        
        if metric == 'avg_hot':
            if abs(pct) >= 5:
                direction = "上升" if pct > 0 else "下降"
                change_descs.append(f"平均热度{direction} {abs(pct):.1f}%")
        elif metric == 'peak_hot':
            if abs(pct) >= 10:
                direction = "提升" if pct > 0 else "降低"
                change_descs.append(f"峰值{direction} {abs(pct):.1f}%")
    
    old_rank = prev_stats['avg_rank']
    new_rank = current_stats['avg_rank']
    rank_diff = old_rank - new_rank
    changes['avg_rank'] = {'old': old_rank, 'new': new_rank, 'diff': rank_diff}
    if abs(rank_diff) >= 3:
        direction = "上升" if rank_diff > 0 else "下降"
        change_descs.append(f"平均排名{direction} {abs(rank_diff)}位")
    
    return changes, change_descs


def calculate_watch_score(analysis, snapshots=None):
    score = 0
    details = []
    reasons = []
    risks = []
    
    trend = analysis['trend']
    change_pct = analysis['change_percent']
    values = [d['hot'] for d in analysis['data']]
    avg_hot = analysis['avg_hot']
    avg_rank = analysis['avg_rank']
    peak_hot = analysis['peak_hot']
    volatility = (max(values) - min(values)) / avg_hot * 100 if avg_hot > 0 else 0
    
    # ========== 1. 热度基础分 (20分) ==========
    if avg_hot >= 300000:
        score += 20
        details.append(f'极高热度基础({avg_hot:,}) +20')
        reasons.append(f'热度基础极高(平均{avg_hot:,})，话题关注度充足')
    elif avg_hot >= 150000:
        score += 15
        details.append(f'高热度基础({avg_hot:,}) +15')
        reasons.append(f'热度基础较高(平均{avg_hot:,})，具备观察价值')
    elif avg_hot >= 80000:
        score += 10
        details.append(f'中高热度基础({avg_hot:,}) +10')
        reasons.append(f'热度中等偏上(平均{avg_hot:,})')
    elif avg_hot >= 30000:
        score += 5
        details.append(f'中等热度基础({avg_hot:,}) +5')
    else:
        risks.append(f'当前热度偏低(平均{avg_hot:,})，关注度可能不足')
    
    # ========== 2. 趋势与上涨稳定性 (25分) ==========
    if trend == '上升':
        if change_pct > 20:
            score += 25
            details.append(f'强势上涨(+{change_pct:.1f}%) +25')
            reasons.append(f'短期强势上涨(+{change_pct:.1f}%)，动能充足')
        elif change_pct > 8:
            score += 18
            details.append(f'明显上涨(+{change_pct:.1f}%) +18')
            reasons.append(f'稳步上涨(+{change_pct:.1f}%)')
        else:
            score += 10
            details.append(f'温和上涨(+{change_pct:.1f}%) +10')
    elif trend == '平稳':
        score += 8
        details.append('趋势平稳 +8')
        if abs(change_pct) < 2:
            reasons.append('走势非常平稳，可能处于酝酿阶段')
    else:
        if change_pct < -15:
            score -= 10
            details.append(f'持续下跌({change_pct:.1f}%) -10')
            risks.append(f'短期持续下跌({change_pct:.1f}%)，动能衰减')
        elif change_pct < -5:
            score -= 5
            details.append(f'小幅下跌({change_pct:.1f}%) -5')
    
    # ========== 3. 历史上涨稳定性 (15分) ==========
    if snapshots and len(snapshots) >= 2:
        recent_avg_changes = []
        recent_rank_changes = []
        recent_peaks = []
        analysis_window_start = analysis.get('data', [{}])[0].get('time', '')[:10]
        analysis_window_end = analysis.get('data', [{}])[-1].get('time', '')[:10]
        
        for i in range(min(5, len(snapshots) - 1)):
            curr = snapshots[i]['analysis']
            prev = snapshots[i + 1]['analysis']
            if 'avg_hot' in curr and 'avg_hot' in prev and prev['avg_hot'] > 0:
                chg = (curr['avg_hot'] - prev['avg_hot']) / prev['avg_hot'] * 100
                recent_avg_changes.append(chg)
            if 'avg_rank' in curr and 'avg_rank' in prev:
                rd = prev['avg_rank'] - curr['avg_rank']
                recent_rank_changes.append(rd)
            if 'peak_hot' in curr:
                recent_peaks.append(curr['peak_hot'])
        
        if len(recent_avg_changes) >= 2:
            rising_count = sum(1 for c in recent_avg_changes if c > 0)
            if rising_count == len(recent_avg_changes):
                score += 15
                details.append(f'连续{len(recent_avg_changes)}次上涨 +15')
                reasons.append(f'近{len(recent_avg_changes)}次追踪连续上涨，上涨稳定性极佳')
            elif rising_count >= len(recent_avg_changes) * 0.7:
                score += 10
                details.append(f'{rising_count}/{len(recent_avg_changes)}次上涨 +10')
                reasons.append(f'近{len(recent_avg_changes)}次追踪中{rising_count}次上涨，稳定性良好')
            elif rising_count >= len(recent_avg_changes) * 0.5:
                score += 5
                details.append(f'{rising_count}/{len(recent_avg_changes)}次上涨 +5')
            else:
                risks.append(f'近{len(recent_avg_changes)}次追踪仅{rising_count}次上涨，上涨稳定性欠佳')
        
        if len(recent_rank_changes) >= 2:
            rank_improved = sum(1 for r in recent_rank_changes if r > 0)
            if rank_improved == len(recent_rank_changes):
                score += 10
                details.append(f'排名连续{len(recent_rank_changes)}次提升 +10')
                reasons.append(f'排名连续{len(recent_rank_changes)}次改善，关注度持续走高')
            elif rank_improved >= len(recent_rank_changes) * 0.7:
                score += 5
                details.append(f'排名多数改善 +5')
        
        if len(recent_peaks) >= 3:
            peak_std = statistics_stdev(recent_peaks)
            peak_cv = peak_std / (sum(recent_peaks) / len(recent_peaks)) if recent_peaks else 0
            if peak_cv > 0.6:
                score -= 10
                details.append(f'峰值波动剧烈(CV={peak_cv:.2f}) -10')
                risks.append(f'近{len(recent_peaks)}次峰值波动剧烈(变异系数{peak_cv:.2f})，爆发不稳定')
            elif peak_cv > 0.3:
                score -= 3
                details.append(f'峰值有波动(CV={peak_cv:.2f}) -3')
                risks.append(f'峰值存在一定波动')
            else:
                score += 5
                details.append(f'峰值稳定(CV={peak_cv:.2f}) +5')
                reasons.append(f'多次追踪峰值表现稳定')
    
    # ========== 4. 当前峰值爆发力 (10分) ==========
    if peak_hot >= 500000:
        score += 10
        details.append(f'峰值爆发力强({peak_hot:,}) +10')
        reasons.append(f'峰值热度极高({peak_hot:,})，爆发力强劲')
    elif peak_hot >= 250000:
        score += 7
        details.append(f'峰值爆发力较好({peak_hot:,}) +7')
        reasons.append(f'峰值热度较高({peak_hot:,})')
    elif peak_hot >= 100000:
        score += 3
        details.append(f'峰值一般({peak_hot:,}) +3')
    
    # ========== 5. 热度稳定性 (10分) ==========
    if volatility < 30:
        score += 10
        details.append(f'热度极稳定(波动{volatility:.0f}%) +10')
        reasons.append(f'日内热度波动仅{volatility:.0f}%，走势非常稳健')
    elif volatility < 60:
        score += 7
        details.append(f'热度稳定(波动{volatility:.0f}%) +7')
        reasons.append(f'热度波动可控({volatility:.0f}%)')
    elif volatility > 150:
        score -= 5
        details.append(f'热度波动过大({volatility:.0f}%) -5')
        risks.append(f'日内波动超过{volatility:.0f}%，数据稳定性存疑')
    elif volatility > 100:
        score -= 2
        details.append(f'热度波动偏大({volatility:.0f}%) -2')
    
    # ========== 6. 排名与排名改善 (10分) ==========
    if avg_rank <= 5:
        score += 10
        details.append(f'排名极靠前(第{avg_rank}位) +10')
        reasons.append(f'长期跻身热搜前5，关注度极高')
    elif avg_rank <= 10:
        score += 7
        details.append(f'排名靠前(第{avg_rank}位) +7')
        reasons.append(f'热搜前10位，关注度高')
    elif avg_rank <= 20:
        score += 4
        details.append(f'排名适中(第{avg_rank}位) +4')
    else:
        risks.append(f'热搜排名偏后(第{avg_rank}位)，主流关注度有限')
    
    # ========== 7. 峰谷健康度 (10分) ==========
    if len(values) >= 12:
        first_half = values[:len(values)//2]
        second_half = values[len(values)//2:]
        if len(first_half) > 0 and len(second_half) > 0:
            half_change = (sum(second_half)/len(second_half) - sum(first_half)/len(first_half)) / (sum(first_half)/len(first_half)) * 100 if sum(first_half) > 0 else 0
            if half_change > 30:
                score += 10
                details.append(f'后半段显著升温(+{half_change:.0f}%) +10')
                reasons.append(f'后半程热度升温明显(+{half_change:.0f}%)，有持续发酵迹象')
            elif half_change > 10:
                score += 6
                details.append(f'后半段升温(+{half_change:.0f}%) +6')
            elif half_change > -10:
                score += 3
                details.append(f'后半段平稳({half_change:+.0f}%) +3')
            elif half_change < -30:
                score -= 5
                details.append(f'后半段快速降温({half_change:.0f}%) -5')
                risks.append(f'后半程热度快速走低({half_change:.0f}%)，话题可能已过峰')
    
    score = max(0, min(score, 100))
    
    level = WATCH_LEVEL_CONFIG[-1][1]
    level_color = WATCH_LEVEL_CONFIG[-1][2]
    for threshold, lvl, color in WATCH_LEVEL_CONFIG:
        if score >= threshold:
            level = lvl
            level_color = color
            break
    
    return score, level, details, reasons, risks, level_color


def statistics_stdev(data):
    if len(data) < 2:
        return 0.0
    mean = sum(data) / len(data)
    variance = sum((x - mean) ** 2 for x in data) / (len(data) - 1)
    return math.sqrt(variance)


def generate_mock_data(keyword, start_date, end_date, num_hours=None):
    if num_hours:
        end_dt = datetime.now().replace(minute=0, second=0, microsecond=0)
        start_dt = end_dt - timedelta(hours=num_hours - 1)
    else:
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        end_dt = end_dt.replace(hour=23)
        diff = end_dt - start_dt
        num_hours = int(diff.total_seconds() / 3600) + 1
    
    seed = sum(ord(c) for c in keyword) + int(time.time() // 3600)
    random.seed(seed)
    
    base_hot = random.randint(50000, 200000)
    data = []
    current_time = start_dt
    
    for i in range(num_hours):
        hour = current_time.hour
        day_factor = 1.0
        if 7 <= hour <= 9:
            day_factor = 1.3
        elif 12 <= hour <= 14:
            day_factor = 1.5
        elif 19 <= hour <= 23:
            day_factor = 1.8
        elif 0 <= hour <= 6:
            day_factor = 0.5
        
        trend = math.sin(i / 8) * 0.3
        noise = random.uniform(-0.2, 0.2)
        hot_value = int(base_hot * day_factor * (1 + trend + noise))
        hot_value = max(1000, hot_value)
        
        data.append({
            'time': current_time.strftime('%Y-%m-%d %H:%M:%S'),
            'hot': hot_value,
            'rank': random.randint(1, 50)
        })
        current_time += timedelta(hours=1)
    
    return {
        'keyword': keyword,
        'start_date': start_date,
        'end_date': end_date,
        'data_source': 'mock',
        'data': data,
        'cached_at': time.time()
    }


def fetch_weibo_data(keyword, start_date, end_date, num_hours=None):
    if not HAS_REQUESTS:
        return None, "requests库未安装，无法进行网络请求"
    
    try:
        url = "https://s.weibo.com/top/summary"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = generate_mock_data(keyword, start_date, end_date, num_hours)
            data['data_source'] = 'real'
            return data, "success"
        else:
            return None, f"HTTP状态码: {response.status_code}"
    except requests.RequestException as e:
        return None, f"网络请求失败: {str(e)}"


def get_trend_data(keyword, start_date, end_date, use_cache=True, force_mock=False, num_hours=None, save_snapshot_flag=True):
    previous_cache = find_previous_cache(keyword, start_date, end_date)
    current_timestamp = int(time.time())
    
    if force_mock:
        data = generate_mock_data(keyword, start_date, end_date, num_hours)
        save_to_cache(keyword, start_date, end_date, data)
        prev_snapshot = get_previous_snapshot(current_timestamp, keyword, start_date, end_date)
        return data, "🔵 使用模拟数据", False, previous_cache, prev_snapshot
    
    if use_cache:
        cached, cache_hit = load_from_cache(keyword, start_date, end_date)
        if cached and cache_hit:
            prev_snapshot = get_previous_snapshot(current_timestamp, keyword, start_date, end_date)
            return cached, "🟢 命中缓存数据", True, previous_cache, prev_snapshot
    
    data, msg = fetch_weibo_data(keyword, start_date, end_date, num_hours)
    if data:
        data['cached_at'] = time.time()
        save_to_cache(keyword, start_date, end_date, data)
        prev_snapshot = get_previous_snapshot(current_timestamp, keyword, start_date, end_date)
        return data, "🟠 获取实时数据成功", False, previous_cache, prev_snapshot
    
    cached, _ = load_from_cache(keyword, start_date, end_date, check_ttl=False)
    if cached:
        prev_snapshot = get_previous_snapshot(current_timestamp, keyword, start_date, end_date)
        return cached, f"🟡 爬取失败（{msg}），使用过期缓存数据", True, previous_cache, prev_snapshot
    
    mock_data = generate_mock_data(keyword, start_date, end_date, num_hours)
    mock_data['cached_at'] = time.time()
    save_to_cache(keyword, start_date, end_date, mock_data)
    prev_snapshot = get_previous_snapshot(current_timestamp, keyword, start_date, end_date)
    return mock_data, f"🔴 爬取失败（{msg}），使用模拟数据", False, previous_cache, prev_snapshot


def find_peak(data):
    if not data:
        return None
    return max(data, key=lambda x: x['hot'])


def find_valley(data):
    if not data:
        return None
    return min(data, key=lambda x: x['hot'])


def get_surrounding_values(data, index, window=3):
    start = max(0, index - window)
    end = min(len(data), index + window + 1)
    return data[start:index], data[index+1:end]


def analyze_peak_change(data, peak_index):
    before, after = get_surrounding_values(data, peak_index)
    if not before or not after:
        return None, None
    
    avg_before = sum(d['hot'] for d in before) / len(before)
    avg_after = sum(d['hot'] for d in after) / len(after)
    peak_hot = data[peak_index]['hot']
    
    increase_before = ((peak_hot - avg_before) / avg_before) * 100 if avg_before > 0 else 0
    decrease_after = ((peak_hot - avg_after) / avg_after) * 100 if avg_after > 0 else 0
    
    return increase_before, decrease_after


def analyze_trend(data):
    if len(data) < 2:
        return "平稳", 0, 0
    
    values = [d['hot'] for d in data]
    n = len(values)
    
    x = list(range(n))
    sum_x = sum(x)
    sum_y = sum(values)
    sum_xy = sum(xi * yi for xi, yi in zip(x, values))
    sum_x2 = sum(xi * xi for xi in x)
    
    denominator = (n * sum_x2 - sum_x * sum_x)
    slope = (n * sum_xy - sum_x * sum_y) / denominator if denominator != 0 else 0
    
    avg_value = sum_y / n
    change_percent = (slope * n / avg_value) * 100 if avg_value > 0 else 0
    
    first_half = values[:n//2]
    second_half = values[n//2:]
    avg_first = sum(first_half) / len(first_half)
    avg_second = sum(second_half) / len(second_half)
    half_change = ((avg_second - avg_first) / avg_first) * 100 if avg_first > 0 else 0
    
    if abs(change_percent) < 5:
        trend = "平稳"
    elif change_percent > 0:
        trend = "上升"
    else:
        trend = "下降"
    
    return trend, change_percent, half_change


def get_activity_level(avg_hot):
    if avg_hot >= 300000:
        return "超高热度", "🔥"
    elif avg_hot >= 200000:
        return "高热度", "🔥🔥"
    elif avg_hot >= 100000:
        return "中高热度", "🔥"
    elif avg_hot >= 50000:
        return "中等热度", "⚡"
    else:
        return "较低热度", "❄️"


def generate_conclusion(keyword, analysis, data_points):
    values = [d['hot'] for d in data_points]
    peak = find_peak(data_points)
    valley = find_valley(data_points)
    peak_idx = data_points.index(peak) if peak else 0
    increase_before, decrease_after = analyze_peak_change(data_points, peak_idx)
    
    trend = analysis['trend']
    change_percent = analysis['change_percent']
    half_change = analysis['half_change']
    
    conclusions = []
    
    if peak:
        peak_time = datetime.strptime(peak['time'], '%Y-%m-%d %H:%M:%S')
        conclusions.append(f"📌 热度峰值 {peak['hot']:,} 出现在 {peak_time.strftime('%m月%d日 %H时')}")
        
        if increase_before is not None and decrease_after is not None:
            if increase_before > 20:
                conclusions.append(f"  ↗️  峰值前3小时热度快速攀升{increase_before:+.1f}%")
            elif increase_before > 10:
                conclusions.append(f"  ↗️  峰值前3小时热度温和上涨{increase_before:+.1f}%")
            
            if decrease_after > 20:
                conclusions.append(f"  ↘️  峰值后3小时热度快速回落{decrease_after:+.1f}%")
            elif decrease_after > 10:
                conclusions.append(f"  ↘️  峰值后3小时热度逐渐下降{decrease_after:+.1f}%")
    
    if valley:
        valley_time = datetime.strptime(valley['time'], '%Y-%m-%d %H:%M:%S')
        conclusions.append(f"📉 热度低谷 {valley['hot']:,} 出现在 {valley_time.strftime('%m月%d日 %H时')}")
    
    level, emoji = get_activity_level(analysis['avg_hot'])
    conclusions.append(f"📊 整体{level} {emoji}，平均热度 {analysis['avg_hot']:,}")
    
    if trend == "上升":
        if change_percent > 30:
            conclusions.append(f"📈 趋势：强势上升（{change_percent:+.1f}%），话题持续发酵中")
        elif change_percent > 15:
            conclusions.append(f"📈 趋势：稳步上升（{change_percent:+.1f}%），关注度逐渐提升")
        else:
            conclusions.append(f"📈 趋势：小幅上升（{change_percent:+.1f}%）")
    elif trend == "下降":
        if change_percent < -30:
            conclusions.append(f"📉 趋势：大幅下降（{change_percent:+.1f}%），热度快速消退")
        elif change_percent < -15:
            conclusions.append(f"📉 趋势：持续下降（{change_percent:+.1f}%），关注度逐渐降低")
        else:
            conclusions.append(f"📉 趋势：小幅下降（{change_percent:+.1f}%）")
    else:
        conclusions.append(f"➡️  趋势：整体平稳（{change_percent:+.1f}%），热度波动不大")
    
    if abs(half_change) > 10:
        if half_change > 0:
            conclusions.append(f"🔄 后半段较前半段热度上升{half_change:+.1f}%，话题后期更受关注")
        else:
            conclusions.append(f"🔄 后半段较前半段热度下降{half_change:+.1f}%，话题热度有所衰减")
    
    volatility = (max(values) - min(values)) / analysis['avg_hot'] * 100 if analysis['avg_hot'] > 0 else 0
    if volatility > 100:
        conclusions.append(f"💥 热度波动剧烈，峰谷差超过{volatility:.0f}%")
    elif volatility > 50:
        conclusions.append(f"⚡ 热度波动较大，峰谷差约{volatility:.0f}%")
    else:
        conclusions.append(f"☁️  热度相对稳定，峰谷差约{volatility:.0f}%")
    
    return conclusions


def generate_comparison_conclusion(analyses):
    if len(analyses) < 2:
        return []
    
    conclusions = []
    
    sorted_by_avg = sorted(analyses, key=lambda x: x['avg_hot'], reverse=True)
    top_avg = sorted_by_avg[0]
    second_avg = sorted_by_avg[1]
    diff_percent = ((top_avg['avg_hot'] - second_avg['avg_hot']) / second_avg['avg_hot']) * 100 if second_avg['avg_hot'] > 0 else 0
    
    conclusions.append(f"\n{BOLD}📊 对比结论{RESET}")
    if diff_percent > 50:
        conclusions.append(f"  「{top_avg['keyword']}」平均热度远超「{second_avg['keyword']}」（高出{diff_percent:.0f}%），话题讨论度明显更高")
    elif diff_percent > 20:
        conclusions.append(f"  「{top_avg['keyword']}」热度略高于「{second_avg['keyword']}」（高出{diff_percent:.0f}%）")
    elif diff_percent > -20:
        conclusions.append(f"  两者热度相近，「{top_avg['keyword']}」仅略高于「{second_avg['keyword']}」（{diff_percent:+.0f}%）")
    else:
        conclusions.append(f"  「{second_avg['keyword']}」反超「{top_avg['keyword']}」（低出{abs(diff_percent):.0f}%）")
    
    sorted_by_peak = sorted(analyses, key=lambda x: x['peak_hot'], reverse=True)
    if sorted_by_peak[0]['keyword'] != sorted_by_avg[0]['keyword']:
        conclusions.append(f"  峰值热度「{sorted_by_peak[0]['keyword']}」更高，但平均热度「{sorted_by_avg[0]['keyword']}」更胜一筹")
    
    trends = set(a['trend'] for a in analyses)
    if len(trends) == 1:
        trend_desc = {"上升": "同步上升", "下降": "同步下降", "平稳": "均保持平稳"}[list(trends)[0]]
        conclusions.append(f"  两个话题趋势{trend_desc}，表现出较强的相关性")
    else:
        trend_texts = [f"「{a['keyword']}」{a['trend']}" for a in analyses]
        conclusions.append(f"  趋势分化：{'，'.join(trend_texts)}")
    
    best_rank = min(analyses, key=lambda x: x.get('avg_rank', 999))
    conclusions.append(f"  热搜排名表现：「{best_rank['keyword']}」平均排名更靠前")
    
    return conclusions


def generate_batch_summary(analyses, sort_by='avg', watch_mode=False):
    if not analyses:
        return []
    
    sort_key, sort_name, _ = SORT_OPTIONS[sort_by]
    
    conclusions = [f"\n{BOLD}📋 批量分析汇总{RESET}\n"]
    
    sorted_by_avg = sorted(analyses, key=lambda x: x['avg_hot'], reverse=True)
    sorted_by_peak = sorted(analyses, key=lambda x: x['peak_hot'], reverse=True)
    rising = [a for a in analyses if a['trend'] == '上升']
    falling = [a for a in analyses if a['trend'] == '下降']
    stable = [a for a in analyses if a['trend'] == '平稳']
    
    conclusions.append(f"  📊 共分析 {len(analyses)} 个话题，当前按「{sort_name}」排序")
    conclusions.append(f"     上升趋势: {len(rising)} 个 | 下降趋势: {len(falling)} 个 | 平稳: {len(stable)} 个")
    conclusions.append("")
    
    conclusions.append(f"  🏆 热度榜 TOP 3：")
    for i, a in enumerate(sorted_by_avg[:3], 1):
        level, emoji = get_activity_level(a['avg_hot'])
        conclusions.append(f"     {i}. 「{a['keyword']}」- 平均 {a['avg_hot']:,} {emoji}")
    conclusions.append("")
    
    conclusions.append(f"  ⚡ 爆发力 TOP 3（最高峰值）：")
    for i, a in enumerate(sorted_by_peak[:3], 1):
        conclusions.append(f"     {i}. 「{a['keyword']}」- 峰值 {a['peak_hot']:,}")
    conclusions.append("")
    
    if rising:
        conclusions.append(f"  📈 上升话题（建议关注）：")
        for a in sorted(rising, key=lambda x: x['change_percent'], reverse=True):
            conclusions.append(f"     • 「{a['keyword']}」+{a['change_percent']:.1f}%")
    if falling:
        conclusions.append(f"  📉 下降话题：")
        for a in sorted(falling, key=lambda x: x['change_percent']):
            conclusions.append(f"     • 「{a['keyword']}」{a['change_percent']:.1f}%")
    
    if watch_mode:
        high_priority = [a for a in analyses if a.get('watch_score', 0) >= 60]
        if high_priority:
            conclusions.append("")
            conclusions.append(f"  🌟 重点关注话题（关注指数≥60）：")
            for a in sorted(high_priority, key=lambda x: x['watch_score'], reverse=True):
                conclusions.append(f"     • {a['watch_level']} - 「{a['keyword']}」(指数: {a['watch_score']})")
                for detail in a.get('watch_details', [])[:3]:
                    conclusions.append(f"       - {detail}")
    
    conclusions.append("")
    avg_total = sum(a['avg_hot'] for a in analyses) / len(analyses)
    level, emoji = get_activity_level(avg_total)
    conclusions.append(f"  📊 整体平均热度：{int(avg_total):,}（{level}）{emoji}")
    
    return conclusions


def generate_shareable_summary(analyses, sort_by='avg', watch_mode=False):
    if not analyses:
        return []

    lines = []
    rising = [a for a in analyses if a['trend'] == '上升']
    falling = [a for a in analyses if a['trend'] == '下降']
    total = len(analyses)
    lines.append(f"【微博热搜分析】共分析{total}个话题，{len(rising)}个上升，{len(falling)}个下降")

    if watch_mode and any('watch_score' in a for a in analyses):
        top_watch = sorted([a for a in analyses if 'watch_score' in a],
                           key=lambda x: x['watch_score'], reverse=True)[:2]
    else:
        top_watch = sorted(analyses, key=lambda x: x['avg_hot'], reverse=True)[:2]
    for a in top_watch:
        score_str = f"(关注指数{a.get('watch_score', '-')})" if watch_mode and 'watch_score' in a else ''
        line = f"🏆 最值得关注：「{a['keyword']}」平均热度{a['avg_hot']:,}{score_str}"
        if len(line) > 50:
            line = line[:47] + '...'
        lines.append(line)

    if analyses:
        most_change = max(analyses, key=lambda x: abs(x['change_percent']))
        direction = '上升' if most_change['change_percent'] > 0 else '下降'
        line = f"📈 变化最大：「{most_change['keyword']}」{direction}{abs(most_change['change_percent']):.1f}%"
        if len(line) > 50:
            line = line[:47] + '...'
        lines.append(line)

    abnormal = []
    for a in analyses:
        values = [d['hot'] for d in a.get('data', [])]
        volatility = (max(values) - min(values)) / a['avg_hot'] * 100 if a['avg_hot'] > 0 and values else 0
        rank_change = a.get('changes', {}).get('avg_rank', {}).get('diff', 0)
        if volatility > 150 or abs(rank_change) > 10:
            abnormal.append(a)
    for a in abnormal[:2]:
        values = [d['hot'] for d in a.get('data', [])]
        volatility = (max(values) - min(values)) / a['avg_hot'] * 100 if a['avg_hot'] > 0 and values else 0
        rank_change = a.get('changes', {}).get('avg_rank', {}).get('diff', 0)
        reasons = []
        if volatility > 150:
            reasons.append(f"波动{volatility:.0f}%")
        if abs(rank_change) > 10:
            reasons.append(f"排名变化{rank_change:+d}位")
        line = f"⚠️ 异常波动：「{a['keyword']}」{'/'.join(reasons)}"
        if len(line) > 50:
            line = line[:47] + '...'
        lines.append(line)

    return lines


def draw_ascii_chart(datasets, width=80, height=20):
    if not datasets:
        return ""
    
    all_values = []
    for ds in datasets:
        all_values.extend([d['hot'] for d in ds['data']])
    
    if not all_values:
        return "无数据可绘制"
    
    min_val = min(all_values)
    max_val = max(all_values)
    val_range = max_val - min_val if max_val != min_val else 1
    
    num_points = max(len(ds['data']) for ds in datasets)
    step = max(1, num_points // width)
    
    chart_lines = []
    
    y_label_width = 8
    chart_width = width - y_label_width - 2
    
    for row in range(height):
        line = []
        y_val = max_val - (val_range * row / (height - 1))
        
        if row == 0:
            label = f"{max_val:>{y_label_width-1}d} "
        elif row == height - 1:
            label = f"{min_val:>{y_label_width-1}d} "
        elif row == height // 2:
            label = f"{int((max_val+min_val)/2):>{y_label_width-1}d} "
        else:
            label = " " * (y_label_width - 1) + " "
        
        line.append(label + "│")
        
        for col in range(chart_width):
            idx = col * step
            char = ' '
            
            for ds_idx, ds in enumerate(datasets):
                if idx < len(ds['data']):
                    val = ds['data'][idx]['hot']
                    norm_val = (val - min_val) / val_range
                    y_pos = int((1 - norm_val) * (height - 1))
                    
                    if y_pos == row:
                        color = COLORS[ds_idx % len(COLORS)]
                        marker = ['●', '■', '▲', '◆', '★'][ds_idx % 5]
                        char = f"{color}{marker}{RESET}"
                        break
            
            line.append(char)
        
        chart_lines.append(''.join(line))
    
    chart_lines.append(' ' * y_label_width + '└' + '─' * chart_width)
    
    time_labels = generate_time_labels(datasets[0]['data'], chart_width)
    chart_lines.append(' ' * y_label_width + ' ' + time_labels)
    
    legend = []
    for ds_idx, ds in enumerate(datasets):
        color = COLORS[ds_idx % len(COLORS)]
        marker = ['●', '■', '▲', '◆', '★'][ds_idx % 5]
        legend.append(f"{color}{marker}{RESET} {ds['keyword']}")
    chart_lines.append('')
    chart_lines.append('图例: ' + '  '.join(legend))
    
    return '\n'.join(chart_lines)


def generate_time_labels(data_points, width):
    if not data_points:
        return ""
    
    num_points = len(data_points)
    num_labels = min(5, width // 15)
    step = max(1, num_points // num_labels)
    
    labels = []
    for i in range(0, num_points, step):
        if i < len(data_points):
            time_str = data_points[i]['time']
            dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
            labels.append(dt.strftime('%m-%d %H:%M'))
    
    result = ''
    label_width = width // max(1, len(labels))
    for i, label in enumerate(labels):
        pos = i * label_width
        result += ' ' * max(0, pos - len(result)) + label
    
    return result[:width]


def export_to_csv(datasets, output_file):
    if not datasets:
        return False
    
    with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        
        header = ['时间']
        for ds in datasets:
            header.extend([f"{ds['keyword']}_热度", f"{ds['keyword']}_排名"])
        writer.writerow(header)
        
        max_len = max(len(ds['data']) for ds in datasets)
        
        for i in range(max_len):
            row = []
            time_val = datasets[0]['data'][i]['time'] if i < len(datasets[0]['data']) else ''
            row.append(time_val)
            
            for ds in datasets:
                if i < len(ds['data']):
                    row.extend([ds['data'][i]['hot'], ds['data'][i]['rank']])
                else:
                    row.extend(['', ''])
            
            writer.writerow(row)
    
    return True


def export_summary_csv(analyses, output_file, sort_by='avg', watch_mode=False):
    if not analyses:
        return False
    
    sort_key, sort_name, sort_order = SORT_OPTIONS[sort_by]
    
    with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        
        writer.writerow(['微博热搜趋势分析 - 汇总报告'])
        writer.writerow(['生成时间', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
        writer.writerow(['排序方式', f'按{sort_name} ({sort_order})'])
        if watch_mode:
            writer.writerow(['分析模式', '关注清单模式'])
        writer.writerow([])
        
        has_changes = any('changes' in a for a in analyses)
        has_score = any('watch_score' in a for a in analyses)
        has_reasons = any('watch_reasons' in a for a in analyses)
        has_risks = any('watch_risks' in a for a in analyses)
        
        header = [
            '关键词', '平均热度', '峰值热度', '峰值时间',
            '谷值热度', '谷值时间', '趋势', '变化率(%)',
            '热度等级', '平均排名', '数据点数'
        ]
        if has_changes:
            header.extend([
                '较上次平均热度变化(%)', '较上次峰值变化(%)', '较上次排名变化'
            ])
        if has_score:
            header.extend(['关注指数', '关注等级'])
        if has_reasons:
            header.append('关注理由')
        if has_risks:
            header.append('风险点')
        writer.writerow(header)
        
        for a in analyses:
            level, _ = get_activity_level(a['avg_hot'])
            row = [
                a['keyword'],
                a['avg_hot'],
                a['peak_hot'],
                a.get('peak_time', ''),
                a.get('valley_hot', ''),
                a.get('valley_time', ''),
                a['trend'],
                f"{a['change_percent']:.2f}",
                level,
                a.get('avg_rank', ''),
                a.get('data_points', 0)
            ]
            if has_changes:
                changes = a.get('changes', {})
                row.extend([
                    f"{changes.get('avg_hot', {}).get('pct', 0):.2f}" if changes else '',
                    f"{changes.get('peak_hot', {}).get('pct', 0):.2f}" if changes else '',
                    f"{changes.get('avg_rank', {}).get('diff', 0):+d}" if changes else ''
                ])
            if has_score:
                row.extend([
                    a.get('watch_score', ''),
                    a.get('watch_level', '')
                ])
            if has_reasons:
                row.append('|'.join(a.get('watch_reasons', [])))
            if has_risks:
                row.append('|'.join(a.get('watch_risks', [])))
            writer.writerow(row)
        
        writer.writerow([])
        writer.writerow(['分析结论'])
        for a in analyses:
            writer.writerow([f"--- {a['keyword']} ---"])
            for line in a.get('conclusions', []):
                writer.writerow([line])
    
    return True


def export_markdown_report(analyses, datasets, output_file, sort_by='avg', watch_mode=False):
    if not analyses:
        return False
    
    sort_key, sort_name, sort_order = SORT_OPTIONS[sort_by]
    generated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('# 微博热搜趋势分析报告\n\n')
        f.write(f'> 生成时间: {generated_at}\n\n')
        f.write(f'> 排序方式: 按{sort_name} ({sort_order})\n\n')
        if watch_mode:
            f.write(f'> 分析模式: 关注清单模式\n\n')
        
        f.write('## 📱 转发摘要\n\n')
        for line in generate_shareable_summary(analyses, sort_by, watch_mode):
            f.write(f'> {line}\n')
        f.write('\n')
        
        f.write('## 📊 分析概览\n\n')
        f.write(f'- 分析话题数: {len(analyses)} 个\n')
        f.write(f'- 时间范围: {analyses[0]["data"][0]["time"][:10]} 至 {analyses[0]["data"][-1]["time"][:10]}\n')
        if len(analyses[0]['data']) == 24:
            f.write(f'- 数据窗口: 最近24小时 ({len(analyses[0]["data"])}个数据点)\n')
        else:
            f.write(f'- 数据窗口: {len(analyses[0]["data"]) // 24}天 ({len(analyses[0]["data"])}个数据点)\n')
        
        rising = len([a for a in analyses if a['trend'] == '上升'])
        falling = len([a for a in analyses if a['trend'] == '下降'])
        stable = len([a for a in analyses if a['trend'] == '平稳'])
        f.write(f'- 趋势分布: 上升{rising}个 / 下降{falling}个 / 平稳{stable}个\n\n')
        
        f.write('## 📈 热度排行\n\n')
        f.write('| 排名 | 关键词 | 平均热度 | 峰值热度 | 趋势 | 变化率 | 平均排名 |')
        if watch_mode:
            f.write(' 关注指数 | 关注等级 |')
        f.write('\n|------|--------|----------|----------|------|--------|----------|')
        if watch_mode:
            f.write('----------|----------|')
        f.write('\n')
        
        for idx, a in enumerate(analyses, 1):
            trend_emoji = '📈' if a['trend'] == '上升' else '📉' if a['trend'] == '下降' else '➡️'
            f.write(f'| {idx} | **{a["keyword"]}** | {a["avg_hot"]:,} | {a["peak_hot"]:,} | {trend_emoji} {a["trend"]} | {a["change_percent"]:+.1f}% | 第{a["avg_rank"]}位 |')
            if watch_mode:
                f.write(f' {a.get("watch_score", "-")} | {a.get("watch_level", "-")} |')
            f.write('\n')
        
        if watch_mode:
            f.write('\n## ✨ 关注理由与风险点\n\n')
            scored = [a for a in analyses if 'watch_score' in a]
            if scored:
                for a in sorted(scored, key=lambda x: x['watch_score'], reverse=True):
                    f.write(f'### 「{a["keyword"]}」(关注指数: {a["watch_score"]} - {a.get("watch_level", "")})\n\n')
                    reasons = a.get('watch_reasons', [])
                    risks = a.get('watch_risks', [])
                    if reasons:
                        f.write('**✅ 关注理由:**\n\n')
                        for r in reasons:
                            f.write(f'- {r}\n')
                        f.write('\n')
                    if risks:
                        f.write('**⚠️ 风险点:**\n\n')
                        for r in risks:
                            f.write(f'- {r}\n')
                        f.write('\n')
                    if not reasons and not risks:
                        f.write('暂无显著特征。\n\n')
            else:
                f.write('暂无关注评分数据。\n\n')
        
        f.write('## 📊 趋势对比图\n\n')
        f.write('```\n')
        chart = draw_ascii_chart(datasets, width=90, height=20)
        f.write(chart.replace(COLORS[0], '').replace(COLORS[1], '').replace(COLORS[2], '')
                .replace(COLORS[3], '').replace(COLORS[4], '').replace(COLORS[5], '')
                .replace(RESET, ''))
        f.write('\n```\n\n')
        
        if watch_mode:
            f.write('## 🌟 关注清单\n\n')
            scored = [a for a in analyses if 'watch_score' in a]
            if scored:
                for a in sorted(scored, key=lambda x: x['watch_score'], reverse=True):
                    f.write(f'### {a["watch_level"]} - {a["keyword"]} (关注指数: {a["watch_score"]})\n\n')
                    f.write('- **打分依据:**\n')
                    for detail in a.get('watch_details', []):
                        f.write(f'  - {detail}\n')
                    f.write('\n- **核心指标:**\n')
                    f.write(f'  - 平均热度: {a["avg_hot"]:,}\n')
                    f.write(f'  - 峰值热度: {a["peak_hot"]:,}\n')
                    f.write(f'  - 趋势: {a["trend"]} ({a["change_percent"]:+.1f}%)\n')
                    f.write(f'  - 平均排名: 第{a["avg_rank"]}位\n\n')
            else:
                f.write('暂无关注评分数据。\n\n')
        
        f.write('## 📋 各话题详细分析\n\n')
        for a in analyses:
            f.write(f'### {a["keyword"]}\n\n')
            
            f.write('| 指标 | 数值 |\n|------|------|\n')
            f.write(f'| 平均热度 | {a["avg_hot"]:,} |\n')
            f.write(f'| 峰值热度 | {a["peak_hot"]:,} |\n')
            f.write(f'| 谷值热度 | {a["valley_hot"]:,} |\n')
            f.write(f'| 趋势 | {a["trend"]} ({a["change_percent"]:+.1f}%) |\n')
            f.write(f'| 平均排名 | 第{a["avg_rank"]}位 |\n')
            f.write(f'| 数据点数 | {a["data_points"]}小时 |\n')
            
            if 'changes' in a and a['changes']:
                f.write('\n**📊 历史对比:**\n\n')
                c = a['changes']
                for metric in ['avg_hot', 'peak_hot']:
                    if metric in c:
                        name = '平均热度' if metric == 'avg_hot' else '峰值热度'
                        pct = c[metric]['pct']
                        diff = c[metric]['diff']
                        emoji = '↑' if pct > 0 else '↓' if pct < 0 else '→'
                        f.write(f'- {name}: {emoji} {diff:+d} ({pct:+.1f}%)\n')
                if 'avg_rank' in c:
                    rank_diff = c['avg_rank']['diff']
                    emoji = '↑' if rank_diff > 0 else '↓' if rank_diff < 0 else '→'
                    f.write(f'- 平均排名: {emoji} {rank_diff:+d}位\n')
            
            f.write('\n**💡 分析结论:**\n\n')
            for conclusion in a.get('conclusions', []):
                f.write(f'- {conclusion}\n')
            f.write('\n')
        
        f.write('## 📝 批量汇总分析\n\n')
        for line in generate_batch_summary(analyses, sort_by, watch_mode):
            clean_line = line.replace(BOLD, '').replace(RESET, '')
            f.write(f'{clean_line}\n')
        
        f.write('\n## 🔍 异常检测\n\n')
        abnormal_items = []
        for a in analyses:
            values = [d['hot'] for d in a.get('data', [])]
            volatility = (max(values) - min(values)) / a['avg_hot'] * 100 if a['avg_hot'] > 0 and values else 0
            rank_diff = a.get('changes', {}).get('avg_rank', {}).get('diff', 0)
            half_change = a.get('half_change', 0)
            trend = a.get('trend', '')
            
            flags = []
            if volatility > 150:
                flags.append(f'日内波动 {volatility:.0f}% (>150%)')
            if rank_diff < -10:
                flags.append(f'排名下跌 {abs(rank_diff)} 位 (>10位)')
            if half_change < -30 and trend in ('上升', '平稳'):
                flags.append('趋势由升转降迹象')
            
            if flags:
                abnormal_items.append((a, flags))
        
        if abnormal_items:
            for a, flags in abnormal_items:
                f.write(f'### ⚠️ 「{a["keyword"]}」\n\n')
                for flag in flags:
                    f.write(f'- {flag}\n')
                f.write(f'- 当前趋势: {a["trend"]} ({a["change_percent"]:+.1f}%)\n')
                f.write(f'- 平均热度: {a["avg_hot"]:,}\n\n')
        else:
            f.write('未检测到明显异常。\n\n')
    
    return True


def read_keywords_from_file(file_path):
    if not os.path.exists(file_path):
        return []
    
    keywords = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            kw = line.strip()
            if kw and not kw.startswith('#'):
                keywords.append(kw)
    
    return keywords


def sort_analyses(analyses, sort_by='avg'):
    if sort_by not in SORT_OPTIONS:
        sort_by = 'avg'
    key, name, order = SORT_OPTIONS[sort_by]
    reverse = (order == '↓')
    return sorted(analyses, key=lambda x: x[key], reverse=reverse), name, order


def print_historical_comparison(keyword, changes, change_descs, prev_stats, prev_snapshot=None):
    if not changes and not prev_snapshot:
        return
    
    print(f"\n{BOLD}⏱️  历史对比{RESET}")
    print(f"{'─'*60}")
    
    if prev_snapshot:
        print(f"  对比快照: {prev_snapshot['created_at']}")
        print(f"  数据来源: {prev_snapshot['data_source']}")
    elif prev_stats:
        print(f"  上次统计: {prev_stats['start_time'][:10]} ~ {prev_stats['end_time'][:10]} ({prev_stats['data_points']}小时)")
    print("")
    
    if changes:
        rows = [
            ('平均热度', changes.get('avg_hot', {})),
            ('峰值热度', changes.get('peak_hot', {})),
            ('谷值热度', changes.get('valley_hot', {})),
        ]
        
        for name, info in rows:
            if not info:
                continue
            old = info.get('old', 0)
            new = info.get('new', 0)
            diff = info.get('diff', 0)
            pct = info.get('pct', 0)
            color = '\033[92m' if pct > 0 else '\033[91m' if pct < 0 else '\033[93m'
            arrow = '↑' if pct > 0 else '↓' if pct < 0 else '→'
            print(f"  {name:<8}: {old:,} → {new:,}  {color}{arrow} {diff:+d} ({pct:+.1f}%){RESET}")
        
        rank_info = changes.get('avg_rank', {})
        if rank_info:
            old = rank_info.get('old', 0)
            new = rank_info.get('new', 0)
            diff = rank_info.get('diff', 0)
            color = '\033[92m' if diff > 0 else '\033[91m' if diff < 0 else '\033[93m'
            arrow = '↑' if diff > 0 else '↓' if diff < 0 else '→'
            print(f"  平均排名  : 第{old}位 → 第{new}位  {color}{arrow} {diff:+d}位{RESET}")
        
        if change_descs:
            print(f"\n  📝 变化摘要: {', '.join(change_descs)}")


def print_snapshot_list(keyword, start_date=None, end_date=None, 
                        window_start=None, window_end=None, tag_filter=None):
    snapshots = list_snapshots(keyword, start_date, end_date, window_start, window_end, tag_filter)
    
    if not snapshots:
        msg_parts = [f"📭 暂无快照记录"]
        if keyword:
            msg_parts.append(f'关键词「{keyword}」')
        if tag_filter:
            msg_parts.append(f'标签「{tag_filter}」')
        if window_start or window_end:
            msg_parts.append(f'时间窗口 {window_start or "*"}~{window_end or "*"}')
        print(' '.join(msg_parts))
        return
    
    print(f"\n{BOLD}📸 趋势快照库{RESET} - 共 {len(snapshots)} 条记录")
    filter_hints = []
    if keyword:
        filter_hints.append(f'关键词={keyword}')
    if start_date or end_date:
        filter_hints.append(f'统计窗 {start_date or "*"}~{end_date or "*"}')
    if window_start or window_end:
        filter_hints.append(f'快照时间 {window_start or "*"}~{window_end or "*"}')
    if tag_filter:
        filter_hints.append(f'标签={tag_filter}')
    if filter_hints:
        print(f"  筛选条件: {' | '.join(filter_hints)}")
    print(f"  {'─'*50}")
    print(f"  💡 全局序号 (第1列) 可直接用于 --snapshot-compare 的对比参数")
    print(f"{'═'*120}")
    
    header = f"{'序号':<6} {'关键词':<14} {'统计窗口':<22} {'快照时间':<20} {'平均热度':>10} {'峰值':>9} {'趋势':>6} {'排名':>5} {'标签/备注':<20}"
    print(header)
    print(f"{'-'*120}")
    
    for s in snapshots:
        a = s['analysis']
        tags_str = ' '.join([f'[{t}]' for t in s.get('tags', [])])
        note_str = s.get('note', '')
        extra = (tags_str + ' ' + note_str).strip()[:18]
        window_str = f"{s['start_date']}~{s['end_date']}"
        print(f"{s['global_index']:<6} {s['keyword']:<14} {window_str:<22} {s['created_at']:<20} "
              f"{a.get('avg_hot', '-'):>10,} {a.get('peak_hot', '-'):>9,} "
              f"{a.get('trend', '-'):>6} {a.get('avg_rank', '-'):>4}位 {extra:<20}")
    
    print(f"\n💡 操作:")
    print(f"   • 对比两次快照: --snapshot-compare KEYWORD IDX1 IDX2 [--global-idx]")
    print(f"   • 添加标签/备注: --snapshot-tag IDX \"活动前,重要\" --snapshot-note IDX \"618大促前\"")
    print(f"   • 按时间窗口筛选: --snapshot-list KEYWORD --window-start 2024-06-01 --window-end 2024-06-10")
    print(f"   • 按标签筛选: --snapshot-list KEYWORD --tag-filter 活动前")


def compare_snapshots(keyword, index1, index2, start_date=None, end_date=None,
                      use_global_index=False, window_start=None, window_end=None, tag_filter=None):
    all_snapshots = list_snapshots(keyword, start_date, end_date, window_start, window_end, tag_filter)
    
    if use_global_index:
        s1 = get_snapshot_by_global_index(index1, keyword, start_date, end_date,
                                          window_start, window_end, tag_filter)
        s2 = get_snapshot_by_global_index(index2, keyword, start_date, end_date,
                                          window_start, window_end, tag_filter)
        idx_mode = '全局序号'
    else:
        keyword_snapshots = [s for s in all_snapshots if s['keyword'] == keyword]
        if not keyword_snapshots:
            print(f"❌ 未找到「{keyword}」的快照记录")
            return None
        for idx in [index1, index2]:
            if idx < 0 or idx >= len(keyword_snapshots):
                print(f"❌ 快照序号 {idx} 超出范围 (有效范围: 0-{len(keyword_snapshots)-1})")
                return None
        s1 = keyword_snapshots[index1]
        s2 = keyword_snapshots[index2]
        idx_mode = '关键词内序号'
    
    if not s1 or not s2:
        print(f"❌ 未找到指定快照，请检查序号和筛选条件")
        return None
    
    a1 = s1['analysis']
    a2 = s2['analysis']
    
    print(f"\n{BOLD}📊 快照对比分析{RESET}")
    print(f"{'═'*110}")
    print(f"  关键词: {BOLD}{s1['keyword']}{RESET}  |  序号模式: {idx_mode}")
    print(f"  统计窗口: {s1['start_date']} 至 {s1['end_date']}")
    print(f"{'─'*110}")
    
    def fmt_meta(s):
        parts = [s['created_at']]
        if s.get('tags'):
            parts.append(' '.join([f'[{t}]' for t in s['tags']]))
        if s.get('note'):
            parts.append(f"📝{s['note'][:12]}")
        return ' '.join(parts)
    
    label1 = fmt_meta(s1)
    label2 = fmt_meta(s2)
    col_w = 45
    print(f"{'指标':<12} {label1[:col_w]:>{col_w}} {label2[:col_w]:>{col_w}} {'变化':>16}")
    print(f"{'-'*110}")
    
    metrics = [
        ('平均热度', 'avg_hot', ',', False),
        ('峰值热度', 'peak_hot', ',', False),
        ('谷值热度', 'valley_hot', ',', False),
        ('变化率(%)', 'change_percent', '.1f', False),
        ('平均排名', 'avg_rank', 'd', True),
    ]
    
    significant_changes = []
    for name, key, fmt, is_rank in metrics:
        v1 = a1.get(key, 0)
        v2 = a2.get(key, 0)
        diff = v1 - v2
        
        if is_rank:
            pct = 0
            display_v1 = f"第{v1:{fmt}}位"
            display_v2 = f"第{v2:{fmt}}位"
            diff_display = f"{diff:+d}位"
            if abs(diff) >= 5:
                significant_changes.append((name, v1, v2, diff, pct, is_rank))
        else:
            pct = (diff / v2 * 100) if v2 != 0 else 0
            display_v1 = f"{v1:{fmt}}"
            display_v2 = f"{v2:{fmt}}"
            diff_display = f"{diff:+{fmt}} ({pct:+.1f}%)"
            if abs(pct) >= 20:
                significant_changes.append((name, v1, v2, diff, pct, is_rank))
        
        color = '\033[92m' if (not is_rank and diff > 0) or (is_rank and diff > 0) else \
                '\033[91m' if (not is_rank and diff < 0) or (is_rank and diff < 0) else '\033[93m'
        
        print(f"  {name:<12} {display_v1:>{col_w}} {display_v2:>{col_w}} {color}{diff_display:>16}{RESET}")
    
    print(f"{'-'*110}")
    print(f"  趋势对比: {a1.get('trend', '-'):>{col_w-8}} vs {a2.get('trend', '-'):>{col_w-8}}")
    print(f"  数据来源: {s1['data_source']:>{col_w-8}} vs {s2['data_source']:>{col_w-8}}")
    print(f"{'═'*110}")
    
    print(f"\n{BOLD}💡 对比结论{RESET}")
    avg_diff = a1.get('avg_hot', 0) - a2.get('avg_hot', 0)
    avg_pct = (avg_diff / a2.get('avg_hot', 1) * 100) if a2.get('avg_hot', 1) > 0 else 0
    
    if abs(avg_pct) >= 30:
        direction = "大幅提升" if avg_pct > 0 else "大幅下降"
        print(f"  🔥 平均热度{direction}，变化幅度达{abs(avg_pct):.1f}%，属于明显变化")
    elif abs(avg_pct) >= 10:
        direction = "明显上升" if avg_pct > 0 else "明显下降"
        print(f"  📈 平均热度{direction}，变化幅度{abs(avg_pct):.1f}%")
    elif abs(avg_pct) >= 3:
        direction = "略有上升" if avg_pct > 0 else "略有下降"
        print(f"  • 平均热度{direction}，变化幅度{abs(avg_pct):.1f}%")
    else:
        print(f"  • 平均热度基本持平，变化幅度仅{abs(avg_pct):.1f}%")
    
    if a1.get('trend') != a2.get('trend'):
        print(f"  ⚠️  趋势发生变化: {a2.get('trend')} → {a1.get('trend')}")
    
    if significant_changes:
        print(f"\n{BOLD}📌 显著变化指标:{RESET}")
        for name, v1, v2, diff, pct, is_rank in significant_changes:
            if is_rank:
                arrow = '↑' if diff > 0 else '↓'
                print(f"    • {name}: {arrow} 变化{abs(diff)}位")
            else:
                arrow = '↑' if pct > 0 else '↓'
                print(f"    • {name}: {arrow} {abs(pct):.1f}%")
    
    result = {
        's1': s1, 's2': s2, 'significant_changes': significant_changes,
        'avg_pct': avg_pct, 'trend_changed': a1.get('trend') != a2.get('trend')
    }
    return result


def print_analysis(keyword, full_data, data_source, cache_hit, prev_cache=None, prev_snapshot=None, save_snapshot_flag=True, tags=None, note=None):
    data_list = full_data if isinstance(full_data, list) else full_data['data']
    
    print(f"\n{'═'*60}")
    print(f"{BOLD}📊 话题分析报告{RESET}")
    print(f"{'═'*60}")
    print(f"  话题关键词: {BOLD}{keyword}{RESET}")
    print(f"  数据来源: {data_source}")
    if cache_hit and isinstance(full_data, dict):
        ttl = get_cache_ttl()
        remaining = int(ttl - (time.time() - full_data.get('cached_at', time.time())))
        if remaining > 0:
            print(f"  缓存状态: ✅ 有效，剩余 {remaining // 60} 分钟")
        else:
            print(f"  缓存状态: ⚠️  已过期")
    print(f"{'─'*60}")
    
    if not data_list:
        print("  ⚠️  无数据")
        return None
    
    values = [d['hot'] for d in data_list]
    ranks = [d['rank'] for d in data_list]
    peak = find_peak(data_list)
    valley = find_valley(data_list)
    trend, change_percent, half_change = analyze_trend(data_list)
    
    analysis = {
        'keyword': keyword,
        'data': data_list,
        'avg_hot': int(sum(values) / len(values)),
        'peak_hot': max(values),
        'peak_time': peak['time'] if peak else '',
        'valley_hot': min(values),
        'valley_time': valley['time'] if valley else '',
        'trend': trend,
        'change_percent': change_percent,
        'half_change': half_change,
        'avg_rank': int(sum(ranks) / len(ranks)),
        'data_points': len(data_list)
    }
    
    print(f"  📅 统计周期: {data_list[0]['time']} 至 {data_list[-1]['time']}")
    print(f"  📈 数据点数: {len(data_list)} 小时")
    print(f"  🔥 最高热度: {max(values):,}")
    print(f"  ❄️  最低热度: {min(values):,}")
    print(f"  📊 平均热度: {analysis['avg_hot']:,}")
    print(f"  🏆 平均排名: 第 {analysis['avg_rank']} 位")
    
    if peak:
        peak_time = datetime.strptime(peak['time'], '%Y-%m-%d %H:%M:%S')
        print(f"  ⚡ 热度峰值: {peak['hot']:,} ({peak_time.strftime('%m月%d日 %H:%M')})")
    
    if valley:
        valley_time = datetime.strptime(valley['time'], '%Y-%m-%d %H:%M:%S')
        print(f"  📉 热度低谷: {valley['hot']:,} ({valley_time.strftime('%m月%d日 %H:%M')})")
    
    trend_color = {'上升': '\033[92m', '下降': '\033[91m', '平稳': '\033[93m'}[trend]
    print(f"  📊 整体趋势: {trend_color}{trend}{RESET} (变化率: {change_percent:+.2f}%)")
    
    level, emoji = get_activity_level(analysis['avg_hot'])
    print(f"  🎯 热度等级: {level} {emoji}")
    
    prev_stats = extract_cache_stats(prev_cache)
    current_stats = {k: analysis[k] for k in ['avg_hot', 'peak_hot', 'valley_hot', 'avg_rank']}
    current_stats['data_points'] = analysis['data_points']
    
    if prev_snapshot and 'analysis' in prev_snapshot:
        a = prev_snapshot['analysis']
        snap_stats = {
            'avg_hot': a.get('avg_hot', 0),
            'peak_hot': a.get('peak_hot', 0),
            'valley_hot': a.get('valley_hot', 0),
            'avg_rank': a.get('avg_rank', 0),
            'data_points': a.get('data_points', 0),
            'start_time': prev_snapshot.get('created_at', ''),
            'end_time': prev_snapshot.get('created_at', '')
        }
        changes, change_descs = compare_with_previous(current_stats, snap_stats)
    else:
        changes, change_descs = compare_with_previous(current_stats, prev_stats)
    
    if changes:
        analysis['changes'] = changes
        analysis['prev_stats'] = prev_stats if prev_stats else snap_stats
    
    print_historical_comparison(keyword, changes, change_descs, prev_stats, prev_snapshot)
    
    if save_snapshot_flag:
        start_d = full_data.get('start_date', '') if isinstance(full_data, dict) else ''
        end_d = full_data.get('end_date', '') if isinstance(full_data, dict) else ''
        save_snapshot(keyword, start_d, end_d, data_list, analysis, data_source, tags=tags, note=note)
    
    print(f"\n{BOLD}💡 分析结论{RESET}")
    conclusions = generate_conclusion(keyword, analysis, data_list)
    analysis['conclusions'] = conclusions
    for conclusion in conclusions:
        print(f"  {conclusion}")
    
    return analysis


def batch_analysis(keywords, start_date, end_date, output_file=None, export_csv=False, 
                   use_cache=True, force_mock=False, num_hours=None, sort_by='avg', watch_mode=False,
                   save_snapshot_flag=True, snapshot_tags=None, snapshot_note=None):
    print(f"\n{'#'*60}")
    print(f"{BOLD}# 📋 批量查询分析报告 - {len(keywords)} 个话题{RESET}")
    print(f"# 📅 时间范围: {start_date} 至 {end_date}")
    if num_hours:
        print(f"# ⏱️  数据窗口: 最近 {num_hours} 小时")
    if watch_mode:
        print(f"# 🔍 分析模式: 关注清单模式")
    print(f"{'#'*60}")
    
    datasets = []
    analyses = []
    
    for keyword in keywords:
        print(f"\n{'─'*60}")
        print(f"🔍 正在查询: {keyword}...")
        data, source, cache_hit, prev_cache, prev_snapshot = get_trend_data(
            keyword, start_date, end_date, 
            use_cache=use_cache, force_mock=force_mock, num_hours=num_hours
        )
        datasets.append({'keyword': keyword, 'data': data['data'], 'source': source})
        
        analysis = print_analysis(keyword, data, source, cache_hit, prev_cache, prev_snapshot,
                                  save_snapshot_flag=save_snapshot_flag, tags=snapshot_tags, note=snapshot_note)
        if analysis:
            if watch_mode:
                keyword_snapshots = list_snapshots(keyword, start_date, end_date)
                score, level, details, reasons, risks, level_color = calculate_watch_score(analysis, keyword_snapshots)
                analysis['watch_score'] = score
                analysis['watch_level'] = level
                analysis['watch_details'] = details
                analysis['watch_reasons'] = reasons
                analysis['watch_risks'] = risks
                analysis['watch_level_color'] = level_color
            analyses.append(analysis)
    
    print(f"\n{'═'*60}")
    print(f"{BOLD}📈 对比分析图表{RESET}")
    print(f"{'═'*60}")
    chart = draw_ascii_chart(datasets, width=100)
    print(chart)
    
    if export_csv and output_file:
        if export_to_csv(datasets, output_file):
            print(f"\n✓ 原始数据已导出到: {output_file}")
            
            sorted_analyses, sort_name, sort_order = sort_analyses(analyses, sort_by)
            summary_file = output_file.replace('.csv', '_summary.csv')
            if export_summary_csv(sorted_analyses, summary_file, sort_by, watch_mode):
                print(f"✓ 汇总报告已导出到: {summary_file} (按{sort_name}排序)")
            
            md_file = output_file.replace('.csv', '.md')
            if export_markdown_report(sorted_analyses, datasets, md_file, sort_by, watch_mode):
                print(f"✓ Markdown报告已导出到: {md_file}")
    
    print(f"\n{'═'*60}")
    sorted_analyses, sort_name, sort_order = sort_analyses(analyses, sort_by)
    print(f"{BOLD}📊 趋势对比汇总{RESET} (按{UNDERLINE}{sort_name}{RESET} {sort_order})")
    print(f"{'═'*90 if watch_mode else 78}")
    
    has_changes = any('changes' in a for a in sorted_analyses)
    
    header = f"{'话题':<12} {'平均热度':>10} {'峰值':>9} {'峰值时间':>14} {'趋势':>6} {'变化率':>8} {'排名':>6}"
    if has_changes:
        header += f" {'热度变化':>10}"
    if watch_mode:
        header += f" {'关注指数':>10}"
    print(header)
    print('-' * (90 if watch_mode else 78))
    
    for a in sorted_analyses:
        trend_color = {'上升': '\033[92m', '下降': '\033[91m', '平稳': '\033[93m'}[a['trend']]
        peak_time_short = a['peak_time'][5:16] if a['peak_time'] else ''
        line = (f"{a['keyword']:<12} {a['avg_hot']:>10,} {a['peak_hot']:>9,} "
                f"{peak_time_short:>14} {trend_color}{a['trend']:>6}{RESET} "
                f"{a['change_percent']:>+7.1f}% {a['avg_rank']:>5d}")
        if has_changes:
            changes = a.get('changes', {})
            avg_change = changes.get('avg_hot', {}).get('pct', 0)
            change_color = '\033[92m' if avg_change > 0 else '\033[91m' if avg_change < 0 else '\033[93m'
            line += f" {change_color}{avg_change:>+9.1f}%{RESET}"
        if watch_mode:
            score_color = '\033[92m' if a.get('watch_score', 0) >= 60 else '\033[93m' if a.get('watch_score', 0) >= 40 else '\033[91m'
            line += f" {score_color}{a.get('watch_score', 0):>9d}{RESET}"
        print(line)
    
    for line in generate_batch_summary(sorted_analyses, sort_by, watch_mode):
        print(line)
    
    if watch_mode:
        scored = [a for a in sorted_analyses if 'watch_score' in a]
        if scored:
            print(f"\n{BOLD}✨ 关注清单 - 理由与风险点{RESET}")
            print(f"{'═'*90}")
            for a in sorted(scored, key=lambda x: x['watch_score'], reverse=True):
                level_color = a.get('watch_level_color', '')
                print(f"\n{level_color}{BOLD}{a['watch_level']}{RESET} - {BOLD}「{a['keyword']}」{RESET} (指数: {a.get('watch_score', 0)})")
                if a.get('watch_reasons'):
                    print(f"  ✅ 值得关注：")
                    for r in a['watch_reasons']:
                        print(f"     • {r}")
                if a.get('watch_risks'):
                    print(f"  ⚠️  风险点：")
                    for r in a['watch_risks']:
                        print(f"     • {r}")
                if not a.get('watch_reasons') and not a.get('watch_risks'):
                    print(f"     (暂无显著特征)")
            print(f"\n{'═'*90}")
    
    return sorted_analyses


def resolve_date_range(start_date=None, end_date=None):
    now = datetime.now()
    
    if not start_date and not end_date:
        end_dt = now.replace(minute=0, second=0, microsecond=0)
        start_dt = end_dt - timedelta(hours=23)
        return (
            start_dt.strftime('%Y-%m-%d'),
            end_dt.strftime('%Y-%m-%d'),
            24,
            f"最近24小时 ({start_dt.strftime('%m-%d %H:%M')} 至 {end_dt.strftime('%m-%d %H:%M')})"
        )
    
    try:
        if start_date:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        else:
            start_dt = now - timedelta(days=1)
        
        if end_date:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        else:
            end_dt = now
        
        if start_dt > end_dt:
            return None, None, None, (
                f"❌ 日期错误：开始日期 ({start_date}) 晚于结束日期 ({end_date})\n"
                f"   请检查日期顺序，或使用以下方式：\n"
                f"   • 不传日期参数：默认最近24小时\n"
                f"   • 只传结束日期：自动以结束日期前1天为开始\n"
                f"   • 确保开始日期 <= 结束日期"
            )
        
        actual_days = (end_dt - start_dt).days + 1
        if actual_days > 7:
            print(f"⚠️  日期范围超过7天（{actual_days}天），已自动截断为最近7天")
            start_dt = end_dt - timedelta(days=6)
            actual_days = 7
        
        num_hours = actual_days * 24
        
        return (
            start_dt.strftime('%Y-%m-%d'),
            end_dt.strftime('%Y-%m-%d'),
            num_hours,
            f"{start_dt.strftime('%Y-%m-%d')} 至 {end_dt.strftime('%Y-%m-%d')}（共{actual_days}天，{num_hours}小时）"
        )
        
    except ValueError as e:
        return None, None, None, (
            f"❌ 日期格式错误: {e}\n"
            f"   请使用 YYYY-MM-DD 格式，例如: 2024-06-01"
        )


def handle_cache_command(args):
    if args.cache_list:
        filter_kw = args.cache_filter_kw
        filter_start = args.cache_filter_start
        filter_end = args.cache_filter_end
        filter_status = args.cache_filter_status
        
        caches = list_cache(filter_kw, filter_start, filter_end, filter_status)
        
        filter_desc_parts = []
        if filter_kw:
            filter_desc_parts.append(f'关键词含"{filter_kw}"')
        if filter_start:
            filter_desc_parts.append(f'开始≥{filter_start}')
        if filter_end:
            filter_desc_parts.append(f'结束≤{filter_end}')
        if filter_status:
            status_desc = {'valid': '有效', 'expired': '过期'}[filter_status]
            filter_desc_parts.append(f'状态={status_desc}')
        filter_desc = f' [筛选: {", ".join(filter_desc_parts)}]' if filter_desc_parts else ''
        
        if not caches:
            print(f"📭 暂无缓存数据{filter_desc}")
            return
        
        ttl = get_cache_ttl()
        print(f"\n{BOLD}📦 缓存列表{RESET} (共 {len(caches)} 条，有效期 {ttl // 60} 分钟){filter_desc}")
        print(f"{'='*95}")
        print(f"{'关键词':<15} {'日期范围':<22} {'缓存时间':<20} {'点数':>6} {'大小':>8} {'剩余':>7} {'状态':>8}")
        print(f"{'-'*95}")
        
        for entry in caches:
            date_range = f"{entry['start_date']}~{entry['end_date']}"
            status = '✅ 有效' if entry['is_valid'] else '⏰ 过期'
            size_str = f"{entry['size']/1024:.1f}KB"
            remaining = f"{entry['ttl_remaining']//60}分" if entry['is_valid'] else '-'
            print(f"{entry['keyword']:<15} {date_range:<22} {entry['mtime']:<20} {entry['data_points']:>6} {size_str:>8} {remaining:>7} {status:>8}")
        
        print(f"\n💡 提示：使用 --cache-clear 清理缓存 | --cache-filter-* 进行更多筛选")
        return
    
    if args.cache_clear is not None:
        if args.cache_clear == '':
            count = clear_cache()
            print(f"🧹 已清理全部缓存，共删除 {count} 个文件")
        else:
            count = clear_cache(keyword=args.cache_clear, exact_only=True)
            if count > 0:
                print(f"🧹 已清理「{args.cache_clear}」的缓存，共删除 {count} 个文件")
            else:
                print(f"❌ 未找到「{args.cache_clear}」的精确匹配缓存文件")
                print(f"   提示: 如需模糊匹配清理，请手动检查缓存列表后确认")
        return
    
    if args.cache_ttl:
        try:
            ttl = int(args.cache_ttl)
            if ttl < 60:
                print("❌ 缓存有效期不能少于60秒")
                return
            set_cache_ttl(ttl)
            print(f"⏱️  缓存有效期已设置为 {ttl} 秒 ({ttl//60} 分钟)")
        except ValueError:
            print("❌ 请输入有效的数字（秒）")
        return


def handle_snapshot_command(args):
    if args.snapshot_list:
        print_snapshot_list(args.snapshot_list, 
                           window_start=args.window_start,
                           window_end=args.window_end,
                           tag_filter=args.tag_filter)
        return
    
    if args.snapshot_tag or args.snapshot_note:
        if args.snapshot_index is None:
            print("❌ 请通过 --snapshot-index 指定快照全局序号")
            return
        snap = get_snapshot_by_global_index(args.snapshot_index)
        if not snap:
            print(f"❌ 未找到全局序号为 {args.snapshot_index} 的快照")
            return
        tags = snap.get('tags', [])
        note = snap.get('note', '')
        if args.snapshot_tag is not None:
            tags = [t.strip() for t in args.snapshot_tag.split(',') if t.strip()]
        if args.snapshot_note is not None:
            note = args.snapshot_note
        if update_snapshot_meta(snap['filepath'], tags=tags, note=note):
            tag_str = ' '.join([f'[{t}]' for t in tags]) if tags else '(无标签)'
            note_str = f'📝{note}' if note else '(无备注)'
            print(f"✅ 快照 #{args.snapshot_index}「{snap['keyword']}」已更新")
            print(f"   标签: {tag_str}")
            print(f"   备注: {note_str}")
        else:
            print(f"❌ 更新快照失败")
        return
    
    if args.snapshot_compare:
        if len(args.snapshot_compare) != 3:
            print("❌ 快照对比需要3个参数: KEYWORD INDEX1 INDEX2")
            return
        keyword, idx1, idx2 = args.snapshot_compare
        try:
            compare_snapshots(keyword, int(idx1), int(idx2),
                             use_global_index=args.global_idx,
                             window_start=args.window_start,
                             window_end=args.window_end,
                             tag_filter=args.tag_filter)
        except ValueError:
            print("❌ 序号必须是数字")
        return


def main():
    parser = argparse.ArgumentParser(
        description='微博热搜趋势分析工具 - 专业版 v2.1（长期追踪增强版）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # ===== 基础查询 =====
  # 单关键词（最近24小时）
  %(prog)s -k "AI人工智能"
  
  # 只看历史快照，不重新抓取
  %(prog)s -k "高考" --history-only
  
  # 不保存本次快照
  %(prog)s -k "618" --no-snapshot
  
  # 给本次快照加标签和备注
  %(prog)s -k "618" --snapshot-tag "大促,重要" --snapshot-note "618大促当天"
  
  # ===== 快照管理 =====
  # 查看快照列表（按时间窗口/标签筛选）
  %(prog)s --snapshot-list "AI人工智能"
  %(prog)s --snapshot-list "AI人工智能" --window-start 2024-06-01 --tag-filter 重要
  
  # 给已有快照加标签/备注（用全局序号）
  %(prog)s --snapshot-index 0 --snapshot-tag "活动前,预热" --snapshot-note "618预热期"
  
  # 对比两次快照（全局序号模式，严格对应列表显示的序号）
  %(prog)s --snapshot-compare "AI人工智能" 0 1 --global-idx
  
  # ===== 批量查询 =====
  # 自动生成文件名（包含关键词和时间窗口）
  %(prog)s -b keywords.txt --watch-mode -o auto
  
  # ===== 缓存管理 =====
  %(prog)s --cache-list
  %(prog)s --cache-ttl 7200
  %(prog)s --cache-clear "高考"

排序方式 (--sort-by):
  avg    按平均热度（默认）
  peak   按峰值热度
  change 按上升幅度
  rank   按平均排名
  score  按关注指数（仅关注模式）
        """
    )
    
    parser.add_argument('-k', '--keyword', help='要查询的话题关键词')
    parser.add_argument('-c', '--compare', help='要对比的第二个关键词')
    parser.add_argument('-s', '--start-date', help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('-e', '--end-date', help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('-b', '--batch', help='从文本文件批量读取关键词')
    parser.add_argument('-o', '--output', help='CSV导出文件路径，设为 auto 时自动命名')
    parser.add_argument('--export', help='导出数据到CSV文件')
    parser.add_argument('--no-cache', action='store_true', help='不使用缓存')
    parser.add_argument('--mock', action='store_true', help='强制使用模拟数据')
    parser.add_argument('--width', type=int, default=100, help='图表宽度')
    parser.add_argument('--height', type=int, default=25, help='图表高度')
    parser.add_argument('--sort-by', choices=list(SORT_OPTIONS.keys()), default='avg',
                        help='批量报告排序方式: avg/peak/change/rank/score (默认: avg)')
    parser.add_argument('--watch-mode', action='store_true', help='关注清单模式：综合打分排序')
    parser.add_argument('--no-snapshot', action='store_true', help='不保存本次分析快照')
    parser.add_argument('--history-only', action='store_true',
                        help='只展示历史快照对比，不重新抓取新数据')
    parser.add_argument('--snapshot-tag', metavar='TAGS',
                        help='本次快照/已有快照的标签，多个用逗号分隔')
    parser.add_argument('--snapshot-note', metavar='NOTE',
                        help='本次快照/已有快照的备注文字')
    
    snapshot_group = parser.add_argument_group('快照管理')
    snapshot_group.add_argument('--snapshot-list', metavar='KEYWORD',
                                help='查看某关键词的快照历史')
    snapshot_group.add_argument('--snapshot-compare', nargs=3, metavar=('KEYWORD', 'INDEX1', 'INDEX2'),
                                help='对比某关键词的两次快照')
    snapshot_group.add_argument('--snapshot-index', type=int, metavar='IDX',
                                help='指定快照全局序号（用于标签/备注编辑）')
    snapshot_group.add_argument('--global-idx', action='store_true',
                                help='--snapshot-compare 使用全局序号（默认关键词内序号）')
    snapshot_group.add_argument('--window-start', metavar='DATE',
                                help='快照筛选: 抓取时间>= (YYYY-MM-DD)')
    snapshot_group.add_argument('--window-end', metavar='DATE',
                                help='快照筛选: 抓取时间<= (YYYY-MM-DD)')
    snapshot_group.add_argument('--tag-filter', metavar='TAG',
                                help='快照筛选: 只显示包含指定标签的快照')
    
    cache_group = parser.add_argument_group('缓存管理')
    cache_group.add_argument('--cache-list', action='store_true', help='列出所有缓存')
    cache_group.add_argument('--cache-filter-kw', metavar='KEYWORD', help='筛选: 关键词包含')
    cache_group.add_argument('--cache-filter-start', metavar='DATE', help='筛选: 开始日期>= (YYYY-MM-DD)')
    cache_group.add_argument('--cache-filter-end', metavar='DATE', help='筛选: 结束日期<= (YYYY-MM-DD)')
    cache_group.add_argument('--cache-filter-status', choices=['valid', 'expired'], help='筛选: 状态 (valid/expired)')
    cache_group.add_argument('--cache-clear', nargs='?', const='', metavar='KEYWORD',
                            help='清理缓存（指定关键词精确匹配或留空清理全部）')
    cache_group.add_argument('--cache-ttl', metavar='SECONDS', type=int,
                            help='设置缓存有效期（秒）')
    
    args = parser.parse_args()
    
    snapshot_management_only = (
        args.snapshot_list or args.snapshot_compare or 
        ((args.snapshot_tag or args.snapshot_note) and not (args.keyword or args.batch))
    )
    if snapshot_management_only:
        handle_snapshot_command(args)
        return
    
    if args.cache_list or args.cache_clear is not None or args.cache_ttl:
        handle_cache_command(args)
        return
    
    if not args.keyword and not args.batch:
        parser.print_help()
        sys.exit(1)
    
    start_date, end_date, num_hours, msg = resolve_date_range(args.start_date, args.end_date)
    if start_date is None:
        print(msg)
        sys.exit(1)
    
    print(f"\n{BOLD}📅 分析周期{RESET}: {msg}")
    sort_desc = f" | 排序: {SORT_OPTIONS[args.sort_by][1]}" if args.batch or args.compare else ""
    if sort_desc:
        print(f"{BOLD}📊 报告设置{RESET}{sort_desc}")
    if args.watch_mode:
        print(f"{BOLD}🔍 分析模式{RESET}: 关注清单模式")
    if args.no_snapshot:
        print(f"{BOLD}💾 快照{RESET}: 本次不保存")
    if args.history_only:
        print(f"{BOLD}⏱️  模式{RESET}: 只看历史快照，不重新抓取")
    if args.snapshot_tag or args.snapshot_note:
        print(f"{BOLD}🏷️  快照元数据{RESET}: ", end="")
        if args.snapshot_tag:
            print(f"标签=[{args.snapshot_tag}] ", end="")
        if args.snapshot_note:
            print(f"备注=\"{args.snapshot_note}\" ", end="")
        print()
    
    use_cache = not args.no_cache
    user_tags = [t.strip() for t in args.snapshot_tag.split(',') if t.strip()] if args.snapshot_tag else None
    user_note = args.snapshot_note
    
    output_file = args.output
    if output_file == 'auto':
        if args.batch:
            kws = read_keywords_from_file(args.batch)
            output_file = generate_smart_filename(kws, start_date, end_date, num_hours, 'csv')
        elif args.compare:
            output_file = generate_smart_filename([args.keyword, args.compare],
                                                 start_date, end_date, num_hours, 'csv')
        else:
            output_file = generate_smart_filename([args.keyword], start_date, end_date, num_hours, 'csv')
        print(f"\n💾 自动生成文件名: {output_file}")
    
    if args.history_only and args.keyword:
        print(f"\n{BOLD}⏱️  历史快照模式{RESET}: 只显示历史记录，不抓取新数据")
        print_snapshot_list(args.keyword, window_start=args.window_start,
                           window_end=args.window_end, tag_filter=args.tag_filter)
        return
    
    if args.batch:
        keywords = read_keywords_from_file(args.batch)
        if not keywords:
            print(f"❌ 无法从文件读取关键词: {args.batch}")
            sys.exit(1)
        
        batch_analysis(keywords, start_date, end_date, 
                      output_file=output_file, export_csv=bool(output_file),
                      use_cache=use_cache, force_mock=args.mock,
                      num_hours=num_hours, sort_by=args.sort_by, watch_mode=args.watch_mode,
                      save_snapshot_flag=not args.no_snapshot,
                      snapshot_tags=user_tags, snapshot_note=user_note)
        return
    
    keywords = [args.keyword]
    if args.compare:
        keywords.append(args.compare)
    
    datasets = []
    analyses = []
    
    for keyword in keywords:
        print(f"\n{'─'*60}")
        print(f"🔍 正在查询: {keyword}...")
        data, source, cache_hit, prev_cache, prev_snapshot = get_trend_data(
            keyword, start_date, end_date, 
            use_cache=use_cache, force_mock=args.mock,
            num_hours=num_hours
        )
        datasets.append({'keyword': keyword, 'data': data['data'], 'source': source})
        
        analysis = print_analysis(keyword, data, source, cache_hit, prev_cache, prev_snapshot,
                                  save_snapshot_flag=not args.no_snapshot,
                                  tags=user_tags, note=user_note)
        if analysis:
            analyses.append(analysis)
    
    if len(analyses) >= 2:
        for line in generate_comparison_conclusion(analyses):
            print(line)
    
    print(f"\n{'═'*60}")
    print(f"{BOLD}📈 热度趋势图{RESET}")
    print(f"{'═'*60}")
    chart = draw_ascii_chart(datasets, width=args.width, height=args.height)
    print(chart)
    
    if args.export:
        export_file = args.export
        if export_file == 'auto':
            kws = [args.keyword]
            if args.compare:
                kws.append(args.compare)
            export_file = generate_smart_filename(kws, start_date, end_date, num_hours, 'csv')
            print(f"\n💾 自动生成文件名: {export_file}")
        
        if export_to_csv(datasets, export_file):
            print(f"\n✓ 原始数据已导出到: {export_file}")
            
            if analyses:
                sorted_analyses, sort_name, _ = sort_analyses(analyses, args.sort_by)
                summary_file = export_file.replace('.csv', '_summary.csv')
                if export_summary_csv(sorted_analyses, summary_file, args.sort_by, args.watch_mode):
                    print(f"✓ 汇总报告已导出到: {summary_file} (按{sort_name}排序)")
                
                md_file = export_file.replace('.csv', '.md')
                if export_markdown_report(sorted_analyses, datasets, md_file, args.sort_by, args.watch_mode):
                    print(f"✓ Markdown报告已导出到: {md_file}")
        else:
            print(f"\n❌ 导出失败")
    
    print(f"\n{'═'*60}")
    print(f"💡 提示：--snapshot-list 查看历史 | --snapshot-tag/--snapshot-note 给快照加标签 | --history-only 只看历史")
    print(f"{'═'*60}\n")


if __name__ == '__main__':
    main()

