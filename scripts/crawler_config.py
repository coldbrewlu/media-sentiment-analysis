#!/usr/bin/env python3
"""
Configuration and utility functions for Chinese media crawler
"""

import json
import csv
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import logging

# Configuration
CONFIG = {
    "output_dir": "data/raw",
    "start_year": 1978,
    "end_year": 2019,
    "keywords": [
        "私营企业", "民营企业", "私营经济", "民营经济", 
        "个体经济", "私有制", "非公有制", "私人企业",
        "民间资本", "私营工商业", "个体工商户", "私营部门",
        "市场经济", "经济改革", "对外开放", "私营投资",
        "民营资本", "私营股份", "个人所有制", "私营化"
    ],
    "request_delay": (1, 3),  # Random delay between requests (min, max)
    "max_articles_per_search": 50,
    "max_concurrent_requests": 3,
    "timeout": 30
}

# Media outlet configurations
MEDIA_CONFIG = {
    "gmw": {
        "name": "光明日报",
        "base_url": "https://www.gmw.cn",
        "archive_url": "https://epaper.gmw.cn/gmrb/html/",
        "search_url": "https://www.gmw.cn/search.htm",
        "selectors": {
            "title": ["h1", ".title", "#title", ".article-title"],
            "content": [".content", "#content", ".article-content", ".text", ".article-text"],
            "date": [".date", ".time", ".publish-time", ".pub-time"],
            "author": [".author", ".writer", ".journalist"]
        }
    },
    "people": {
        "name": "人民日报",
        "base_url": "http://paper.people.com.cn",
        "archive_url": "http://paper.people.com.cn/rmrb/html/",
        "search_url": "http://search.people.cn/",
        "selectors": {
            "title": ["h1", ".title", "#title", ".bt"],
            "content": [".content", "#content", ".article-content", ".text", ".main-content"],
            "date": [".date", ".time", ".publish-time", ".pub-time", ".ly"],
            "author": [".author", ".writer", ".journalist", ".zz"]
        }
    },
    "economic": {
        "name": "经济日报",
        "base_url": "http://www.ce.cn",
        "archive_url": "http://paper.ce.cn/jjrb/html/",
        "search_url": "http://search.ce.cn/",
        "selectors": {
            "title": ["h1", ".title", "#title"],
            "content": [".content", "#content", ".article-content", ".text"],
            "date": [".date", ".time", ".publish-time"],
            "author": [".author", ".writer"]
        }
    },
    "reference": {
        "name": "参考消息",
        "base_url": "http://www.cankaoxiaoxi.com",
        "archive_url": "http://www.cankaoxiaoxi.com/",
        "search_url": "http://search.cankaoxiaoxi.com/",
        "selectors": {
            "title": ["h1", ".title", "#title"],
            "content": [".content", "#content", ".article-content", ".text"],
            "date": [".date", ".time", ".publish-time"],
            "author": [".author", ".writer"]
        }
    }
}

