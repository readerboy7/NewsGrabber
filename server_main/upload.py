import threading
import os
import json
import time
import re

import file
import settings

import internetarchive
import requests


class Upload(threading.Thread):

    """Uploading and sorting of files is done here."""

    def __init__(self):
        threading.Thread.__init__(self)
        self.concurrent_uploads = 0
        self.max_item_size = settings.max_item_size
        self.access_key = settings.access_key
        self.secret_key = settings.secret_key
        self.uploads_file = file.File(os.path.join(settings.dir_last_upload, 'uploads.json'))
        self.uploads = {}
        self.items_file = file.File(os.path.join(settings.dir_last_upload, 'items.json'))
        self.items = {}

    def run(self):
        self.read()
        self.upload()

    def write(self):
        self.items_file.write_json(self.items)
        self.uploads_file.write_json(self.uploads)

    def read(self):
        items = self.items_file.read_json()
        if items:
            self.items = items

        uploads = self.uploads_file.read_json()
        if uploads:
            self.uploads = uploads

    def upload(self):
        while True:
            for f in [
                    f for f in os.listdir(settings.dir_ready) if f.endswith('.warc.gz')
                        and not os.path.isfile(os.path.join(settings.dir_ready, f+'.upload'))]:
                while not settings.upload_running:
                    time.sleep(1)
                time.sleep(1)
                while self.concurrent_uploads > settings.max_concurrent_uploads or not self.upload_allowed():
                    time.sleep(10)
                self.concurrent_uploads += 1
                open(os.path.join(settings.dir_ready, f+'.upload'), 'a').close()
                date = re.search(r'([0-9]{4}-[0-9]{2}-[0-9]{2})', f).group(1)
                if not f in self.uploads:
                    self.uploads[f] = {}
                    self.uploads[f]['date'] = date.replace('-', '')
                    self.uploads[f]['size'] = os.path.getsize(os.path.join(settings.dir_ready, f))
                    if not self.uploads[f]['date'] in self.items:
                        self.items[self.uploads[f]['date']] = {}
                        self.items[self.uploads[f]['date']]['item_num'] = 0
                        self.items[self.uploads[f]['date']]['item_size'] = 0
                    elif self.items[self.uploads[f]['date']]['item_size'] > self.max_item_size:
                        self.items[self.uploads[f]['date']]['item_num'] += 1
                        self.items[self.uploads[f]['date']]['item_size'] = 0
                    self.items[self.uploads[f]['date']]['item_size'] += self.uploads[f]['size']
                    self.uploads[f]['item_num'] = self.items[self.uploads[f]['date']]['item_num']
                    self.uploads[f]['item_size'] = self.items[self.uploads[f]['date']]['item_size']
                name = self.uploads[f]['date']+'_'+str(self.uploads[f]['item_num']).zfill(4)
                ia_args = {'title': 'Archive Team Newsgrab: {name}'.format(name=name),
                           'mediatype': 'web',
                           'description': 'A collection of news articles grabbed from a wide variety of sources around the world automatically by Archive Team scripts.',
                           'collection': 'archiveteam_newssites',
                           'date': date}
                threading.Thread(target=self.upload_single, args=(name, f, ia_args)).start()

    def upload_single(self, name, f, ia_args):
        with open(settings.keys, 'r') as f:
            access_key, secret_key = f.read().strip().split(':')
        try:
            internetarchive.upload('archiveteam_newssites_{name}'.format(name=name),
                os.path.join(settings.dir_ready, f),
                metadata=ia_args,
                access_key=access_key,
                secret_key=secret_key,
                queue_derive=True,
                verify=True,
                verbose=True,
                delete=True,
                retries=10,
                retries_sleep=300)
        except:
            pass # see code below
        self.concurrent_uploads -= 1
        os.remove(os.path.join(settings.dir_ready, f+'.upload'))
        if os.path.isfile(os.path.join(settings.dir_ready, f)):
            settings.irc_bot.send('PRIVMSG', '{name} uploaded unsuccessful.'.format(
                name=f), settings.irc_channel_bot)

    def upload_allowed(self):
        response = requests.get('https://s3.us.archive.org/?check_limit=1&accesskey='
                +self.access_key)
        if response.status_code == 200:
            try:
                data = json.loads(response.text)
                if ('over_limit' in data and data['over_limit'] is not 0) \
                    or ('detail' in data and 'rationing_engaged' in data['detail']
                        and data['detail']['rationing_engaged'] is not 0):
                    return False
            except:
                pass
            return True
        else:
            return False