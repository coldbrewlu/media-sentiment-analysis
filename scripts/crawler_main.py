# gmw_crawler_fixed.py - Fixed version of GMW crawler

import requests
from bs4 import BeautifulSoup
import json
import time
import os
from urllib.parse import urljoin, urlparse
from datetime import datetime
import logging
import argparse

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GMWCrawler:
    def __init__(self, output_dir="data/raw/gmw", test_mode=False):
        self.base_url = "https://www.gmw.cn"
        self.output_dir = output_dir
        self.test_mode = test_mode
        self.max_articles = 10 if test_mode else 100
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        # Headers to mimic a real browser
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        # Article link selectors (multiple fallbacks)
        self.article_selectors = [
            'a[href*="/content/"]',
            'a[href*="/article/"]',
            'a[href*="/news/"]',
            'a[href*="/2024/"]',
            'a[href*="/2025/"]',
            '.news-item a',
            '.article-title a',
            'h3 a',
            'h2 a'
        ]
        
        # Content extraction selectors
        self.title_selectors = [
            'h1',
            '.article-title',
            '.news-title',
            '.title',
            'title'
        ]
        
        self.content_selectors = [
            '.article-content',
            '.news-content',
            '.content',
            '#content',
            '.main-content',
            '.article-body',
            '.news-body',
            'div[class*="content"]',
            'div[class*="article"]',
            'div[id*="content"]'
        ]
        
        self.date_selectors = [
            '.publish-time',
            '.date',
            '.time',
            '[class*="time"]',
            '.author-date'
        ]
        
        self.author_selectors = [
            '.author',
            '.byline',
            '[class*="author"]',
            '.writer'
        ]
        
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        
    def get_article_links(self, max_pages=3):
        """Get article links from GMW homepage and category pages"""
        logger.info("Getting article links from GMW...")
        
        article_links = set()
        
        # URLs to crawl
        urls_to_crawl = [
            self.base_url,  # Homepage
            f"{self.base_url}/node_1141.htm",  # News section
            f"{self.base_url}/node_1142.htm",  # Opinion section
            "https://tech.gmw.cn/",  # Tech section
            "https://guancha.gmw.cn/",  # Commentary section
        ]
        
        for url in urls_to_crawl:
            try:
                logger.info(f"Crawling: {url}")
                response = self.session.get(url, timeout=10)
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    
                    # Try each selector
                    for selector in self.article_selectors:
                        links = soup.select(selector)
                        for link in links:
                            href = link.get('href')
                            if href:
                                full_url = urljoin(url, href)
                                # Filter valid article URLs
                                if self.is_valid_article_url(full_url):
                                    article_links.add(full_url)
                    
                    logger.info(f"Found {len(article_links)} total unique links so far")
                    
                else:
                    logger.warning(f"Failed to access {url}: {response.status_code}")
                    
            except Exception as e:
                logger.error(f"Error crawling {url}: {e}")
            
            time.sleep(1)  # Be respectful
            
            if len(article_links) >= self.max_articles:
                break
        
        logger.info(f"Total article links found: {len(article_links)}")
        return list(article_links)[:self.max_articles]
    
    def is_valid_article_url(self, url):
        """Check if URL is a valid article URL"""
        parsed = urlparse(url)
        
        # Must be from GMW domain
        if 'gmw.cn' not in parsed.netloc:
            return False
            
        # Must contain content indicators
        content_indicators = [
            '/content/',
            '/article/',
            '/news/',
            '/2024/',
            '/2025/',
            '.htm',
            '.html'
        ]
        
        return any(indicator in url for indicator in content_indicators)
    
    def extract_article_content(self, url):
        """Extract content from a single article"""
        try:
            logger.info(f"Extracting content from: {url}")
            response = self.session.get(url, timeout=10)
            
            if response.status_code != 200:
                logger.warning(f"Failed to access article: {response.status_code}")
                return None
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract title
            title = None
            for selector in self.title_selectors:
                title_elem = soup.select_one(selector)
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    if title and len(title) > 5:
                        break
            
            # Extract content
            content = None
            for selector in self.content_selectors:
                content_elem = soup.select_one(selector)
                if content_elem:
                    # Remove script and style elements
                    for script in content_elem(["script", "style"]):
                        script.decompose()
                    content = content_elem.get_text(strip=True)
                    if content and len(content) > 100:
                        break
            
            # Extract date
            date = None
            for selector in self.date_selectors:
                date_elem = soup.select_one(selector)
                if date_elem:
                    date = date_elem.get_text(strip=True)
                    if date:
                        break
            
            # Extract author
            author = None
            for selector in self.author_selectors:
                author_elem = soup.select_one(selector)
                if author_elem:
                    author = author_elem.get_text(strip=True)
                    if author:
                        break
            
            if not title or not content:
                logger.warning(f"Failed to extract essential content from {url}")
                return None
            
            return {
                'url': url,
                'title': title,
                'content': content,
                'date': date,
                'author': author,
                'extracted_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error extracting content from {url}: {e}")
            return None
    
    def save_article(self, article_data):
        """Save article data to file"""
        try:
            # Create filename from URL
            parsed_url = urlparse(article_data['url'])
            filename = parsed_url.path.replace('/', '_').replace('.htm', '').replace('.html', '')
            if filename.startswith('_'):
                filename = filename[1:]
            if not filename:
                filename = f"article_{int(time.time())}"
            
            filename = f"{filename}.json"
            filepath = os.path.join(self.output_dir, filename)
            
            # Save to file
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(article_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved article to {filepath}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving article: {e}")
            return False
    
    def crawl(self):
        """Main crawling method"""
        logger.info("Starting GMW crawler...")
        
        if self.test_mode:
            logger.info("Running in TEST MODE - limited articles")
        
        # Get article links
        article_links = self.get_article_links()
        
        if not article_links:
            logger.error("No article links found! Check website access and selectors.")
            return
        
        logger.info(f"Found {len(article_links)} article links to process")
        
        # Process articles
        successful_count = 0
        failed_count = 0
        
        for i, url in enumerate(article_links, 1):
            logger.info(f"Processing article {i}/{len(article_links)}")
            
            # Extract content
            article_data = self.extract_article_content(url)
            
            if article_data:
                # Save article
                if self.save_article(article_data):
                    successful_count += 1
                else:
                    failed_count += 1
            else:
                failed_count += 1
            
            # Be respectful - delay between requests
            time.sleep(2)
            
            # In test mode, stop after first successful article
            if self.test_mode and successful_count >= 3:
                logger.info("Test mode: stopping after 3 successful articles")
                break
        
        logger.info(f"Crawling complete. Success: {successful_count}, Failed: {failed_count}")
        
        # Create summary file
        summary = {
            'crawl_date': datetime.now().isoformat(),
            'total_articles': len(article_links),
            'successful': successful_count,
            'failed': failed_count,
            'test_mode': self.test_mode
        }
        
        summary_file = os.path.join(self.output_dir, 'crawl_summary.json')
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Crawl summary saved to {summary_file}")

def main():
    parser = argparse.ArgumentParser(description='GMW Crawler')
    parser.add_argument('--test', action='store_true', help='Run in test mode')
    parser.add_argument('--output', default='../data/raw/gmw', help='Output directory')
    
    args = parser.parse_args()
    
    crawler = GMWCrawler(output_dir=args.output, test_mode=args.test)
    crawler.crawl()

if __name__ == "__main__":
    main()