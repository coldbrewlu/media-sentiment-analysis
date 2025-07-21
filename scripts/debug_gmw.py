# debug_gmw.py - Debug script to test GMW crawling

import requests
from bs4 import BeautifulSoup
import time
import json
from urllib.parse import urljoin, urlparse
import os

def test_gmw_access():
    """Test basic access to GMW website"""
    print("=== Testing GMW Website Access ===")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    base_url = "https://www.gmw.cn"
    
    try:
        print(f"Accessing: {base_url}")
        response = requests.get(base_url, headers=headers, timeout=10)
        print(f"Status Code: {response.status_code}")
        print(f"Content Length: {len(response.content)}")
        print(f"Content-Type: {response.headers.get('Content-Type', 'N/A')}")
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            print(f"Page Title: {soup.title.string if soup.title else 'No title'}")
            
            # Look for article links
            article_links = []
            
            # Common selectors for news articles
            selectors = [
                'a[href*="/content/"]',  # Content pages
                'a[href*="/article/"]',  # Article pages  
                'a[href*="/news/"]',     # News pages
                'a[href*="/2024/"]',     # Date-based URLs
                'a[href*="/2025/"]',     # Date-based URLs
                '.news-item a',          # Common news item selector
                '.article-title a',      # Article title links
                'h3 a',                  # Header links
                'h2 a'                   # Header links
            ]
            
            for selector in selectors:
                links = soup.select(selector)
                if links:
                    print(f"\nFound {len(links)} links with selector: {selector}")
                    for i, link in enumerate(links[:5]):  # Show first 5
                        href = link.get('href')
                        if href:
                            full_url = urljoin(base_url, href)
                            title = link.get_text(strip=True)
                            print(f"  {i+1}. {title[:50]}... -> {full_url}")
                            article_links.append(full_url)
                    
                    if len(links) > 5:
                        print(f"  ... and {len(links) - 5} more")
            
            return article_links[:10]  # Return first 10 for testing
            
        else:
            print(f"Failed to access website. Status: {response.status_code}")
            return []
            
    except Exception as e:
        print(f"Error accessing website: {e}")
        return []

def test_article_scraping(article_urls):
    """Test scraping individual articles"""
    print("\n=== Testing Article Scraping ===")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    successful_articles = []
    
    for i, url in enumerate(article_urls[:3]):  # Test first 3 articles
        print(f"\nTesting article {i+1}: {url}")
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Try different selectors for article content
                content_selectors = [
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
                
                title_selectors = [
                    'h1',
                    '.article-title',
                    '.news-title',
                    '.title',
                    'title'
                ]
                
                # Extract title
                title = None
                for selector in title_selectors:
                    title_elem = soup.select_one(selector)
                    if title_elem:
                        title = title_elem.get_text(strip=True)
                        if title and len(title) > 10:  # Valid title
                            break
                
                # Extract content
                content = None
                for selector in content_selectors:
                    content_elem = soup.select_one(selector)
                    if content_elem:
                        content = content_elem.get_text(strip=True)
                        if content and len(content) > 100:  # Valid content
                            break
                
                print(f"Title: {title[:50] if title else 'Not found'}...")
                print(f"Content length: {len(content) if content else 0}")
                
                if title and content:
                    successful_articles.append({
                        'url': url,
                        'title': title,
                        'content': content[:200] + '...' if len(content) > 200 else content
                    })
                    print("✓ Successfully extracted content")
                else:
                    print("✗ Failed to extract content")
                    
            else:
                print(f"✗ Failed to access article. Status: {response.status_code}")
                
        except Exception as e:
            print(f"✗ Error scraping article: {e}")
        
        time.sleep(1)  # Be respectful
    
    return successful_articles

def generate_gmw_config(successful_articles):
    """Generate GMW configuration based on successful scraping"""
    print("\n=== Generating GMW Configuration ===")
    
    if not successful_articles:
        print("No successful articles found. Cannot generate configuration.")
        return None
    
    # Analyze successful articles to determine patterns
    sample_url = successful_articles[0]['url']
    
    config = {
        "gmw": {
            "base_url": "https://www.gmw.cn",
            "name": "光明网",
            "description": "GMW (Guangming Daily) - Chinese News Portal",
            "selectors": {
                "article_links": [
                    "a[href*='/content/']",
                    "a[href*='/article/']", 
                    "a[href*='/news/']",
                    "a[href*='/2024/']",
                    "a[href*='/2025/']"
                ],
                "title": [
                    "h1",
                    ".article-title",
                    ".news-title",
                    ".title"
                ],
                "content": [
                    ".article-content",
                    ".news-content",
                    ".content",
                    "#content",
                    ".main-content"
                ],
                "date": [
                    ".publish-time",
                    ".date",
                    ".time",
                    "[class*='time']"
                ],
                "author": [
                    ".author",
                    ".byline",
                    "[class*='author']"
                ]
            },
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive"
            },
            "delay": 2,
            "max_pages": 10,
            "max_articles": 100
        }
    }
    
    return config

def main():
    print("GMW Crawler Debug Tool")
    print("=" * 50)
    
    # Test 1: Basic website access
    article_links = test_gmw_access()
    
    if not article_links:
        print("\n❌ Failed to find any article links. Check website access and selectors.")
        return
    
    print(f"\n✓ Found {len(article_links)} article links")
    
    # Test 2: Article scraping
    successful_articles = test_article_scraping(article_links)
    
    if not successful_articles:
        print("\n❌ Failed to scrape any articles. Check article selectors.")
        return
    
    print(f"\n✓ Successfully scraped {len(successful_articles)} articles")
    
    # Test 3: Generate configuration
    config = generate_gmw_config(successful_articles)
    
    if config:
        # Save configuration
        config_file = "gmw_config.json"
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Configuration saved to {config_file}")
        
        # Display sample results
        print("\n=== Sample Results ===")
        for i, article in enumerate(successful_articles, 1):
            print(f"\nArticle {i}:")
            print(f"Title: {article['title']}")
            print(f"URL: {article['url']}")
            print(f"Content: {article['content']}")
    
    print("\n" + "=" * 50)
    print("Debug complete. Use the generated configuration to update your crawler.")

if __name__ == "__main__":
    main()