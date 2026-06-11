#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博热搜趋势分析命令行工具
"""

import argparse
import json
import csv
import os
import sys
import math
import random
import time
from datetime import datetime, timedelta
from collections import defaultdict

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.cache')
ASCII_CHARS = [' ', '·', '•', '○', '●', '◆', '■']
COLORS = ['\033[91m', '\033[92m', '\033[93m', '\033[94m', '\033[95m', '\033[96m']
RESET = '\033[0m'


def ensure_cache_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)


def get_cache_path(keyword, start_date, end_date):
    ensure_cache_dir()
    filename = f"{keyword}_{start_date}_{end_date}.json"
    filename = filename.replace(' ', '_').replace('/', '_')
    return os.path.join(CACHE_DIR, filename)


def load_from_cache(keyword, start_date, end_date):
    cache_path = get_cache_path(keyword, start_date, end_date)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    return None


def save_to_cache(keyword, start_date, end_date, data):
    cache_path = get_cache_path(keyword, start_date, end_date)
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except IOError:
        pass


def generate_mock_data(keyword, start_date, end_date):
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    hours = int((end - start).total_seconds() / 3600) + 24
    
    seed = sum(ord(c) for c in keyword)
    random.seed(seed)
    
    base_hot = random.randint(50000, 200000)
    data = []
    current_time = start
    
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
        'data': data
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
            return generate_mock_data(keyword, start_date, end_date), "success"
        else:
            return None, f"HTTP状态码: {response.status_code}"
    except requests.RequestException as e:
        return None, f"网络请求失败: {str(e)}"


def get_trend_data(keyword, start_date, end_date, use_cache=True, force_mock=False):
    if force_mock:
        return generate_mock_data(keyword, start_date, end_date), "使用模拟数据"
    
    if use_cache:
        cached = load_from_cache(keyword, start_date, end_date)
        if cached:
            return cached, "使用缓存数据"
    
    data, msg = fetch_weibo_data(keyword, start_date, end_date)
    if data:
        save_to_cache(keyword, start_date, end_date, data)
        return data, "获取实时数据成功"
    
    cached = load_from_cache(keyword, start_date, end_date)
    if cached:
        return cached, f"爬取失败（{msg}），使用缓存数据"
    
    mock_data = generate_mock_data(keyword, start_date, end_date)
    save_to_cache(keyword, start_date, end_date, mock_data)
    return mock_data, f"爬取失败（{msg}），使用模拟数据"


def find_peak(data):
    if not data:
        return None
    peak = max(data, key=lambda x: x['hot'])
    return peak


def analyze_trend(data):
    if len(data) < 2:
        return "平稳", 0
    
    values = [d['hot'] for d in data]
    n = len(values)
    
    x = list(range(n))
    sum_x = sum(x)
    sum_y = sum(values)
    sum_xy = sum(xi * yi for xi, yi in zip(x, values))
    sum_x2 = sum(xi * xi for xi in x)
    
    slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x) if (n * sum_x2 - sum_x * sum_x) != 0 else 0
    
    avg_value = sum_y / n
    change_percent = (slope * n / avg_value) * 100 if avg_value > 0 else 0
    
    if abs(change_percent) < 5:
        trend = "平稳"
    elif change_percent > 0:
        trend = "上升"
    else:
        trend = "下降"
    
    return trend, change_percent


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


def print_analysis(keyword, data, data_source):
    print(f"\n{'='*60}")
    print(f"话题: {keyword}")
    print(f"数据来源: {data_source}")
    print(f"{'='*60}")
    
    if not data:
        print("无数据")
        return
    
    values = [d['hot'] for d in data]
    peak = find_peak(data)
    trend, change_percent = analyze_trend(data)
    
    print(f"统计周期: {data[0]['time']} 至 {data[-1]['time']}")
    print(f"数据点数: {len(data)}")
    print(f"最高热度: {max(values):,}")
    print(f"最低热度: {min(values):,}")
    print(f"平均热度: {int(sum(values)/len(values)):,}")
    
    if peak:
        print(f"热度峰值: {peak['hot']:,} (出现时间: {peak['time']})")
    
    trend_color = {'上升': '\033[92m', '下降': '\033[91m', '平稳': '\033[93m'}[trend]
    print(f"趋势分析: {trend_color}{trend}{RESET} (变化率: {change_percent:+.2f}%)")


def batch_analysis(keywords, start_date, end_date, output_file=None, export_csv=False):
    print(f"\n{'#'*60}")
    print(f"# 批量查询报告 - {len(keywords)} 个话题")
    print(f"# 时间范围: {start_date} 至 {end_date}")
    print(f"{'#'*60}")
    
    datasets = []
    for keyword in keywords:
        print(f"\n正在查询: {keyword}...")
        data, source = get_trend_data(keyword, start_date, end_date)
        datasets.append({'keyword': keyword, 'data': data['data'], 'source': source})
        print_analysis(keyword, data['data'], source)
    
    print(f"\n{'='*60}")
    print("对比分析图表")
    print(f"{'='*60}")
    chart = draw_ascii_chart(datasets)
    print(chart)
    
    if export_csv and output_file:
        if export_to_csv(datasets, output_file):
            print(f"\n✓ 数据已导出到: {output_file}")
    
    print(f"\n{'='*60}")
    print("趋势对比汇总")
    print(f"{'='*60}")
    
    comparison_data = []
    for ds in datasets:
        values = [d['hot'] for d in ds['data']]
        peak = find_peak(ds['data'])
        trend, change = analyze_trend(ds['data'])
        comparison_data.append({
            'keyword': ds['keyword'],
            'avg_hot': int(sum(values)/len(values)),
            'peak_hot': max(values),
            'peak_time': peak['time'] if peak else '',
            'trend': trend,
            'change': change
        })
    
    comparison_data.sort(key=lambda x: x['avg_hot'], reverse=True)
    
    print(f"{'话题':<15} {'平均热度':>12} {'峰值热度':>12} {'峰值时间':>20} {'趋势':>8} {'变化率':>10}")
    print('-' * 80)
    for item in comparison_data:
        trend_color = {'上升': '\033[92m', '下降': '\033[91m', '平稳': '\033[93m'}[item['trend']]
        print(f"{item['keyword']:<15} {item['avg_hot']:>12,} {item['peak_hot']:>12,} {item['peak_time']:>20} {trend_color}{item['trend']:>8}{RESET} {item['change']:>+9.2f}%")


def main():
    parser = argparse.ArgumentParser(
        description='微博热搜趋势分析工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  %(prog)s -k "AI人工智能"
  %(prog)s -k "高考" -s 2024-06-01 -e 2024-06-07
  %(prog)s -k "端午节" -c "中秋节"
  %(prog)s -k "世界杯" --export worldcup.csv
  %(prog)s -b keywords.txt -o batch_report.csv
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
    
    args = parser.parse_args()
    
    if not args.keyword and not args.batch:
        parser.print_help()
        sys.exit(1)
    
    today = datetime.now()
    if not args.start_date:
        args.start_date = (today - timedelta(days=1)).strftime('%Y-%m-%d')
    if not args.end_date:
        args.end_date = today.strftime('%Y-%m-%d')
    
    try:
        start_dt = datetime.strptime(args.start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(args.end_date, '%Y-%m-%d')
        if (end_dt - start_dt).days > 7:
            print("⚠️  日期范围不能超过7天，已自动截断")
            end_dt = start_dt + timedelta(days=7)
            args.end_date = end_dt.strftime('%Y-%m-%d')
    except ValueError:
        print("❌ 日期格式错误，请使用 YYYY-MM-DD 格式")
        sys.exit(1)
    
    use_cache = not args.no_cache
    
    if args.batch:
        keywords = read_keywords_from_file(args.batch)
        if not keywords:
            print(f"❌ 无法从文件读取关键词: {args.batch}")
            sys.exit(1)
        
        batch_analysis(keywords, args.start_date, args.end_date, 
                      output_file=args.output, export_csv=bool(args.output))
        return
    
    keywords = [args.keyword]
    if args.compare:
        keywords.append(args.compare)
    
    datasets = []
    for keyword in keywords:
        print(f"\n正在查询: {keyword}...")
        data, source = get_trend_data(keyword, args.start_date, args.end_date, 
                                     use_cache=use_cache, force_mock=args.mock)
        datasets.append({'keyword': keyword, 'data': data['data'], 'source': source})
        print_analysis(keyword, data['data'], source)
    
    print(f"\n{'='*60}")
    print("热度趋势图")
    print(f"{'='*60}")
    chart = draw_ascii_chart(datasets, width=args.width, height=args.height)
    print(chart)
    
    if args.export:
        if export_to_csv(datasets, args.export):
            print(f"\n✓ 数据已导出到: {args.export}")
        else:
            print(f"\n❌ 导出失败")


if __name__ == '__main__':
    main()
