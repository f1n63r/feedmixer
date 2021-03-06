import unittest
from unittest.mock import MagicMock, call, ANY
import feedparser
from feedmixer import FeedMixer, ParseError
import requests
from requests.exceptions import RequestException
from shelfcache import shelfcache


ATOM_PATH = 'test/test_atom.xml'
RSS_PATH = 'test/test_rss2.xml'

OK = 200

with open(ATOM_PATH, 'r') as f:
    TEST_ATOM = ''.join(f.readlines())

with open(RSS_PATH, 'r') as f:
    TEST_RSS = ''.join(f.readlines())


def mock_shelfcache(return_value=None):
    """Helper function to create a mocked ShelfCache instance.

    Args:
        return_value: the value returned by the mocked shelf.get() method
    """
    mock_shelf = MagicMock()
    mock_shelf.exp_seconds.return_value = 300
    mock_get = MagicMock(return_value=return_value)
    mock_shelf.get = mock_get
    return mock_shelf

def build_response(status=OK, etag='etag', modified='modified', max_age=None):
    """Make a requests.Response object suitable for testing.
    Args:
        status: HTTP status
        exp-time: cache expire time (set to future for fresh cache, past for
            stale cache (defaults to stale))
        etag: etag cache-control header
        modified: last-modified cache-control header
    Returns:
        A Response instance populated according to the arguments.
    """
    headers = {'last-modified': modified, 'etag': etag, 'Cache-Control':
               'max-age={}'.format(max_age)}
    test_response = requests.Response()
    test_response.status_code = status
    test_response.headers = headers
    return test_response


def build_mock_cache_get():
    def mock_fetch(cache, url, **kwargs):
        """Mimics the cache_get() method"""
        if url == "atom":
            resp = MagicMock()
            resp.text = TEST_ATOM
            return resp
        elif url == "fetcherror":
            raise RequestException("fetch error")
        elif url == "parseerror":
            raise ParseError("parse error")
        elif url == "rss":
            resp = MagicMock()
            resp.text = TEST_RSS
            return resp
        else:
            resp = MagicMock(spec=requests.Response)
            resp.text = url
            return resp
    return MagicMock(side_effect=mock_fetch)

