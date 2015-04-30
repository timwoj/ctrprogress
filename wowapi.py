# -*- coding: utf-8 -*-

#!/usr/bin/env python

import json
import logging
import os
import time

from google.appengine.ext import ndb
from google.appengine.api import urlfetch
from google.appengine.api import urlfetch_errors

class Importer:

    def load(self, toonlist, data):
        path = os.path.join(os.path.split(__file__)[0],'api-auth.json')
        json_key = json.load(open(path))
        apikey = json_key['blizzard']

        # Request all of the toon data from the blizzard API and determine the
        # group's ilvls, armor type counts and token type counts.  subs are not
        # included in the counts, since they're not really part of the main
        # group.
        for toon in toonlist:
            try:
                # TODO: this object can probably be a class instead of another dict
                newdata = dict()
                data.append(newdata)
                
                realm = 'aerie-peak'
                if '/' in toon:
                    (toon,realm) = toon.split('/')
                    # normalize the realm name
                    realm = realm.lower().replace('\'','').replace(' ','-')

                url = 'https://us.api.battle.net/wow/character/%s/%s?fields=progression,items&locale=en_US&apikey=%s' % (realm, toon, apikey)
                # create the rpc object for the fetch method.  the deadline
                # defaults to 5 seconds, but that seems to be too short for the
                # Blizzard API site sometimes.  setting it to 10 helps a little
                # but it makes page loads a little slower.
                rpc = urlfetch.create_rpc(10)
                rpc.callback = self.create_callback(rpc, toon, newdata)
                urlfetch.make_fetch_call(rpc, url)
                newdata['rpc'] = rpc
                newdata['toon'] = toon

                # The Blizzard API has a limit of 10 calls per second.  Sleep here
                # for a very brief time to avoid hitting that limit.
                time.sleep(0.1)
            except:
                logging.error('Failed to create rpc for %s' % toon)

        # Now that all of the RPC calls have been created, loop through the data
        # dictionary one more time and wait for each fetch to be completed. Once
        # all of the waits finish, then we have all of the data from the
        # Blizzard API and can loop through all of it and build the page.
        start = time.time()
        for d in data:
            try:
                d['rpc'].wait()
            except Exception as e:
                logging.error('Waiting for rpc failed: %s' % str(e))
        end = time.time()
        
        logging.info("Time spent retrieving data: %f seconds" % (end-start))

    # Callback that handles the result of the call to the Blizzard API.  This will fill in
    # the toondata dict for the requested toon with either data from Battle.net or with an
    # error message to display on the page.
    def handle_result(self, rpc, name, toondata):

        try:
            response = rpc.get_result()
        except urlfetch_errors.DeadlineExceededError:
            logging.error('urlfetch threw DeadlineExceededError on toon %s' % name.encode('ascii','ignore'))
            toondata['toon'] = name
            toondata['status'] = 'nok'
            toondata['reason'] = 'Timeout retrieving data from Battle.net for %s.  Refresh page to try again.' % name
            return
        except urlfetch_errors.DownloadError:
            logging.error('urlfetch threw DownloadError on toon %s' % name.encode('ascii','ignore'))
            toondata['toon'] = name
            toondata['status'] = 'nok'
            toondata['reason'] = 'Network error retrieving data from Battle.net for toon %s.  Refresh page to try again.' % name
            return
        except:
            logging.error('urlfetch threw unknown exception on toon %s' % name.encode('ascii','ignore'))
            toondata['toon'] = name
            toondata['status'] = 'nok'
            toondata['reason'] = 'Unknown error retrieving data from Battle.net for toon %s.  Refresh page to try again.' % name
            return

        # change the json from the response into a dict of data and store it
        # into the toondata object that was passed in.
        jsondata = json.loads(response.content)
        toondata.update(jsondata);

        # Blizzard's API will return an error if it couldn't retrieve the data
        # for some reason.  Check for this and log it if it fails.  Note that
        # this response doesn't contain the toon's name so it has to be added
        # in afterwards.
        if 'status' in jsondata and jsondata['status'] == 'nok':
            logging.error('Blizzard API failed to find toon %s for reason: %s' %
                  (name.encode('ascii','ignore'), jsondata['reason']))
            toondata['toon'] = name
            toondata['reason'] = "Error retrieving data for %s from Blizzard API: %s" % (name, jsondata['reason'])
            return

        # we get all of the data here, but we want to filter out just the raids
        # we care about so that it's not so much data returned from the importer
        validraids = ['Highmaul','Blackrock Foundry']
        if toondata['progression'] != None:
            toondata['progression']['raids'] = [r for r in toondata['progression']['raids'] if r['name'] in validraids]

        del toondata['rpc']

    def create_callback(self, rpc, name, toondata):
        return lambda: self.handle_result(rpc, name, toondata)
