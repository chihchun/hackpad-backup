#!/usr/bin/python
import logging

import os
import subprocess
import urllib
import json
import time
import re
import sys

import requests
from requests_oauthlib import OAuth1Session

g_logger = None;
g_format = 'txt'
g_timezone = '+0800'
g_delay = 1

# only if you know what it is
g_out_of_order_commit = False

api_keys = {}

re_site = '^[\w-]+$'

class HackpadException(Exception):
    pass

def load_api_keys():
    for line in file('api_keys.txt'):
        line = re.sub('#.*', '', line)
        if not line:
            continue
        data = line.split()
        if len(data) == 3:
            key, secret, site = data
        else:
            site = ''
            key, secret  = data
        api_keys[site] = key, secret

class Hackpad:
    def __init__(self, site=''):
        if site not in api_keys:
            raise ValueError, 'no api key for this site "%s"' % site

        if site:
            self.base = 'https://%s.hackpad.com' % site
        else:
            self.base = 'https://hackpad.com'
        self.hackpad = OAuth1Session(*api_keys[site])

    def _get(self, url):
        g_logger.debug(url);
        for i in range(5):
            r = self.hackpad.get(url)
            if r.status_code not in (200, 401):
                g_logger.warn('status_code:', r.status_code, ', content:', r.content);
                time.sleep(2)
                continue
            break

        # for debug
        with file('tmp.txt', 'w') as f:
            f.write(r.content)

        return r

    def get_pad_content(self, padid, format='html', revision=None):
        if revision:
            url = self.base + '/api/1.0/pad/%s/content/%s.%s' % (padid, revision, format)
        else:
            url = self.base + '/api/1.0/pad/%s/content.%s' % (padid, format)

        r = self._get(url)
        return r.content

    def list_updated_pads(self, timestamp):
        url = self.base + '/api/1.0/edited-since/%d' % int(timestamp)
        r = self._get(url)
        o = json.loads(r.text)
        if 'success' in o and not o['success']:
            raise HackpadException, o['error']
        if len(o) == 1000:
            raise HackpadException, 'too many pads edited'
        return o

    def list_revisions(self, padid):
        url = self.base + '/api/1.0/pad/%s/revisions' % padid
        r = self._get(url)
        try:
            o = json.loads(r.text)
        except ValueError:
            g_logger.error(r.text);
            raise
        if 'success' in o and not o['success']:
            if o['error'] == 'Not found':  # maybe real "Not found", maybe no access right
                return []  # workaround
            raise HackpadException, o['error']
        return o

    def list_all_pads(self):
        url = self.base + '/api/1.0/pads/all'
        r = self._get(url)
        o = json.loads(r.text)
        if 'success' in o and not o['success']:
            raise HackpadException, o['error']
        return o