class TestMixedEntries(unittest.TestCase):
    def test_empty(self):
        """
        Test with an empty `feeds` list.
        """
        mc = MagicMock()
        fm = FeedMixer(feeds=[], cache_get=mc, cache=mock_shelfcache())
        me = fm.mixed_entries
        mc.assert_not_called()
        self.assertEqual(me, [])

    def test_single_good(self):
        """
        Test with a single good URL.
        """
        mc = build_mock_cache_get()
        cache = mock_shelfcache()
        fm = FeedMixer(feeds=['atom'], cache_get=mc, num_keep=2,
                       cache=cache)
        me = fm.mixed_entries
        mc.assert_called_once_with(cache, 'atom', headers=ANY)
        self.assertEqual(len(me), 2)

    def test_multi_good(self):
        """
        Test with multiple good URLs.
        """
        mc = build_mock_cache_get()
        cache = mock_shelfcache()
        fm = FeedMixer(feeds=['atom', 'rss', 'atom'], cache_get=mc, num_keep=2,
                       cache=cache)
        me = fm.mixed_entries
        mc.assert_has_calls([call(cache, 'atom', headers=ANY),
                             call(cache, 'rss', headers=ANY),
                             call(cache, 'atom',headers=ANY)], any_order=True)
        self.assertEqual(len(me), 6)

    def test_single_exception(self):
        """
        Test with a single URL which throws an exception.
        """
        mc = build_mock_cache_get()
        fm = FeedMixer(feeds=['fetcherror'], cache_get=mc, num_keep=2,
                       cache=mock_shelfcache())
        me = fm.mixed_entries
        self.assertEqual(len(me), 0)
        self.assertIsInstance(fm.error_urls['fetcherror'], RequestException)

    def test_multi_exception(self):
        """
        Test with several URLs which all throw exceptions.
        """
        mc = build_mock_cache_get()
        cache = mock_shelfcache()
        fm = FeedMixer(feeds=['fetcherror', 'parseerror'],
                       cache_get=mc, num_keep=2, cache=cache)
        me = fm.mixed_entries
        mc.assert_has_calls([call(cache, 'fetcherror', headers=ANY),
                             call(cache, 'parseerror', headers=ANY)],
                            any_order=True)
        self.assertEqual(len(me), 0)
        self.assertIsInstance(fm.error_urls['fetcherror'], RequestException)
        self.assertIsInstance(fm.error_urls['parseerror'], ParseError)

    def test_multi_mixed(self):
        """
        Test with several URLs, some of which succeed and some of which throw
        exceptions.
        """
        mc = build_mock_cache_get()
        cache = mock_shelfcache()
        fm = FeedMixer(feeds=['fetcherror', 'atom', 'rss', 'parseerror'],
                       cache_get=mc, num_keep=2, cache=cache)
        me = fm.mixed_entries
        mc.assert_has_calls([call(cache, 'fetcherror', headers=ANY),
                             call(cache, 'atom', headers=ANY),
                             call(cache, 'rss', headers=ANY),
                             call(cache, 'parseerror', headers=ANY)],
                            any_order=True)
        self.assertEqual(len(me), 4)
        self.assertEqual(len(fm.error_urls.keys()), 2)
        self.assertIsInstance(fm.error_urls['fetcherror'], RequestException)
        self.assertIsInstance(fm.error_urls['parseerror'], ParseError)

    def test_keep_all_neg(self):
        """
        Setting num_keep to -1 should keep all the entries.
        """
        mc = build_mock_cache_get()
        fm = FeedMixer(feeds=['atom'], cache_get=mc, num_keep=-1,
                       cache=mock_shelfcache())
        me = fm.mixed_entries
        self.assertEqual(len(me), 12)

    def test_keep_all_zero(self):
        """
        Setting num_keep to 0 should also keep all the entries.
        """
        mc = build_mock_cache_get()
        fm = FeedMixer(feeds=['atom'], cache_get=mc, num_keep=0,
                       cache=mock_shelfcache())
        me = fm.mixed_entries
        self.assertEqual(len(me), 12)

    def test_adds_feed_author(self):
        """
        Test that a feed missing the `author_detail` attribute on its entries
        has it added.
        """
        # Ensure that any future changes to the test file at ATOM_PATH don't
        # include <author> for each entry (which would render this test useless)
        feed = feedparser.parse(TEST_ATOM)
        first = feed['entries'][0]
        if hasattr(first, 'author_detail'):
            del first['author_detail']
        first_entry = feed['entries'][0]
        self.assertNotIn('author_detail', first_entry)
        self.assertNotIn('author_name', first_entry)

        # Now simulate fetching URL, after which the entry should have an
        # `author_name` attribute
        mc = build_mock_cache_get()
        cache = mock_shelfcache()
        fm = FeedMixer(feeds=['atom'], cache_get=mc, num_keep=1,
                       cache=cache)
        me = fm.mixed_entries
        mc.assert_called_once_with(cache, 'atom', headers=ANY)
        self.assertIn('author_name', me[0])


