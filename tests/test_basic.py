"""
Basic tests to verify the application is working.

Start here! These are the simplest tests to understand.
Run: pytest tests/test_basic.py -v
"""
import pytest


def test_index_page_loads(client):
    """
    Test that the homepage loads successfully.
    
    This is the simplest test - it just checks that when you visit
    the homepage, you get a 200 (success) response.
    """
    response = client.get('/')
    assert response.status_code == 200
    # Check that the page contains expected content
    assert b'Campus Swap' in response.data or b'campus' in response.data.lower()


def test_inventory_page_loads(client):
    """
    Test that the inventory page loads successfully.
    """
    response = client.get('/inventory')
    assert response.status_code == 200


def test_about_page_loads(client):
    """
    Test that the about page loads successfully.
    """
    response = client.get('/about')
    assert response.status_code == 200


def test_health_check_endpoint(client):
    """
    Test the health check endpoint we added.
    
    This endpoint is used by monitoring tools to check if the app is running.
    """
    response = client.get('/health')
    assert response.status_code == 200
    
    # Check that it returns JSON
    assert response.is_json
    
    # Check the response data
    data = response.get_json()
    assert data['status'] == 'healthy'
    assert 'database' in data
    assert 'timestamp' in data


def test_sitemap_generates(client):
    """
    Test that sitemap.xml generates correctly.
    
    Sitemaps help search engines find your pages.
    """
    response = client.get('/sitemap.xml')
    assert response.status_code == 200
    assert 'xml' in response.content_type.lower()
    assert b'urlset' in response.data


def test_robots_txt_exists(client):
    """
    Test that robots.txt exists.
    
    robots.txt tells search engines which pages to crawl.
    """
    response = client.get('/robots.txt')
    assert response.status_code == 200
    assert b'User-agent' in response.data
