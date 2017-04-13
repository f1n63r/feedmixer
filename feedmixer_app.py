from feedmixer import FeedMixer
import falcon
from typing import NamedTuple, List
import json
import urllib
import urllib.parse

ParsedQS = NamedTuple('ParsedQS', [('f', List[str]),
                                   ('n', int)])

# Vars to config:
TITLE = "FeedMixer feed"
DESC = "{type} feed created by FeedMixer."
# The path where the cache database file will be created:
DBPATH = "fmcache.db"


def parse_qs(req: falcon.Request) -> ParsedQS:
    qs = falcon.uri.parse_query_string(req.query_string)
    feeds = qs.get('f', [])
    n = qs.get('n', -1)
    if not isinstance(feeds, list): feeds = [feeds] # NOQA
    return ParsedQS(feeds, int(n))


class MixedFeed:
    def __init__(self, ftype: str='atom') -> None:
        super().__init__()
        self.ftype = ftype

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        feeds, n = parse_qs(req)
        fm = FeedMixer(feeds=feeds, num_keep=n, title=TITLE,
                       desc=DESC.format(type=self.ftype), link=req.uri,
                       cache_path=DBPATH)

        # dynamically find and call appropriate method based on ftype:
        method_name = "{}_feed".format(self.ftype)
        method = getattr(fm, method_name)
        resp.body = method()

        if fm.error_urls:
            # There were errors; report them in the 'X-fm-errors' http header as
            # a url-encoded JSON hash
            error_dict = {}
            for url, e in fm.error_urls.items():
                err_str = str(e)
                if hasattr(e, 'status'):
                    err_str += " ({})".format(e.status)
                error_dict[url] = err_str
            json_err = urllib.parse.quote(json.dumps(error_dict))
            resp.append_header('X-fm-errors', json_err)

        resp.content_type = "application/{}".format(self.ftype)
        resp.status = falcon.HTTP_200

atom = MixedFeed(ftype='atom')
rss = MixedFeed(ftype='rss')
jsn = MixedFeed(ftype='json')

api = application = falcon.API()
api.add_route('/atom', atom)
api.add_route('/rss', rss)
api.add_route('/json', jsn)