class TestMixedEntriesCache(unittest.TestCase):
    """
    Test that __fetch_entries() correctly replaces response object with
    FeedParserDict for caching.
    """
    def test_fresh_response(self):
        """
        cache_get() has returned a requests.Response object from the requests
        library. Ensure it gets cached as a FeedParserDict.
        """
        # Setup:
        url = 'atom'
        mc = build_mock_cache_get()
        fresh = build_response()
        mock_result = shelfcache.CacheResult(data=fresh, expired=False)
        cache = mock_shelfcache(return_value=mock_result)

        # DUT:
        fm = FeedMixer(feeds=[url], cache_get=mc, cache=cache)
        fm.mixed_entries

        # Asserts:
        cache.replace_data.assert_called_once_with(key=url, data=ANY)

    def test_fresh_parsed(self):
        """
        cache_get() has returned a fresh FeedParserDict object. Ensure we return it.
        """
        # Setup:
        url = 'atom'
        fresh = feedparser.parse(TEST_ATOM)
        def mock_get(*args, **kwargs):
            return fresh
        mc = MagicMock(side_effect=mock_get)
        mock_result = shelfcache.CacheResult(data=fresh, expired=False)
        cache = mock_shelfcache(return_value=mock_result)

        # DUT:
        fm = FeedMixer(feeds=[url], cache_get=mc, cache=cache, num_keep=-1)
        me = fm.mixed_entries

        # Asserts:
        self.assertEqual(len(me), len(fresh.entries))
        cache.create_or_update.assert_not_called()

    def test_stale_parsed(self):
        """
        cache_get() has returned a stale FeedParserDict object. Ensure we
        re-fetch, parse, and cache it.
        """
        # Setup:
        url = 'atom'
        mc = build_mock_cache_get()
        stale = build_response(status=304)
        fresh = feedparser.parse(TEST_ATOM)
        mock_result = shelfcache.CacheResult(data=stale, expired=True)
        cache = mock_shelfcache(return_value=mock_result)

        # DUT:
        fm = FeedMixer(feeds=[url], cache_get=mc, cache=cache, num_keep=-1)
        me = fm.mixed_entries

        # Asserts:
        self.assertEqual(len(me), len(fresh.entries))
        cache.replace_data.assert_called_once_with(key=url, data=ANY)

    def test_saves_headers(self):
        """
        Make sure headers are stored with cached feed. Tests regression fixed
        with 2ee4bc9c245229d564d4b14e7d76ae5879f6eeae
        """
        # Setup:
        url = 'atom'
        resp = build_response()
        mc = MagicMock(return_value=resp)
        headers = resp.headers
        mock_result = shelfcache.CacheResult(data=resp, expired=True)
        cache = mock_shelfcache(return_value=mock_result)

        # DUT:
        fm = FeedMixer(feeds=[url], cache_get=mc, cache=cache, num_keep=-1)
        fm.mixed_entries

        # Asserts:
        saved_headers = cache.replace_data.call_args[1]['data'].headers
        self.assertEqual(headers, saved_headers)


class TestFeed(unittest.TestCase):
    def test_set_feed(self):
        """
        Test that setting the feed property clears existing mixed_entries.
        """
        # First fetch some entries
        mc = build_mock_cache_get()
        fm = FeedMixer(feeds=['atom', 'rss'], cache_get=mc, num_keep=1,
                       cache=mock_shelfcache())
        self.assertEqual(len(fm.mixed_entries), 2)

        # Now clear feeds and assert that mixed_entries is also cleared
        fm.feeds = []
        self.assertEqual(len(fm.mixed_entries), 0)

    def test_set_num_keep(self):
        """
        Test that setting the num_keep property re-fetches the feeds.
        """
        # First fetch some entries
        mc = build_mock_cache_get()
        fm = FeedMixer(feeds=['atom', 'rss'], cache_get=mc, num_keep=2,
                       cache=mock_shelfcache())
        self.assertEqual(len(fm.mixed_entries), 4)

        # Now clear feeds and assert that mixed_entries is also cleared
        fm.num_keep = 1
        self.assertEqual(len(fm.mixed_entries), 2)


