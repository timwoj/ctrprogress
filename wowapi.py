# -*- coding: utf-8 -*-

#!/usr/bin/env python

import json
import logging
import os
import time
import ctrpmodels

from google.appengine.ext import ndb
from google.appengine.api import urlfetch
from google.appengine.api import urlfetch_errors

from concurrent import futures

# Method that gets called by the threadpool.  This will fill in the toondata
# dict for the requested toon with either data from Battle.net or with an
# error message to display on the page.  This has to be defined at the
# module level so that the threadpool can call it correctly.    
def handle_result(name, realm, apikey):
    
    toondata = dict()
    
    url = 'https://us.api.battle.net/wow/character/%s/%s?fields=progression,items&locale=en_US&apikey=%s' % (realm, name, apikey)
    try:
        response = urlfetch.fetch(url)
    except urlfetch_errors.DeadlineExceededError:
        logging.error('urlfetch threw DeadlineExceededError on toon %s' % name.encode('ascii','ignore'))
        toondata['toon'] = name
        toondata['status'] = 'nok'
        toondata['reason'] = 'Timeout retrieving data from Battle.net for %s.  Refresh page to try again.' % name
        return toondata
    except urlfetch_errors.DownloadError:
        logging.error('urlfetch threw DownloadError on toon %s' % name.encode('ascii','ignore'))
        toondata['toon'] = name
        toondata['status'] = 'nok'
        toondata['reason'] = 'Network error retrieving data from Battle.net for toon %s.  Refresh page to try again.' % name
        return toondata
    except:
        logging.error('urlfetch threw unknown exception on toon %s' % name.encode('ascii','ignore'))
        toondata['toon'] = name
        toondata['status'] = 'nok'
        toondata['reason'] = 'Unknown error retrieving data from Battle.net for toon %s.  Refresh page to try again.' % name
        return toondata
    
    # change the json from the response into a dict of data and store it
    # into the toondata object that was passed in.
    jsondata = json.loads(response.content)
    toondata.update(jsondata)

    # Blizzard's API will return an error if it couldn't retrieve the data
    # for some reason.  Check for this and log it if it fails.  Note that
    # this response doesn't contain the toon's name so it has to be added
    # in afterwards.
    if 'status' in jsondata and jsondata['status'] == 'nok':
        logging.error('Blizzard API failed to find toon %s for reason: %s' %
                      (name.encode('ascii','ignore'), jsondata['reason']))
        toondata['toon'] = name
        toondata['status'] = 'nok'
        toondata['reason'] = "Error retrieving data for %s from Blizzard API: %s" % (name, jsondata['reason'])
        return toondata

    # we get all of the data here, but we want to filter out just the raids
    # we care about so that it's not so much data returned from the importer
    validraids = [ctrpmodels.Constants.hmname,ctrpmodels.Constants.brfname]
    if toondata['progression'] != None:
        toondata['progression']['raids'] = [r for r in toondata['progression']['raids'] if r['name'] in validraids]

    return toondata

class Importer:

    def load(self, toonlist, data):
        path = os.path.join(os.path.split(__file__)[0],'api-auth.json')
        json_key = json.load(open(path))
        apikey = json_key['blizzard']

        start = time.time()
        
        # Create a threadpool to use to make the URL requests to the Blizzard
        # API. This used to use the urlfetch async methods but I need finer
        # control over how many are running at a time since I'm bumping against
        # the API's quotas for free accounts.
        executor = futures.ThreadPoolExecutor(max_workers=7)
        fs = dict()

        # Request all of the toon data from the blizzard API and determine the
        # group's ilvls, armor type counts and token type counts.  subs are not
        # included in the counts, since they're not really part of the main
        # group.
        for toon in toonlist:
            realm = 'aerie-peak'
            if '/' in toon:
                (toon,realm) = toon.split('/')
                # normalize the realm name
                realm = realm.lower().replace('\'','').replace(' ','-')
            fs[executor.submit(handle_result, toon, realm, apikey)] = toon
        
        # Loop through all of the futures created above and handle each one as
        # they complete.  The return value from the future is the toon data.
        for future in futures.as_completed(fs):
            toon = fs[future]
            if future.exception() is not None:
                logging.info("wowapi generated exception for %s: %s" % (toon, future.exception()))
            else:
                returnval = future.result()
                data.append(returnval)
        fs.clear()

        end = time.time()
        
        logging.info("Time spent retrieving data: %f seconds" % (end-start))
