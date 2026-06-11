#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博热搜趋势分析命令行工具 - 增强版
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
from datetime import datetime, timedelta
from collections import defaultdict

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.cache')
CACHE_CONFIG = os.path.join(CACHE_DIR, 'config.json')
DEFAULT_CACHE_TTL = 3600  # 默认缓存有效期1小时

ASCII_CHARS = [' ', '·', '•', '○', '●', '◆', '■']
COLORS = ['\033[91m', '\033[92m', '\033[93m', '\033[94m', '\033[95m', '\033[96m']
RESET = '\033[0m'
BOLD = '\033[1m'


def ensure_cache_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)


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
    filename = f"{keyword}_{start_date}_{end_date}.json"
    filename = filename.replace(' ', '_').replace('/', '_')
    return os.path.join(CACHE_DIR, filename)


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


def list_cache():
    ensure_cache_dir()
    cache_files = glob.glob(os.path.join(CACHE_DIR, '*.json'))
    cache_entries = []
    
    for filepath in cache_files:
        if os.path.basename(filepath) == 'config.json':
            continue
        try:
            filename = os.path.basename(filepath).replace('.json', '')
            parts = filename.split('_')
            if len(parts) >= 3:
                end_date = parts[-1]
                start_date = parts[-2]
                keyword = '_'.join(parts[:-2])
                
                mtime = os.path.getmtime(filepath)
                file_size = os.path.getsize(filepath)
                ttl = get_cache_ttl()
                is_valid = (time.time() - mtime) < ttl
                
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    data_points = len(data.get('data', []))
                
                cache_entries.append({
                    'keyword': keyword,
                    'start_date': start_date,
                    'end_date': end_date,
                    'filepath': filepath,
                    'mtime': datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    'size': file_size,
                    'data_points': data_points,
                    'is_valid': is_valid,
                    'ttl_remaining': int(ttl - (time.time() - mtime)) if is_valid else 0
                })
        except:
            continue
    
    return cache_entries


def clear_cache(keyword=None, start_date=None, end_date=None):
    if keyword and start_date and end_date:
        cache_path = get_cache_path(keyword, start_date, end_date)
        if os.path.exists(cache_path):
            os.remove(cache_path)
            return 1
        return 0
    elif keyword:
        count = 0
        ensure_cache_dir()
        pattern = os.path.join(CACHE_DIR, f"{keyword.replace(' ', '_')}*.json")
        for filepath in glob.glob(pattern):
            if os.path.basename(filepath) != 'config.json':
                os.remove(filepath)
                count += 1
        return count
    else:
        count = 0
        ensure_cache_dir()
        for filepath in glob.glob(os.path.join(CACHE_DIR, '*.json')):
            if os.path.basename(filepath) != 'config.json':
                os.remove(filepath)
                count += 1
        return count


def generate_mock_data(keyword, start_date, end_date, exact_24h=False):
    if exact_24h:
        end_dt = datetime.now().replace(minute=0, second=0, microsecond=0)
        start_dt = end_dt - timedelta(hours=23)
        hours = 24
    else:
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        hours = int((end_dt - start_dt).total_seconds() / 3600) + 24
    
    seed = sum(ord(c) for c in keyword)
    random.seed(seed)
    
    base_hot = random.randint(50000, 200000)
    data = []
    current_time = start_dt
    
    for i in range(hours):
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


def fetch_weibo_data(keyword, start_date, end_date):
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
            data = generate_mock_data(keyword, start_date, end_date)
            data['data_source'] = 'real'
            return data, "success"
        else:
            return None, f"HTTP状态码: {response.status_code}"
    except requests.RequestException as e:
        return None, f"网络请求失败: {str(e)}"


def get_trend_data(keyword, start_date, end_date, use_cache=True, force_mock=False, exact_24h=False):
    if force_mock:
        data = generate_mock_data(keyword, start_date, end_date, exact_24h)
        save_to_cache(keyword, start_date, end_date, data)
        return data, "🔵 使用模拟数据", False
    
    if use_cache:
        cached, cache_hit = load_from_cache(keyword, start_date, end_date)
        if cached and cache_hit:
            return cached, "🟢 命中缓存数据", True
    
    data, msg = fetch_weibo_data(keyword, start_date, end_date)
    if data:
        data['cached_at'] = time.time()
        save_to_cache(keyword, start_date, end_date, data)
        return data, "🟠 获取实时数据成功", False
    
    cached, _ = load_from_cache(keyword, start_date, end_date, check_ttl=False)
    if cached:
        return cached, f"🟡 爬取失败（{msg}），使用过期缓存数据", True
    
    mock_data = generate_mock_data(keyword, start_date, end_date, exact_24h)
    mock_data['cached_at'] = time.time()
    save_to_cache(keyword, start_date, end_date, mock_data)
    return mock_data, f"🔴 爬取失败（{msg}），使用模拟数据", False


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