class TestAtomFeed(unittest.TestCase):
    def test_atom_feed(self):
        """
        Test serialization as Atom.
        """
        expected = '''<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom"><title>Title</title><link href="" rel="alternate"></link><id></id><updated>2017-04-05T18:48:43Z</updated><entry><title>Uber finds one allegedly stolen Waymo file on an employee’s personal device</title><link href="https://techcrunch.com/2017/04/05/uber-finds-one-allegedly-stolen-waymo-file-on-an-employees-personal-device/" rel="alternate"></link><published>2017-04-05T18:48:43Z</published><updated>2017-04-05T18:48:43Z</updated><author><name>folz</name></author><id>https://news.ycombinator.com/item?id=14044517</id><summary type="html">&lt;p&gt;Article URL: &lt;a href="https://techcrunch.com/2017/04/05/uber-finds-one-allegedly-stolen-waymo-file-on-an-employees-personal-device/"&gt;https://techcrunch.com/2017/04/05/uber-finds-one-allegedly-stolen-waymo-file-on-an-employees-personal-device/&lt;/a&gt;&lt;/p&gt;&lt;p&gt;Comments URL: &lt;a href="https://news.ycombinator.com/item?id=14044517"&gt;https://news.ycombinator.com/item?id=14044517&lt;/a&gt;&lt;/p&gt;&lt;p&gt;Points: 336&lt;/p&gt;&lt;p&gt;# Comments: 206&lt;/p&gt;</summary></entry><entry><title>A Look At Bernie Sanders\' Electoral Socialism</title><link href="http://americancynic.net/log/2016/2/27/a_look_at_bernie_sanders_electoral_socialism/" rel="alternate"></link><published>2016-02-27T22:33:51Z</published><updated>2017-02-15T07:00:00Z</updated><author><name>A. Cynic</name><uri>http://americancynic.net</uri></author><id>tag:americancynic.net,2016-02-27:/log/2016/2/27/a_look_at_bernie_sanders_electoral_socialism/</id><summary type="html">On the difference between democratic socialism and social democracy, the future of capitalism, and the socialist response to the Bernie Sanders presidential campaign.</summary></entry></feed>'''
        mc = build_mock_cache_get()
        fm = FeedMixer(feeds=['atom', 'rss'], cache_get=mc, num_keep=1,
                       cache=mock_shelfcache())
        af = fm.atom_feed()
        self.maxDiff = None
        self.assertIn(expected, af)

    def test_atom_prefer_summary(self):
        """
        Test that passing prefer_summary=True will return the short 'summary'
        """
        expected = '''On the difference between democratic socialism and social democracy, the future of capitalism, and the socialist response to the Bernie Sanders presidential campaign.'''
        mc = build_mock_cache_get()
        cache = mock_shelfcache()
        fm = FeedMixer(feeds=['atom'], cache_get=mc, num_keep=1,
                       cache=cache, prefer_summary=True)
        me = fm.mixed_entries[0]
        self.assertEqual(me.get('description'), expected)

    def test_atom_prefer_content(self):
        """
        Test that passing prefer_summary=False will ask the parser for the full
        entry content.
        """
        mc = build_mock_cache_get()
        cache = mock_shelfcache()
        fm = FeedMixer(feeds=['atom'], cache_get=mc, num_keep=1,
                       cache=cache, prefer_summary=False)
        me = fm.mixed_entries[0]
        self.assertTrue(len(me.get('description')) > 1000)