class Storage:
    def __init__(self, site):
        self.site = site
        self.data = []

        assert re.match(re_site, site)
        self.base = 'data/%s' % (site or 'main')
        if not os.path.exists(self.base):
            os.makedirs(self.base)

        if not os.path.exists(os.path.join(self.base, '.git')):
            cmd = 'cd %s && git init' % self.base,
            subprocess.check_call(cmd, shell=True)

    def verify_padid(self, padid):
        if not re.match(r'^[\w%.~-]+$', padid):
            raise ValueError

    def _get_store_filename(self, padid):
        # check for security
        self.verify_padid(padid)
        assert not re.match(r'^\.', padid)
        return '%s.%s' % (padid, g_format)

    def _get_store_path(self, padid):
        path = os.path.join(self.base, self._get_store_filename(padid))
        return path

    def _git_log(self, padid=None):
        if padid is None:
            cmd = 'cd %s && git log -n 1 --pretty="format:%%B"' % (self.base)
            g_logger.debug(cmd);
            try:
                output = subprocess.check_output(cmd, shell=True)
            except subprocess.CalledProcessError:
                return None
        else:
            path = self._get_store_path(padid)
            if not os.path.exists(path):
                return None

            cmd = 'cd %s && git log -n 1 --pretty="format:%%B" -- "%s"' % (self.base, self._get_store_filename(padid))
            g_logger.debug(cmd);
            output = subprocess.check_output(cmd, shell=True)
        return output

    def get_last_backup_time(self):
        log = self._git_log()
        if log is None:
            return 0
        g_logger.debug(log)
        m = re.search('^timestamp (\d+(?:\.\d+)?)$', log, re.M)
        if not m:
            return 0
        return float(m.group(1))

    def get_version(self, padid):
        log = self._git_log(padid)
        if log is None:
            return 0

        m = re.search('^version (\d+)$', log, re.M)
        assert m
        return int(m.group(1))

    def add(self, t, rev, padid, content):
        self.data.append((t, rev, padid, content))

    def _git_commit(self, padid, datestr, msg, content):
        path = self._get_store_path(padid)

        if os.path.exists(path):
            old_content = file(path).read()
            if old_content == content:
                return

        with open(path, 'w') as f:
            f.write(content)

        fn = self._get_store_filename(padid)
        cmd = 'cd %s && git add -- "%s" && git commit --date="%s" -a -F -' % (
                self.base, fn, datestr)
        g_logger.debug(cmd)
        g_logger.debug (msg.encode('utf8'))
        p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE)
        stdout, stderr = p.communicate(msg.encode('utf8'))
        assert p.returncode == 0


    def commit(self):
        # sort by timestamp
        self.data.sort()

        for t, rev, padid, content in self.data:

            datestr = '%s %s' % (int(t), g_timezone)
            msg = (
                    'timestamp %(timestamp)s\n' +
                    'version %(version)s\n' +
                    'authors %(authors)s\n') % dict(
                    timestamp=t,
                    version=rev['endRev'],
                    authors=','.join(rev['authors']),
                    )

            self._git_commit(padid, datestr, msg, content)

        self.data = []


def backup_site(site):
    hackpad = Hackpad(site)
    storage = Storage(site)

    if g_out_of_order_commit:
        last_backup = 0
    else:
        last_backup = storage.get_last_backup_time()

    now = time.time()

    try:
        padids = hackpad.list_updated_pads(last_backup)
    except HackpadException:
        padids = hackpad.list_all_pads()

    for padid in padids:
        storage.verify_padid(padid)

    for padid in padids:
        g_logger.debug("processing %s" % padid);

        if re.match(r'^[.]', padid):
            logger.error("I don't like this padid: %s" % padid)
            continue

        last_version = storage.get_version(padid)

        for rev in hackpad.list_revisions(padid):
            del rev['htmlDiff']
            '''sample:
            {u'endRev': 215, u'authorPics': [u'https://graph.facebook.com/1234567/picture?type=square'], u'timestamp': 1375949266.528, u'startRev': 160, u'authors': [u'John Doe'], u'emails': []}
            '''

            # ignore old changes
            # NOTE, endRev=0 means just created and has not been modified yet
            if last_version >= rev['endRev']:
                continue
            # in order to avoid race condition, ignore recent changes
            if rev['timestamp'] > now - 60:
                continue

            g_logger.debug(rev);

            content = hackpad.get_pad_content(padid, format=g_format, revision=rev['endRev'])

            storage.add(rev['timestamp'], rev, padid, content)
            time.sleep(g_delay)

        if g_out_of_order_commit:
            storage.commit()

    storage.commit()

def run_backup():
    for line in file('backup_list.txt'):
        line = re.sub('#.*', '', line).strip()
        if not line:
            continue
        site, item = line.split('/')
        assert re.match(re_site, site)

        if item != '*':
            raise NotImplementedError
        else:
            backup_site(site)

def main():
    load_api_keys()

    run_backup()

if __name__ == '__main__':
    # create console handler and set level to debug
    ch = logging.StreamHandler()
    # add formatter to ch
    ch.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    g_logger = logging.getLogger('console')
    g_logger.setLevel(logging.DEBUG)
    g_logger.addHandler(ch)

    # g_logger.setLevel(logging.DEBUG)
    # g_logger.setLevel(logging.INFO)
    main()