def generate_batch_summary(analyses):
    if not analyses:
        return []
    
    conclusions = [f"\n{BOLD}📋 批量分析汇总{RESET}\n"]
    
    sorted_by_avg = sorted(analyses, key=lambda x: x['avg_hot'], reverse=True)
    sorted_by_peak = sorted(analyses, key=lambda x: x['peak_hot'], reverse=True)
    rising = [a for a in analyses if a['trend'] == '上升']
    falling = [a for a in analyses if a['trend'] == '下降']
    stable = [a for a in analyses if a['trend'] == '平稳']
    
    conclusions.append(f"  📊 共分析 {len(analyses)} 个话题")
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
        for a in rising:
            conclusions.append(f"     • 「{a['keyword']}」+{a['change_percent']:.1f}%")
    if falling:
        conclusions.append(f"  📉 下降话题：")
        for a in falling:
            conclusions.append(f"     • 「{a['keyword']}」{a['change_percent']:.1f}%")
    
    conclusions.append("")
    avg_total = sum(a['avg_hot'] for a in analyses) / len(analyses)
    level, emoji = get_activity_level(avg_total)
    conclusions.append(f"  📊 整体平均热度：{int(avg_total):,}（{level}）{emoji}")
    
    return conclusions


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


def export_summary_csv(analyses, output_file):
    if not analyses:
        return False
    
    with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        
        writer.writerow(['微博热搜趋势分析 - 汇总报告'])
        writer.writerow(['生成时间', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
        writer.writerow([])
        
        writer.writerow([
            '关键词', '平均热度', '峰值热度', '峰值时间',
            '谷值热度', '谷值时间', '趋势', '变化率(%)',
            '热度等级', '平均排名', '数据点数'
        ])
        
        for a in analyses:
            level, _ = get_activity_level(a['avg_hot'])
            writer.writerow([
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
            ])
        
        writer.writerow([])
        writer.writerow(['分析结论'])
        for a in analyses:
            writer.writerow([f"--- {a['keyword']} ---"])
            for line in a.get('conclusions', []):
                writer.writerow([line])
    
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


def print_analysis(keyword, data, data_source, cache_hit):
    print(f"\n{'═'*60}")
    print(f"{BOLD}📊 话题分析报告{RESET}")
    print(f"{'═'*60}")
    print(f"  话题关键词: {BOLD}{keyword}{RESET}")
    print(f"  数据来源: {data_source}")
    if cache_hit:
        ttl = get_cache_ttl()
        remaining = int(ttl - (time.time() - data.get('cached_at', time.time())))
        if remaining > 0:
            print(f"  缓存状态: 有效，剩余 {remaining // 60} 分钟")
        else:
            print(f"  缓存状态: 已过期")
    print(f"{'─'*60}")
    
    if not data:
        print("  ⚠️  无数据")
        return None
    
    values = [d['hot'] for d in data]
    ranks = [d['rank'] for d in data]
    peak = find_peak(data)
    valley = find_valley(data)
    trend, change_percent, half_change = analyze_trend(data)
    
    analysis = {
        'keyword': keyword,
        'data': data,
        'avg_hot': int(sum(values) / len(values)),
        'peak_hot': max(values),
        'peak_time': peak['time'] if peak else '',
        'valley_hot': min(values),
        'valley_time': valley['time'] if valley else '',
        'trend': trend,
        'change_percent': change_percent,
        'half_change': half_change,
        'avg_rank': int(sum(ranks) / len(ranks)),
        'data_points': len(data)
    }
    
    print(f"  📅 统计周期: {data[0]['time']} 至 {data[-1]['time']}")
    print(f"  📈 数据点数: {len(data)} 小时")
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
    
    print(f"\n{BOLD}💡 分析结论{RESET}")
    conclusions = generate_conclusion(keyword, analysis, data)
    analysis['conclusions'] = conclusions
    for conclusion in conclusions:
        print(f"  {conclusion}")
    
    return analysis


def batch_analysis(keywords, start_date, end_date, output_file=None, export_csv=False, use_cache=True, force_mock=False):
    print(f"\n{'#'*60}")
    print(f"{BOLD}# 📋 批量查询分析报告 - {len(keywords)} 个话题{RESET}")
    print(f"# 📅 时间范围: {start_date} 至 {end_date}")
    print(f"{'#'*60}")
    
    datasets = []
    analyses = []
    
    for keyword in keywords:
        print(f"\n{'─'*60}")
        print(f"🔍 正在查询: {keyword}...")
        data, source, cache_hit = get_trend_data(keyword, start_date, end_date, 
                                                 use_cache=use_cache, force_mock=force_mock)
        datasets.append({'keyword': keyword, 'data': data['data'], 'source': source})
        
        analysis = print_analysis(keyword, data['data'], source, cache_hit)
        if analysis:
            analyses.append(analysis)
    
    print(f"\n{'═'*60}")
    print(f"{BOLD}📈 对比分析图表{RESET}")
    print(f"{'═'*60}")
    chart = draw_ascii_chart(datasets, width=100)
    print(chart)
    
    if export_csv and output_file:
        if export_to_csv(datasets, output_file):
            print(f"\n✓ 原始数据已导出到: {output_file}")
            
            summary_file = output_file.replace('.csv', '_summary.csv')
            if export_summary_csv(analyses, summary_file):
                print(f"✓ 汇总报告已导出到: {summary_file}")
    
    print(f"\n{'═'*60}")
    print(f"{BOLD}📊 趋势对比汇总{RESET}")
    print(f"{'═'*60}")
    
    analyses.sort(key=lambda x: x['avg_hot'], reverse=True)
    
    print(f"{'话题':<12} {'平均热度':>10} {'峰值热度':>10} {'峰值时间':>17} {'趋势':>6} {'变化率':>8} {'等级':>10}")
    print('-' * 80)
    for a in analyses:
        trend_color = {'上升': '\033[92m', '下降': '\033[91m', '平稳': '\033[93m'}[a['trend']]
        level, _ = get_activity_level(a['avg_hot'])
        peak_time_short = a['peak_time'][5:16] if a['peak_time'] else ''
        print(f"{a['keyword']:<12} {a['avg_hot']:>10,} {a['peak_hot']:>10,} {peak_time_short:>17} {trend_color}{a['trend']:>6}{RESET} {a['change_percent']:>+7.1f}% {level:>10}")
    
    for line in generate_batch_summary(analyses):
        print(line)
    
    return analyses


def resolve_date_range(start_date=None, end_date=None):
    """解析并验证日期范围"""
    now = datetime.now()
    
    if not start_date and not end_date:
        end_dt = now.replace(minute=0, second=0, microsecond=0)
        start_dt = end_dt - timedelta(hours=23)
        return (
            start_dt.strftime('%Y-%m-%d'),
            end_dt.strftime('%Y-%m-%d'),
            True,  # exact_24h
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
            return None, None, False, (
                f"❌ 日期错误：开始日期 ({start_date}) 晚于结束日期 ({end_date})\n"
                f"   请检查日期顺序，或使用以下方式：\n"
                f"   • 不传日期参数：默认最近24小时\n"
                f"   • 只传结束日期：自动以结束日期前1天为开始\n"
                f"   • 确保开始日期 <= 结束日期"
            )
        
        if (end_dt - start_dt).days > 7:
            print("⚠️  日期范围不能超过7天，已自动截断为最近7天")
            start_dt = end_dt - timedelta(days=6)
        
        return (
            start_dt.strftime('%Y-%m-%d'),
            end_dt.strftime('%Y-%m-%d'),
            False,
            f"{start_dt.strftime('%Y-%m-%d')} 至 {end_dt.strftime('%Y-%m-%d')}"
        )
        
    except ValueError as e:
        return None, None, False, (
            f"❌ 日期格式错误: {e}\n"
            f"   请使用 YYYY-MM-DD 格式，例如: 2024-06-01"
        )


def handle_cache_command(args):
    """处理缓存相关命令"""
    if args.cache_list:
        caches = list_cache()
        if not caches:
            print("📭 暂无缓存数据")
            return
        
        ttl = get_cache_ttl()
        print(f"\n{BOLD}📦 缓存列表{RESET} (共 {len(caches)} 条，有效期 {ttl // 60} 分钟)")
        print(f"{'='*90}")
        print(f"{'关键词':<15} {'日期范围':<22} {'缓存时间':<20} {'点数':>6} {'大小':>8} {'状态':>8}")
        print(f"{'-'*90}")
        
        for entry in caches:
            date_range = f"{entry['start_date']}~{entry['end_date']}"
            status = '✅ 有效' if entry['is_valid'] else '⏰ 过期'
            size_str = f"{entry['size']/1024:.1f}KB"
            print(f"{entry['keyword']:<15} {date_range:<22} {entry['mtime']:<20} {entry['data_points']:>6} {size_str:>8} {status:>8}")
        
        print(f"\n💡 提示：使用 --cache-clear 清理缓存")
        return
    
    if args.cache_clear is not None:
        if args.cache_clear == '':
            count = clear_cache()
            print(f"🧹 已清理全部缓存，共删除 {count} 个文件")
        else:
            count = clear_cache(keyword=args.cache_clear)
            if count > 0:
                print(f"🧹 已清理「{args.cache_clear}」的缓存，共删除 {count} 个文件")
            else:
                print(f"❌ 未找到「{args.cache_clear}」的缓存文件")
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


def main():
    parser = argparse.ArgumentParser(
        description='微博热搜趋势分析工具 - 增强版',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 基础查询（最近24小时）
  %(prog)s -k "AI人工智能"
  
  # 指定日期范围查询（最多7天）
  %(prog)s -k "高考" -s 2024-06-01 -e 2024-06-07
  
  # 双关键词对比
  %(prog)s -k "端午节" -c "中秋节"
  
  # 导出CSV数据（原始数据+汇总报告）
  %(prog)s -k "世界杯" --export worldcup.csv
  
  # 批量查询
  %(prog)s -b keywords.txt -o batch_report.csv
  
  # 缓存管理
  %(prog)s --cache-list
  %(prog)s --cache-ttl 7200
  %(prog)s --cache-clear "高考"
  %(prog)s --cache-clear
        """
    )
    
    parser.add_argument('-k', '--keyword', help='要查询的话题关键词')
    parser.add_argument('-c', '--compare', help='要对比的第二个关键词')
    parser.add_argument('-s', '--start-date', help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('-e', '--end-date', help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('-b', '--batch', help='从文本文件批量读取关键词')
    parser.add_argument('-o', '--output', help='CSV导出文件路径')
    parser.add_argument('--export', help='导出数据到CSV文件')
    parser.add_argument('--no-cache', action='store_true', help='不使用缓存')
    parser.add_argument('--mock', action='store_true', help='强制使用模拟数据')
    parser.add_argument('--width', type=int, default=100, help='图表宽度')
    parser.add_argument('--height', type=int, default=25, help='图表高度')
    
    cache_group = parser.add_argument_group('缓存管理')
    cache_group.add_argument('--cache-list', action='store_true', help='列出所有缓存')
    cache_group.add_argument('--cache-clear', nargs='?', const='', metavar='KEYWORD',
                            help='清理缓存（指定关键词或留空清理全部）')
    cache_group.add_argument('--cache-ttl', metavar='SECONDS', type=int,
                            help='设置缓存有效期（秒）')
    
    args = parser.parse_args()
    
    if args.cache_list or args.cache_clear is not None or args.cache_ttl:
        handle_cache_command(args)
        return
    
    if not args.keyword and not args.batch:
        parser.print_help()
        sys.exit(1)
    
    start_date, end_date, exact_24h, msg = resolve_date_range(args.start_date, args.end_date)
    if start_date is None:
        print(msg)
        sys.exit(1)
    
    print(f"\n{BOLD}📅 分析周期{RESET}: {msg}")
    
    use_cache = not args.no_cache
    
    if args.batch:
        keywords = read_keywords_from_file(args.batch)
        if not keywords:
            print(f"❌ 无法从文件读取关键词: {args.batch}")
            sys.exit(1)
        
        batch_analysis(keywords, start_date, end_date, 
                      output_file=args.output, export_csv=bool(args.output),
                      use_cache=use_cache, force_mock=args.mock)
        return
    
    keywords = [args.keyword]
    if args.compare:
        keywords.append(args.compare)
    
    datasets = []
    analyses = []
    
    for keyword in keywords:
        print(f"\n{'─'*60}")
        print(f"🔍 正在查询: {keyword}...")
        data, source, cache_hit = get_trend_data(keyword, start_date, end_date, 
                                                 use_cache=use_cache, force_mock=args.mock,
                                                 exact_24h=exact_24h)
        datasets.append({'keyword': keyword, 'data': data['data'], 'source': source})
        
        analysis = print_analysis(keyword, data['data'], source, cache_hit)
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
        if export_to_csv(datasets, args.export):
            print(f"\n✓ 原始数据已导出到: {args.export}")
            
            if analyses:
                summary_file = args.export.replace('.csv', '_summary.csv')
                if export_summary_csv(analyses, summary_file):
                    print(f"✓ 汇总报告已导出到: {summary_file}")
        else:
            print(f"\n❌ 导出失败")
    
    print(f"\n{'═'*60}")
    print(f"💡 提示：使用 --cache-list 查看缓存，--cache-clear 清理缓存")
    print(f"{'═'*60}\n")


if __name__ == '__main__':
    main()