class TestRSSFeed(unittest.TestCase):
    def test_rss_feed(self):
        """
        Test serialization as RSS.
        """
        expected = '''<?xml version="1.0" encoding="utf-8"?>\n<rss version="2.0"><channel><title>Title</title><link></link><description></description><lastBuildDate>Wed, 05 Apr 2017 18:48:43 -0000</lastBuildDate><item><title>Uber finds one allegedly stolen Waymo file on an employee’s personal device</title><link>https://techcrunch.com/2017/04/05/uber-finds-one-allegedly-stolen-waymo-file-on-an-employees-personal-device/</link><description>&lt;p&gt;Article URL: &lt;a href="https://techcrunch.com/2017/04/05/uber-finds-one-allegedly-stolen-waymo-file-on-an-employees-personal-device/"&gt;https://techcrunch.com/2017/04/05/uber-finds-one-allegedly-stolen-waymo-file-on-an-employees-personal-device/&lt;/a&gt;&lt;/p&gt;&lt;p&gt;Comments URL: &lt;a href="https://news.ycombinator.com/item?id=14044517"&gt;https://news.ycombinator.com/item?id=14044517&lt;/a&gt;&lt;/p&gt;&lt;p&gt;Points: 336&lt;/p&gt;&lt;p&gt;# Comments: 206&lt;/p&gt;</description><dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">folz</dc:creator><pubDate>Wed, 05 Apr 2017 18:48:43 -0000</pubDate><comments>https://news.ycombinator.com/item?id=14044517</comments><guid isPermaLink="false">https://news.ycombinator.com/item?id=14044517</guid></item><item><title>A Look At Bernie Sanders\' Electoral Socialism</title><link>http://americancynic.net/log/2016/2/27/a_look_at_bernie_sanders_electoral_socialism/</link><description>On the difference between democratic socialism and social democracy, the future of capitalism, and the socialist response to the Bernie Sanders presidential campaign.</description><dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">A. Cynic</dc:creator><pubDate>Sat, 27 Feb 2016 22:33:51 -0000</pubDate><guid isPermaLink="false">tag:americancynic.net,2016-02-27:/log/2016/2/27/a_look_at_bernie_sanders_electoral_socialism/</guid></item></channel></rss>'''
        mc = build_mock_cache_get()
        fm = FeedMixer(feeds=['atom', 'rss'], cache_get=mc, num_keep=1,
                       cache=mock_shelfcache())
        rf = fm.rss_feed()
        self.maxDiff = None
        self.assertIn(expected, rf)


class TestJSONFeed(unittest.TestCase):
    def test_json_feed(self):
        """
        Test serialization as JSON.
        """
        expected = r'''{"version": "https://jsonfeed.org/version/1", "title": "Title", "home_page_url": "", "description": "", "items": [{"title": "Uber finds one allegedly stolen Waymo file on an employee\u2019s personal device", "content_html": "<p>Article URL: <a href=\"https://techcrunch.com/2017/04/05/uber-finds-one-allegedly-stolen-waymo-file-on-an-employees-personal-device/\">https://techcrunch.com/2017/04/05/uber-finds-one-allegedly-stolen-waymo-file-on-an-employees-personal-device/</a></p><p>Comments URL: <a href=\"https://news.ycombinator.com/item?id=14044517\">https://news.ycombinator.com/item?id=14044517</a></p><p>Points: 336</p><p># Comments: 206</p>", "url": "https://techcrunch.com/2017/04/05/uber-finds-one-allegedly-stolen-waymo-file-on-an-employees-personal-device/", "id": "https://news.ycombinator.com/item?id=14044517", "author": {"name": "folz"}, "date_published": "2017-04-05T18:48:43Z", "date_modified": "2017-04-05T18:48:43Z"}, {"title": "A Look At Bernie Sanders' Electoral Socialism", "content_html": "On the difference between democratic socialism and social democracy, the future of capitalism, and the socialist response to the Bernie Sanders presidential campaign.", "url": "http://americancynic.net/log/2016/2/27/a_look_at_bernie_sanders_electoral_socialism/", "id": "tag:americancynic.net,2016-02-27:/log/2016/2/27/a_look_at_bernie_sanders_electoral_socialism/", "author": {"name": "A. Cynic", "url": "http://americancynic.net"}, "date_published": "2016-02-27T22:33:51Z", "date_modified": "2017-02-15T07:00:00Z"}]}'''
        mc = build_mock_cache_get()
        fm = FeedMixer(feeds=['atom', 'rss'], cache_get=mc, num_keep=1,
                       cache=mock_shelfcache())
        jf = fm.json_feed()
        self.maxDiff = None
        self.assertIn(expected, jf)