class DataProcessor:
    """Process and clean crawled data"""
    
    def __init__(self, data_dir: str = "data/raw"):
        self.data_dir = Path(data_dir)
        self.cleaned_dir = Path("data/cleaned")
        self.cleaned_dir.mkdir(parents=True, exist_ok=True)
        
    def clean_text(self, text: str) -> str:
        """Clean and normalize text content"""
        if not text:
            return ""
            
        # Remove extra whitespace
        text = ' '.join(text.split())
        
        # Remove common newspaper formatting
        text = text.replace('【', '').replace('】', '')
        text = text.replace('（', '(').replace('）', ')')
        
        # Remove URLs
        import re
        text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
        
        return text.strip()
    
    def extract_date(self, date_str: str) -> Optional[str]:
        """Extract and normalize date from various formats"""
        if not date_str:
            return None
            
        import re
        
        # Common date patterns
        patterns = [
            r'(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})',  # YYYY年MM月DD or YYYY-MM-DD
            r'(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})',  # YYYY年MM月DD
            r'(\d{1,2})[月\-/](\d{1,2})[日\-/](\d{4})',  # MM月DD日YYYY
        ]
        
        for pattern in patterns:
            match = re.search(pattern, date_str)
            if match:
                groups = match.groups()
                if len(groups) == 3:
                    try:
                        year = int(groups[0]) if len(groups[0]) == 4 else int(groups[2])
                        month = int(groups[1]) if len(groups[0]) == 4 else int(groups[0])
                        day = int(groups[2]) if len(groups[0]) == 4 else int(groups[1])
                        return f"{year:04d}-{month:02d}-{day:02d}"
                    except ValueError:
                        continue
        
        return None
    
    def process_media_data(self, media_type: str):
        """Process all articles for a specific media type"""
        media_dir = self.data_dir / media_type
        if not media_dir.exists():
            logging.warning(f"Media directory {media_dir} does not exist")
            return
            
        articles = []
        
        # Process all JSON files
        for json_file in media_dir.glob("*.json"):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    article = json.load(f)
                    
                # Clean the article data
                cleaned_article = {
                    'id': article.get('id'),
                    'media': media_type,
                    'title': self.clean_text(article.get('title', '')),
                    'content': self.clean_text(article.get('content', '')),
                    'date': self.extract_date(article.get('date', '')),
                    'author': self.clean_text(article.get('author', '')),
                    'url': article.get('url', ''),
                    'crawl_time': article.get('crawl_time', '')
                }
                
                # Only include articles with substantial content
                if (len(cleaned_article['content']) > 100 and 
                    cleaned_article['title'] and 
                    cleaned_article['date']):
                    articles.append(cleaned_article)
                    
            except Exception as e:
                logging.error(f"Error processing {json_file}: {e}")
                continue
        
        # Save cleaned data
        if articles:
            # Save as JSON
            output_file = self.cleaned_dir / f"{media_type}_cleaned.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(articles, f, ensure_ascii=False, indent=2)
            
            # Save as CSV
            csv_file = self.cleaned_dir / f"{media_type}_cleaned.csv"
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=articles[0].keys())
                writer.writeheader()
                writer.writerows(articles)
            
            logging.info(f"Processed {len(articles)} articles for {media_type}")
        
        return articles
    
    def create_master_dataset(self):
        """Combine all cleaned data into a master dataset"""
        all_articles = []
        
        for media_type in ['gmw', 'people', 'economic', 'reference']:
            cleaned_file = self.cleaned_dir / f"{media_type}_cleaned.json"
            if cleaned_file.exists():
                with open(cleaned_file, 'r', encoding='utf-8') as f:
                    articles = json.load(f)
                    all_articles.extend(articles)
        
        if all_articles:
            # Sort by date
            all_articles.sort(key=lambda x: x.get('date', ''))
            
            # Save master dataset
            master_file = self.cleaned_dir / "master_dataset.json"
            with open(master_file, 'w', encoding='utf-8') as f:
                json.dump(all_articles, f, ensure_ascii=False, indent=2)
            
            # Save as CSV
            csv_file = self.cleaned_dir / "master_dataset.csv"
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=all_articles[0].keys())
                writer.writeheader()
                writer.writerows(all_articles)
            
            logging.info(f"Created master dataset with {len(all_articles)} articles")
            
            # Create summary statistics
            self.create_summary_stats(all_articles)
        
        return all_articles
    
    def create_summary_stats(self, articles: List[Dict]):
        """Create summary statistics for the dataset"""
        stats = {
            'total_articles': len(articles),
            'media_breakdown': {},
            'year_breakdown': {},
            'keyword_frequency': {},
            'date_range': {
                'start': min(article['date'] for article in articles if article['date']),
                'end': max(article['date'] for article in articles if article['date'])
            }
        }
        
        # Media breakdown
        for article in articles:
            media = article['media']
            stats['media_breakdown'][media] = stats['media_breakdown'].get(media, 0) + 1
        
        # Year breakdown
        for article in articles:
            if article['date']:
                year = article['date'][:4]
                stats['year_breakdown'][year] = stats['year_breakdown'].get(year, 0) + 1
        
        # Keyword frequency
        for keyword in CONFIG['keywords']:
            count = sum(1 for article in articles 
                       if keyword in article['content'] or keyword in article['title'])
            if count > 0:
                stats['keyword_frequency'][keyword] = count
        
        # Save statistics
        stats_file = self.cleaned_dir / "dataset_stats.json"
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        
        logging.info(f"Created summary statistics: {stats}")
        return stats

def main():
    """Main function to process crawled data"""
    processor = DataProcessor()
    
    # Process each media type
    for media_type in ['gmw', 'people', 'economic', 'reference']:
        processor.process_media_data(media_type)
    
    # Create master dataset
    processor.create_master_dataset()
    
    print("Data processing completed!")

if __name__ == "__main__":
    main()